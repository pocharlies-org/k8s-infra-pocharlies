#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
shift || true
STATE_FILE=""
TARGET_NODE=""
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
EXPECTED_KUBE_CONTEXT="${EXPECTED_KUBE_CONTEXT:-x86-k3s}"
OPENCLAW_SMOKE_REPO="${OPENCLAW_SMOKE_REPO:-}"
NAMESPACE="${OPENCLAW_NAMESPACE:-openclaw-qwen36}"
APPLICATION="${OPENCLAW_ARGO_APPLICATION:-openclaw-qwen36}"
MAINTENANCE_LOCK="${OPENCLAW_MAINTENANCE_LOCK:-openclaw-qwen36-maintenance-lock}"
TIMEOUT_SECONDS="${OPENCLAW_FAILOVER_TIMEOUT_SECONDS:-900}"
POLL_SECONDS="${OPENCLAW_FAILOVER_POLL_SECONDS:-3}"
FAILURE_ARMED=false
ROUTER_MUST_REPAUSE=false
ARGO_FROZEN=false

while (($#)); do
  case "$1" in
    --state-file) STATE_FILE="$2"; shift 2 ;;
    --target-node) TARGET_NODE="$2"; shift 2 ;;
    --smoke-repo) OPENCLAW_SMOKE_REPO="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

usage() {
  cat >&2 <<'USAGE'
Usage:
  openclaw_maintenance_failover.sh prepare --target-node NODE --state-file /ABS/PATH [--smoke-repo /ABS/REPO]
  openclaw_maintenance_failover.sh verify  --target-node NODE --state-file /ABS/PATH [--smoke-repo /ABS/REPO]
  openclaw_maintenance_failover.sh abort   --target-node NODE --state-file /ABS/PATH [--smoke-repo /ABS/REPO]
USAGE
  exit 2
}

fail() { echo "OpenClaw maintenance failover: FAIL: $*" >&2; exit 1; }
kctl() { "$KUBECTL_BIN" "$@"; }

component_field() {
  local component="$1" field="$2"
  case "$component:$field" in
    openclaw:deployment) echo openclaw-qwen36-openclaw ;;
    openclaw:container) echo openclaw ;;
    openclaw:pdb) echo openclaw-qwen36-openclaw ;;
    openclaw:pvc) echo openclaw-qwen36-openclaw-data-longhorn ;;
    readonly:deployment) echo openclaw-qwen36-readonly ;;
    readonly:container) echo readonly ;;
    readonly:pdb) echo openclaw-qwen36-readonly ;;
    readonly:pvc) echo openclaw-qwen36-readonly-data-longhorn ;;
    social:deployment) echo openclaw-qwen36-social ;;
    social:container) echo social ;;
    social:pdb) echo openclaw-qwen36-social ;;
    social:pvc) echo openclaw-qwen36-social-data-longhorn ;;
    telegram-router:deployment) echo openclaw-qwen36-telegram-router ;;
    telegram-router:container) echo telegram-router ;;
    telegram-router:pdb) echo openclaw-qwen36-telegram-router ;;
    telegram-router:pvc) echo openclaw-qwen36-telegram-router-data-longhorn ;;
    *) fail "unknown component field $component:$field" ;;
  esac
}

ready_pod_json() {
  local component="$1" deployment selector
  deployment="$(component_field "$component" deployment)"
  selector="$(kctl -n "$NAMESPACE" get deployment "$deployment" -o json |
    jq -er '.spec.selector.matchLabels | to_entries | map("\(.key)=\(.value)") | join(",")')"
  kctl -n "$NAMESPACE" get pods -l "$selector" -o json | jq -ec '
    [.items[] |
      select(.metadata.deletionTimestamp == null) |
      select(.status.phase == "Running") |
      select(any(.status.conditions[]?; .type == "Ready" and .status == "True")) |
      select((.status.containerStatuses // []) | length > 0) |
      select(all(.status.containerStatuses[]; .ready == true))
    ] |
    if length == 1 then .[0]
    else error("expected exactly one fully Ready pod") end
  '
}

router_status() {
  local pod
  pod="$(ready_pod_json telegram-router | jq -r '.metadata.name')"
  # This single-quoted source is JavaScript evaluated in the container.
  # shellcheck disable=SC2016
  kctl -n "$NAMESPACE" exec "$pod" -c telegram-router -- node -e '
    fetch("http://127.0.0.1:8787/status")
      .then(async response => {
        if (!response.ok) throw new Error(`status ${response.status}`);
        process.stdout.write(await response.text());
      })
      .catch(error => { console.error(error.message); process.exit(1); });
  '
}

router_admin() {
  local path="$1" pod
  pod="$(ready_pod_json telegram-router | jq -r '.metadata.name')"
  # This single-quoted source is JavaScript evaluated in the container.
  # shellcheck disable=SC2016
  kctl -n "$NAMESPACE" exec "$pod" -c telegram-router -- node -e '
    const path = process.argv[1];
    const token = process.env.TELEGRAM_ROUTER_ADMIN_TOKEN || "";
    if (!token) throw new Error("missing router admin token");
    fetch(`http://127.0.0.1:8787${path}`, {
      method: "POST",
      headers: {authorization: `Bearer ${token}`},
    })
      .then(async response => {
        const body = await response.text();
        if (!response.ok) throw new Error(`${path} ${response.status} ${body}`);
      })
      .catch(error => { console.error(error.message); process.exit(1); });
  ' "$path" >/dev/null
}

wait_router_paused_and_idle() {
  local deadline=$((SECONDS + TIMEOUT_SECONDS)) status
  while ((SECONDS < deadline)); do
    status="$(router_status)"
    if jq -e '.paused == true and .workerBusy == false' <<<"$status" >/dev/null; then
      return 0
    fi
    sleep "$POLL_SECONDS"
  done
  fail "router did not become paused and idle"
}

wait_router_resumed_and_drained() {
  local baseline_dead="$1" deadline=$((SECONDS + TIMEOUT_SECONDS)) status dead
  while ((SECONDS < deadline)); do
    status="$(router_status)"
    dead="$(jq -r '.deadCount // 0' <<<"$status")"
    ((dead <= baseline_dead)) || fail "router dead-letter count increased from $baseline_dead to $dead"
    if jq -e '.paused == false and .workerBusy == false and (.queueDepth // 0) == 0' \
      <<<"$status" >/dev/null; then
      return 0
    fi
    sleep "$POLL_SECONDS"
  done
  fail "router did not resume and drain before timeout"
}

require_argo_and_smoke_revision() {
  local application_json live_revision repo_revision origin
  application_json="$(kctl -n argocd get application.argoproj.io "$APPLICATION" -o json)"
  jq -e --arg namespace "$NAMESPACE" '
    .status.sync.status == "Synced" and
    .status.health.status == "Healthy" and
    ((.status.operationState.phase // "") != "Running") and
    ((.metadata.annotations["argocd.argoproj.io/skip-reconcile"] // "false") != "true") and
    .spec.destination.namespace == $namespace and
    .spec.source.repoURL == "https://github.com/pocharlies-org/k8s-openclaw-qwen36-pocharlies" and
    .spec.source.path == "helm/openclaw-qwen36"
  ' <<<"$application_json" >/dev/null || fail "OpenClaw Argo Application is not stable Synced/Healthy"
  live_revision="$(jq -r '.status.sync.revision // empty' <<<"$application_json")"

  [[ "$OPENCLAW_SMOKE_REPO" == /* ]] || fail "--smoke-repo must be an absolute path"
  [[ -d "$OPENCLAW_SMOKE_REPO/.git" || -f "$OPENCLAW_SMOKE_REPO/.git" ]] ||
    fail "smoke repo is not a Git checkout"
  [[ -z "$(git -C "$OPENCLAW_SMOKE_REPO" status --porcelain --untracked-files=normal)" ]] ||
    fail "smoke repo is dirty"
  origin="$(git -C "$OPENCLAW_SMOKE_REPO" remote get-url origin)"
  [[ "$origin" =~ pocharlies-org/k8s-openclaw-qwen36-pocharlies(\.git)?$ ]] ||
    fail "unexpected smoke repo origin"
  repo_revision="$(git -C "$OPENCLAW_SMOKE_REPO" rev-parse HEAD)"
  [[ "$live_revision" =~ ^[0-9a-f]{40}$ && "$repo_revision" == "$live_revision" ]] ||
    fail "smoke repo revision $repo_revision does not match live revision $live_revision"
}

acquire_maintenance_lock() {
  local lock_id="$1" manifest
  manifest="$(kctl -n "$NAMESPACE" create configmap "$MAINTENANCE_LOCK" \
    --from-literal="lockId=$lock_id" \
    --from-literal="targetNode=$TARGET_NODE" \
    --from-literal="startedEpoch=$(date +%s)" \
    --dry-run=client -o json | jq '
      .metadata.labels["app.kubernetes.io/name"]="openclaw-qwen36" |
      .metadata.labels["app.kubernetes.io/component"]="maintenance-lock" |
      .immutable=true
    ')"
  printf '%s' "$manifest" | kctl create -f - >/dev/null ||
    fail "maintenance lock already exists or could not be created"
}

assert_maintenance_lock() {
  local expected
  [[ -f "$STATE_FILE" ]] || fail "state file is missing"
  expected="$(jq -r '.lockId // empty' "$STATE_FILE")"
  [[ -n "$expected" ]] || fail "state file has no lock ID"
  kctl -n "$NAMESPACE" get configmap "$MAINTENANCE_LOCK" -o json | jq -e \
    --arg lock "$expected" --arg target "$TARGET_NODE" '
      .immutable == true and .data.lockId == $lock and .data.targetNode == $target
    ' >/dev/null || fail "maintenance lock ownership does not match the state file"
}

release_maintenance_lock() {
  assert_maintenance_lock
  kctl -n "$NAMESPACE" delete configmap "$MAINTENANCE_LOCK" --wait=true >/dev/null
}

freeze_argo() {
  local patch
  [[ -f "$STATE_FILE" ]] || fail "state file is missing before Argo freeze"
  # Arm restoration before the first mutation so a partial freeze is reversible.
  ARGO_FROZEN=true
  patch='{"spec":{"syncPolicy":{"automated":{"enabled":false,"selfHeal":false}}}}'
  kctl -n argocd patch application.argoproj.io "$APPLICATION" --type=merge -p "$patch" >/dev/null
  kctl -n argocd annotate application.argoproj.io "$APPLICATION" \
    argocd.argoproj.io/skip-reconcile=true --overwrite >/dev/null
  kctl -n argocd get application.argoproj.io "$APPLICATION" -o json | jq -e '
    .spec.syncPolicy.automated.enabled == false and
    .spec.syncPolicy.automated.selfHeal == false and
    .metadata.annotations["argocd.argoproj.io/skip-reconcile"] == "true" and
    ((.status.operationState.phase // "") != "Running")
  ' >/dev/null || fail "Argo freeze was not observed"
}

assert_argo_frozen() {
  [[ "$ARGO_FROZEN" == true ]] || fail "Argo is not frozen"
  kctl -n argocd get application.argoproj.io "$APPLICATION" -o json | jq -e '
    .spec.syncPolicy.automated.enabled == false and
    .spec.syncPolicy.automated.selfHeal == false and
    .metadata.annotations["argocd.argoproj.io/skip-reconcile"] == "true" and
    ((.status.operationState.phase // "") != "Running")
  ' >/dev/null || fail "Argo freeze was lost during the maintenance window"
}

restore_argo_best_effort() {
  local sync_policy patch skip_present skip_value
  [[ -f "$STATE_FILE" ]] || return 0
  sync_policy="$(jq -c '.argoBefore.syncPolicy // empty' "$STATE_FILE")"
  [[ -n "$sync_policy" ]] || return 0
  patch="$(jq -nc --argjson value "$sync_policy" \
    '[{"op":"replace","path":"/spec/syncPolicy","value":$value}]')"
  kctl -n argocd patch application.argoproj.io "$APPLICATION" --type=json -p "$patch" >/dev/null || return 1
  skip_present="$(jq -r '.argoBefore.skipReconcilePresent' "$STATE_FILE")"
  if [[ "$skip_present" == true ]]; then
    skip_value="$(jq -r '.argoBefore.skipReconcileValue' "$STATE_FILE")"
    kctl -n argocd annotate application.argoproj.io "$APPLICATION" \
      "argocd.argoproj.io/skip-reconcile=$skip_value" --overwrite >/dev/null || return 1
  else
    kctl -n argocd annotate application.argoproj.io "$APPLICATION" \
      argocd.argoproj.io/skip-reconcile- >/dev/null 2>&1 || true
  fi
  ARGO_FROZEN=false
}

assert_argo_restored() {
  local application_json expected_sync skip_present skip_value
  application_json="$(kctl -n argocd get application.argoproj.io "$APPLICATION" -o json)"
  expected_sync="$(jq -c '.argoBefore.syncPolicy' "$STATE_FILE")"
  jq -e --argjson expected "$expected_sync" '.spec.syncPolicy == $expected' \
    <<<"$application_json" >/dev/null || fail "Argo sync policy was not restored exactly"
  skip_present="$(jq -r '.argoBefore.skipReconcilePresent' "$STATE_FILE")"
  if [[ "$skip_present" == true ]]; then
    skip_value="$(jq -r '.argoBefore.skipReconcileValue' "$STATE_FILE")"
    jq -e --arg expected "$skip_value" \
      '.metadata.annotations["argocd.argoproj.io/skip-reconcile"] == $expected' \
      <<<"$application_json" >/dev/null || fail "prior Argo skip-reconcile annotation was not restored"
  else
    jq -e '(.metadata.annotations // {}) | has("argocd.argoproj.io/skip-reconcile") | not' \
      <<<"$application_json" >/dev/null || fail "maintenance skip-reconcile annotation remains"
  fi
}

run_paused_social_smoke() {
  local status pod audit baseline_dead current_dead
  assert_argo_frozen
  status="$(router_status)"
  jq -e '.paused == true and .workerBusy == false' <<<"$status" >/dev/null ||
    fail "paused social smoke requires a paused idle router"
  baseline_dead="$(jq -r '.routerBefore.deadCount // 0' "$STATE_FILE")"
  current_dead="$(jq -r '.deadCount // 0' <<<"$status")"
  ((current_dead <= baseline_dead)) ||
    fail "dead-letter count increased from $baseline_dead to $current_dead while paused"
  pod="$(ready_pod_json social | jq -r '.metadata.name')"
  kctl -n "$NAMESPACE" exec "$pod" -c social -- node -e '
    fetch("http://127.0.0.1:8080/readyz")
      .then(async response => {
        if (!response.ok) process.exit(1);
        const body = await response.json();
        if (body.ready !== true) process.exit(1);
      })
      .catch(() => process.exit(1));
  '
  audit="$(kctl -n "$NAMESPACE" exec "$pod" -c social -- openclaw security audit --deep --json)"
  jq -e '.summary.critical == 0' <<<"$audit" >/dev/null ||
    fail "paused social security audit has critical findings"
}

run_smoke() {
  local script="$1" shim_dir kubectl_path rc=0
  [[ -x "$OPENCLAW_SMOKE_REPO/scripts/$script" || -r "$OPENCLAW_SMOKE_REPO/scripts/$script" ]] ||
    fail "missing smoke script $script"
  if [[ "$KUBECTL_BIN" == */* ]]; then
    kubectl_path="$(cd "$(dirname "$KUBECTL_BIN")" && pwd -P)/$(basename "$KUBECTL_BIN")"
  else
    kubectl_path="$(command -v "$KUBECTL_BIN")"
  fi
  shim_dir="$(mktemp -d)"
  printf '#!/usr/bin/env bash\nexec %q --context %q "$@"\n' \
    "$kubectl_path" "$EXPECTED_KUBE_CONTEXT" >"$shim_dir/kubectl"
  chmod 0755 "$shim_dir/kubectl"
  (
    export PATH="$shim_dir:$PATH"
    export OPENCLAW_NAMESPACE="$NAMESPACE"
    cd "$OPENCLAW_SMOKE_REPO"
    bash "scripts/$script"
  ) || rc=$?
  rm -rf "$shim_dir"
  ((rc == 0)) || return "$rc"
}

placement_snapshot() {
  local component pod_json deployment container pdb pvc pv volume_json
  for component in openclaw readonly social telegram-router; do
    pod_json="$(ready_pod_json "$component")"
    deployment="$(component_field "$component" deployment)"
    container="$(component_field "$component" container)"
    pdb="$(component_field "$component" pdb)"
    pvc="$(component_field "$component" pvc)"
    pv="$(kctl -n "$NAMESPACE" get pvc "$pvc" -o jsonpath='{.spec.volumeName}')"
    [[ "$pv" == pvc-* ]] || fail "$pvc is not bound to a Longhorn PV"
    volume_json="$(kctl -n longhorn-system get volumes.longhorn.io "$pv" -o json)"
    jq -n \
      --arg component "$component" \
      --arg deployment "$deployment" \
      --arg container "$container" \
      --arg pdb "$pdb" \
      --arg pvc "$pvc" \
      --arg pv "$pv" \
      --arg pod "$(jq -r '.metadata.name' <<<"$pod_json")" \
      --arg uid "$(jq -r '.metadata.uid' <<<"$pod_json")" \
      --arg node "$(jq -r '.spec.nodeName' <<<"$pod_json")" \
      --arg volumeState "$(jq -r '.status.state // ""' <<<"$volume_json")" \
      --arg volumeNode "$(jq -r '.status.currentNodeID // ""' <<<"$volume_json")" \
      --arg robustness "$(jq -r '.status.robustness // ""' <<<"$volume_json")" \
      '{component:$component,deployment:$deployment,container:$container,pdb:$pdb,pvc:$pvc,pv:$pv,pod:$pod,uid:$uid,node:$node,volumeState:$volumeState,volumeNode:$volumeNode,robustness:$robustness}'
  done | jq -s '.'
}

assert_all_pdbs_restored() {
  local component pdb
  for component in openclaw readonly social telegram-router; do
    pdb="$(component_field "$component" pdb)"
    kctl -n "$NAMESPACE" get pdb "$pdb" -o json | jq -e '
      .spec.minAvailable == 1 and
      (.spec | has("maxUnavailable") | not) and
      .status.observedGeneration == .metadata.generation
    ' >/dev/null || fail "$pdb is not restored to minAvailable=1"
  done
}

restore_all_pdbs_best_effort() {
  local component pdb
  for component in openclaw readonly social telegram-router; do
    pdb="$(component_field "$component" pdb)"
    kctl -n "$NAMESPACE" patch pdb "$pdb" --type=merge \
      -p '{"spec":{"minAvailable":1}}' >/dev/null 2>&1 || true
  done
}

update_state_status() {
  local status="$1" temporary
  [[ -f "$STATE_FILE" ]] || return 0
  temporary="${STATE_FILE}.incoming"
  jq --arg status "$status" --argjson epoch "$(date +%s)" \
    '.status=$status | .lastUpdateEpoch=$epoch' "$STATE_FILE" >"$temporary"
  chmod 0600 "$temporary"
  mv -f "$temporary" "$STATE_FILE"
}

failure_handler() {
  local rc=$?
  trap - EXIT HUP INT TERM
  if ((rc == 0)) && [[ "$FAILURE_ARMED" != true ]]; then
    exit 0
  fi
  ((rc != 0)) || rc=1
  if [[ "$FAILURE_ARMED" == true ]]; then
    set +e
    restore_all_pdbs_best_effort
    if [[ "$ARGO_FROZEN" == true ]]; then
      restore_argo_best_effort || true
    fi
    if [[ "$ROUTER_MUST_REPAUSE" == true ]]; then
      router_admin /admin/pause || true
    fi
    update_state_status failed
    echo "OpenClaw maintenance failover failed closed: PDBs and Argo policy restored; lock retained; router and target remain paused/cordoned when already mutated." >&2
  fi
  exit "$rc"
}
trap failure_handler EXIT HUP INT TERM

quiesce_component() {
  local component="$1" pod container
  [[ "$component" != telegram-router ]] || return 0
  pod="$(ready_pod_json "$component" | jq -r '.metadata.name')"
  container="$(component_field "$component" container)"
  kctl -n "$NAMESPACE" exec "$pod" -c "$container" -- env \
    OPENCLAW_PRESTOP_FAIL_ON_TIMEOUT=true \
    OPENCLAW_PRESTOP_DRAIN_TIMEOUT_SECONDS=600 \
    OPENCLAW_PRESTOP_POLL_SECONDS=5 \
    openclaw-wait-for-quiescent
}

restore_pdb() {
  local component="$1" pdb deadline=$((SECONDS + 60))
  pdb="$(component_field "$component" pdb)"
  kctl -n "$NAMESPACE" patch pdb "$pdb" --type=merge \
    -p '{"spec":{"minAvailable":1}}' >/dev/null
  while ((SECONDS < deadline)); do
    if kctl -n "$NAMESPACE" get pdb "$pdb" -o json | jq -e '
      .spec.minAvailable == 1 and
      .status.observedGeneration == .metadata.generation
    ' >/dev/null; then
      return 0
    fi
    sleep 1
  done
  fail "$pdb restoration was not observed by the PDB controller"
}

evict_with_controlled_pdb_window() {
  local component="$1" pod="$2" uid="$3" pdb payload attempts_remaining=5 accepted=false
  assert_argo_frozen
  pdb="$(component_field "$component" pdb)"
  kctl -n "$NAMESPACE" get pdb "$pdb" -o json | jq -e '
    .spec.minAvailable == 1 and (.spec | has("maxUnavailable") | not)
  ' >/dev/null || fail "$pdb does not have the reviewed minAvailable=1 contract"

  payload="$(jq -nc --arg name "$pod" --arg namespace "$NAMESPACE" --arg uid "$uid" '
    {apiVersion:"policy/v1",kind:"Eviction",metadata:{name:$name,namespace:$namespace},deleteOptions:{preconditions:{uid:$uid}}}
  ')"
  while ((attempts_remaining > 0)); do
    attempts_remaining=$((attempts_remaining - 1))
    assert_argo_frozen
    kctl -n "$NAMESPACE" patch pdb "$pdb" --type=merge \
      -p '{"spec":{"minAvailable":0}}' >/dev/null
    for _ in 1 2 3 4 5; do
      if kctl -n "$NAMESPACE" get pdb "$pdb" -o json | jq -e '
        .spec.minAvailable == 0 and
        .status.observedGeneration == .metadata.generation and
        (.status.disruptionsAllowed // 0) >= 1
      ' >/dev/null; then
        break
      fi
      sleep 1
    done
    if printf '%s' "$payload" | kctl create --raw \
      "/api/v1/namespaces/${NAMESPACE}/pods/${pod}/eviction" -f - >/dev/null 2>&1; then
      accepted=true
      break
    fi
    restore_pdb "$component"
    sleep 2
  done
  restore_pdb "$component"
  [[ "$accepted" == true ]] || fail "Eviction API rejected $component after five controlled PDB windows"
}

wait_old_pod_gone() {
  local pod="$1" deadline=$((SECONDS + TIMEOUT_SECONDS))
  while ((SECONDS < deadline)); do
    if ! kctl -n "$NAMESPACE" get pod "$pod" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$POLL_SECONDS"
  done
  fail "old pod $pod did not terminate"
}

verify_volume_attachment() {
  local component="$1" node="$2" pvc pv deadline=$((SECONDS + TIMEOUT_SECONDS))
  pvc="$(component_field "$component" pvc)"
  pv="$(kctl -n "$NAMESPACE" get pvc "$pvc" -o jsonpath='{.spec.volumeName}')"
  while ((SECONDS < deadline)); do
    if [[ "$ARGO_FROZEN" == true ]]; then
      assert_argo_frozen
    fi
    if kctl get volumeattachments.storage.k8s.io -o json | jq -e \
      --arg pv "$pv" --arg node "$node" '
        [.items[] |
          select(.metadata.deletionTimestamp == null) |
          select(.spec.source.persistentVolumeName == $pv)
        ] as $attachments |
        ($attachments | length) == 1 and
        $attachments[0].spec.nodeName == $node and
        $attachments[0].status.attached == true
      ' >/dev/null 2>&1 &&
      kctl -n longhorn-system get volumes.longhorn.io "$pv" -o json | jq -e \
        --arg node "$node" '
          .status.state == "attached" and
          .status.currentNodeID == $node and
          .status.robustness == "healthy"
        ' >/dev/null 2>&1; then
      return 0
    fi
    sleep "$POLL_SECONDS"
  done
  fail "$component did not complete Kubernetes detach/attach and healthy Longhorn attach on $node"
}

move_component_if_needed() {
  local component="$1" old_json old_pod old_uid old_node deployment new_json new_node
  old_json="$(ready_pod_json "$component")"
  old_node="$(jq -r '.spec.nodeName' <<<"$old_json")"
  [[ "$old_node" == "$TARGET_NODE" ]] || return 0
  old_pod="$(jq -r '.metadata.name' <<<"$old_json")"
  old_uid="$(jq -r '.metadata.uid' <<<"$old_json")"
  deployment="$(component_field "$component" deployment)"

  quiesce_component "$component"
  evict_with_controlled_pdb_window "$component" "$old_pod" "$old_uid"
  wait_old_pod_gone "$old_pod"
  kctl -n "$NAMESPACE" rollout status "deployment/$deployment" --timeout="${TIMEOUT_SECONDS}s"
  assert_argo_frozen
  new_json="$(ready_pod_json "$component")"
  [[ "$(jq -r '.metadata.uid' <<<"$new_json")" != "$old_uid" ]] ||
    fail "$component pod UID did not change after accepted eviction"
  new_node="$(jq -r '.spec.nodeName' <<<"$new_json")"
  [[ "$new_node" != "$TARGET_NODE" ]] || fail "$component rescheduled onto cordoned target"
  verify_volume_attachment "$component" "$new_node"
}

assert_all_protected_off_target() {
  local component pod_json
  for component in openclaw readonly social telegram-router; do
    pod_json="$(ready_pod_json "$component")"
    [[ "$(jq -r '.spec.nodeName' <<<"$pod_json")" != "$TARGET_NODE" ]] ||
      fail "$component remains on $TARGET_NODE"
    verify_volume_attachment "$component" "$(jq -r '.spec.nodeName' <<<"$pod_json")"
  done
}

require_common() {
  local context
  [[ "$MODE" == prepare || "$MODE" == verify || "$MODE" == abort ]] || usage
  [[ "$STATE_FILE" == /* && -n "$TARGET_NODE" ]] || usage
  case "$TARGET_NODE" in
    ks5-cp-1|ks5-cp-2|ks5-cp-3|sauvage) ;;
    *) fail "target must be one of the four reviewed OVH OpenClaw destinations" ;;
  esac
  for command in jq git bash; do
    command -v "$command" >/dev/null 2>&1 || fail "required executable missing: $command"
  done
  if [[ "$KUBECTL_BIN" == */* ]]; then
    [[ -x "$KUBECTL_BIN" ]] || fail "kubectl is missing: $KUBECTL_BIN"
  else
    command -v "$KUBECTL_BIN" >/dev/null 2>&1 || fail "kubectl is missing: $KUBECTL_BIN"
  fi
  context="$(kctl config current-context)"
  [[ "$context" == "$EXPECTED_KUBE_CONTEXT" ]] ||
    fail "kubectl context is $context, expected $EXPECTED_KUBE_CONTEXT"
  kctl get --raw=/readyz >/dev/null
  if [[ "$MODE" != abort ]]; then
    require_argo_and_smoke_revision
  fi
}

prepare_failover() {
  local confirmation node_json initial_placements initial_router target_count survivors application_json lock_id
  confirmation="move-openclaw-off-${TARGET_NODE}"
  [[ "${CONFIRM_OPENCLAW_MAINTENANCE_FAILOVER:-}" == "$confirmation" ]] ||
    fail "set CONFIRM_OPENCLAW_MAINTENANCE_FAILOVER=$confirmation"
  [[ ! -e "$STATE_FILE" ]] || fail "state file already exists: $STATE_FILE"
  mkdir -p "$(dirname "$STATE_FILE")"
  umask 077

  node_json="$(kctl get node "$TARGET_NODE" -o json)"
  jq -e '
    any(.status.conditions[]?; .type == "Ready" and .status == "True") and
    .metadata.labels["node-pool"] == "ks5-nvme"
  ' <<<"$node_json" >/dev/null || fail "$TARGET_NODE is not a Ready KS5 NVMe node"
  survivors="$(kctl get nodes -l node-pool=ks5-nvme -o json | jq \
    --arg target "$TARGET_NODE" '[.items[] |
      select(.metadata.name != $target) |
      select((.spec.unschedulable // false) == false) |
      select(any(.status.conditions[]?; .type == "Ready" and .status == "True"))
    ] | length')"
  ((survivors >= 2)) || fail "fewer than two other Ready schedulable KS5 nodes"

  initial_placements="$(placement_snapshot)"
  target_count="$(jq --arg target "$TARGET_NODE" '[.[] | select(.node == $target)] | length' <<<"$initial_placements")"
  ((target_count > 0)) || fail "no protected singleton is on $TARGET_NODE; no failover is required"
  initial_router="$(router_status)"
  jq -e '
    .paused == false and .workerBusy == false and (.queueDepth // 0) == 0 and
    .deliveryAckEnabled == true and .activeBackend == "blue"
  ' <<<"$initial_router" >/dev/null || fail "router is not active, idle and queue-empty before failover"
  assert_all_pdbs_restored
  application_json="$(kctl -n argocd get application.argoproj.io "$APPLICATION" -o json)"
  lock_id="failover-${TARGET_NODE}-$(date -u +%Y%m%dT%H%M%SZ)-$$"

  jq -n \
    --arg status preparing \
    --arg targetNode "$TARGET_NODE" \
    --argjson startedEpoch "$(date +%s)" \
    --argjson targetInitiallyUnschedulable "$(jq '.spec.unschedulable // false' <<<"$node_json")" \
    --argjson placements "$initial_placements" \
    --argjson router "$initial_router" \
    --arg lockId "$lock_id" \
    --argjson syncPolicy "$(jq '.spec.syncPolicy' <<<"$application_json")" \
    --argjson skipReconcilePresent "$(jq '(.metadata.annotations // {}) | has("argocd.argoproj.io/skip-reconcile")' <<<"$application_json")" \
    --arg skipReconcileValue "$(jq -r '.metadata.annotations["argocd.argoproj.io/skip-reconcile"] // ""' <<<"$application_json")" \
    '{status:$status,targetNode:$targetNode,startedEpoch:$startedEpoch,targetInitiallyUnschedulable:$targetInitiallyUnschedulable,placementsBefore:$placements,routerBefore:$router,cordonedByHelper:false,lockId:$lockId,argoBefore:{syncPolicy:$syncPolicy,skipReconcilePresent:$skipReconcilePresent,skipReconcileValue:$skipReconcileValue}}' \
    >"${STATE_FILE}.incoming"
  chmod 0600 "${STATE_FILE}.incoming"
  mv -f "${STATE_FILE}.incoming" "$STATE_FILE"
  FAILURE_ARMED=true

  acquire_maintenance_lock "$lock_id"
  freeze_argo
  router_admin /admin/pause
  wait_router_paused_and_idle
  ROUTER_MUST_REPAUSE=true
  if [[ "$(jq -r '.spec.unschedulable // false' <<<"$node_json")" != true ]]; then
    kctl cordon "$TARGET_NODE" >/dev/null
    jq '.cordonedByHelper=true' "$STATE_FILE" >"${STATE_FILE}.incoming"
    chmod 0600 "${STATE_FILE}.incoming"
    mv -f "${STATE_FILE}.incoming" "$STATE_FILE"
  fi

  move_component_if_needed openclaw
  move_component_if_needed readonly
  move_component_if_needed social
  move_component_if_needed telegram-router
  assert_all_pdbs_restored
  assert_all_protected_off_target

  run_paused_social_smoke
  run_smoke smoke-workboard.sh
  run_smoke smoke-codex-k8s.sh
  assert_argo_frozen
  router_admin /admin/resume
  wait_router_resumed_and_drained "$(jq -r '.routerBefore.deadCount // 0' "$STATE_FILE")"
  run_smoke smoke-social-gateway.sh
  restore_argo_best_effort || fail "could not restore the exact Argo sync policy"
  assert_argo_restored
  require_argo_and_smoke_revision
  assert_maintenance_lock

  placement_snapshot >"${STATE_FILE}.placements-after.incoming"
  jq --slurpfile placements "${STATE_FILE}.placements-after.incoming" \
    --argjson completedEpoch "$(date +%s)" '
      .status="prepared" |
      .preparedEpoch=$completedEpoch |
      .placementsAfter=$placements[0]
    ' "$STATE_FILE" >"${STATE_FILE}.incoming"
  rm -f "${STATE_FILE}.placements-after.incoming"
  chmod 0600 "${STATE_FILE}.incoming"
  mv -f "${STATE_FILE}.incoming" "$STATE_FILE"
  ROUTER_MUST_REPAUSE=false
  FAILURE_ARMED=false
  echo "OpenClaw maintenance failover prepared: all protected singletons are off $TARGET_NODE; router resumed; target remains cordoned."
}

verify_failover() {
  local status baseline_dead node_json
  [[ -f "$STATE_FILE" ]] || fail "state file is missing"
  [[ "$(jq -r '.targetNode' "$STATE_FILE")" == "$TARGET_NODE" ]] || fail "state target mismatch"
  status="$(jq -r '.status' "$STATE_FILE")"
  [[ "$status" == prepared ]] || fail "state is $status, expected prepared"
  assert_maintenance_lock
  node_json="$(kctl get node "$TARGET_NODE" -o json)"
  jq -e '
    (.spec.unschedulable // false) == false and
    any(.status.conditions[]?; .type == "Ready" and .status == "True")
  ' <<<"$node_json" >/dev/null || fail "$TARGET_NODE is not Ready and uncordoned after maintenance"
  assert_all_pdbs_restored
  assert_all_protected_off_target
  baseline_dead="$(jq -r '.routerBefore.deadCount // 0' "$STATE_FILE")"
  wait_router_resumed_and_drained "$baseline_dead"
  run_smoke smoke-social-gateway.sh
  run_smoke smoke-workboard.sh
  run_smoke smoke-codex-k8s.sh
  require_argo_and_smoke_revision
  release_maintenance_lock
  jq --argjson verifiedEpoch "$(date +%s)" '
    .status="verified" | .verifiedEpoch=$verifiedEpoch
  ' "$STATE_FILE" >"${STATE_FILE}.incoming"
  chmod 0600 "${STATE_FILE}.incoming"
  mv -f "${STATE_FILE}.incoming" "$STATE_FILE"
  echo "OpenClaw maintenance failover verified after maintenance on $TARGET_NODE."
}

abort_failover() {
  local confirmation baseline_dead status component
  confirmation="abort-openclaw-failover-${TARGET_NODE}"
  [[ "${CONFIRM_OPENCLAW_MAINTENANCE_ABORT:-}" == "$confirmation" ]] ||
    fail "set CONFIRM_OPENCLAW_MAINTENANCE_ABORT=$confirmation"
  [[ -f "$STATE_FILE" ]] || fail "state file is missing"
  [[ "$(jq -r '.targetNode' "$STATE_FILE")" == "$TARGET_NODE" ]] || fail "state target mismatch"
  status="$(jq -r '.status' "$STATE_FILE")"
  [[ "$status" == failed || "$status" == preparing ]] ||
    fail "abort is only valid for failed or preparing state, not $status"
  assert_maintenance_lock
  FAILURE_ARMED=true
  for component in openclaw readonly social telegram-router; do
    restore_pdb "$component"
  done
  assert_all_pdbs_restored
  kctl -n "$NAMESPACE" rollout status deployment/openclaw-qwen36-openclaw --timeout="${TIMEOUT_SECONDS}s"
  kctl -n "$NAMESPACE" rollout status deployment/openclaw-qwen36-readonly --timeout="${TIMEOUT_SECONDS}s"
  kctl -n "$NAMESPACE" rollout status deployment/openclaw-qwen36-social --timeout="${TIMEOUT_SECONDS}s"
  kctl -n "$NAMESPACE" rollout status deployment/openclaw-qwen36-telegram-router --timeout="${TIMEOUT_SECONDS}s"
  baseline_dead="$(jq -r '.routerBefore.deadCount // 0' "$STATE_FILE")"
  if jq -e '.paused == true' <<<"$(router_status)" >/dev/null; then
    ROUTER_MUST_REPAUSE=true
    router_admin /admin/resume
  fi
  wait_router_resumed_and_drained "$baseline_dead"
  require_argo_and_smoke_revision
  run_smoke smoke-social-gateway.sh
  run_smoke smoke-workboard.sh
  run_smoke smoke-codex-k8s.sh
  ROUTER_MUST_REPAUSE=false
  if [[ "$(jq -r '.cordonedByHelper // false' "$STATE_FILE")" == true ]]; then
    kctl uncordon "$TARGET_NODE" >/dev/null
  fi
  release_maintenance_lock
  jq --argjson abortedEpoch "$(date +%s)" '
    .status="aborted" | .abortedEpoch=$abortedEpoch
  ' "$STATE_FILE" >"${STATE_FILE}.incoming"
  chmod 0600 "${STATE_FILE}.incoming"
  mv -f "${STATE_FILE}.incoming" "$STATE_FILE"
  FAILURE_ARMED=false
  echo "OpenClaw maintenance failover aborted safely; router active and helper cordon removed."
}

require_common
case "$MODE" in
  prepare) prepare_failover ;;
  verify) verify_failover ;;
  abort) abort_failover ;;
  *) usage ;;
esac
