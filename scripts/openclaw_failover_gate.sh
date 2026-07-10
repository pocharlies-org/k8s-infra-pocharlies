#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
shift || true
STATE_FILE=""
TARGET_NODE=""
REQUIRE_OFF_TARGET=false
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
EXPECTED_KUBE_CONTEXT="${EXPECTED_KUBE_CONTEXT:-x86-k3s}"
NAMESPACE="openclaw-qwen36"

while (($#)); do
  case "$1" in
    --state-file) STATE_FILE="$2"; shift 2 ;;
    --target-node) TARGET_NODE="$2"; shift 2 ;;
    --require-off-target) REQUIRE_OFF_TARGET=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$MODE" != pre && "$MODE" != post ]] ||
   [[ -z "$STATE_FILE" || -z "$TARGET_NODE" ]]; then
  echo "Usage: $0 {pre|post} --state-file FILE --target-node NODE [--require-off-target]" >&2
  exit 2
fi

kctl() { "$KUBECTL_BIN" "$@"; }
fail() { echo "OpenClaw failover gate: FAIL: $*" >&2; exit 1; }

context="$(kctl config current-context 2>/dev/null || true)"
[[ "$context" == "$EXPECTED_KUBE_CONTEXT" ]] ||
  fail "kubectl context is '$context', expected '$EXPECTED_KUBE_CONTEXT'"
kctl get --raw=/readyz >/dev/null || fail "Kubernetes API readyz failed"

pods_json="$(kctl -n "$NAMESPACE" get pods -o json)"
terminating="$(jq '[.items[] | select(.metadata.deletionTimestamp != null)] | length' <<<"$pods_json")"
[[ "$terminating" == 0 ]] || fail "$terminating OpenClaw pod(s) are still Terminating"
unsafe_nodes="$(jq '[
  .items[] |
  select(.metadata.deletionTimestamp == null) |
  select(.status.phase == "Running") |
  select(
    .spec.nodeName != "ks5-cp-1" and
    .spec.nodeName != "ks5-cp-2" and
    .spec.nodeName != "ks5-cp-3" and
    .spec.nodeName != "sauvage"
  ) |
  {pod:.metadata.name,node:.spec.nodeName}
]' <<<"$pods_json")"
[[ "$(jq 'length' <<<"$unsafe_nodes")" == 0 ]] ||
  fail "active OpenClaw pod outside the four approved OVH nodes: $(jq -c . <<<"$unsafe_nodes")"

gateway_record() {
  local component="$1"
  local service="$2"
  local container="$3"
  local matches pod node
  matches="$(jq --arg component "$component" '
    [.items[] |
      select(.metadata.labels["app.kubernetes.io/component"] == $component) |
      select(.metadata.deletionTimestamp == null) |
      select(.status.phase == "Running") |
      select((.status.containerStatuses // []) | length > 0) |
      select(all(.status.containerStatuses[]; .ready == true))]
  ' <<<"$pods_json")"
  [[ "$(jq 'length' <<<"$matches")" == 1 ]] ||
    fail "expected exactly one fully Ready $component gateway pod"
  pod="$(jq -r '.[0].metadata.name' <<<"$matches")"
  node="$(jq -r '.[0].spec.nodeName' <<<"$matches")"
  case "$node" in
    ks5-cp-1|ks5-cp-2|ks5-cp-3|sauvage) ;;
    *) fail "$component gateway is on $node, outside the four approved OVH nodes" ;;
  esac
  jq -n \
    --arg component "$component" \
    --arg service "$service" \
    --arg container "$container" \
    --arg pod "$pod" \
    --arg node "$node" \
    '{component:$component,service:$service,container:$container,pod:$pod,node:$node}'
}

main_gateway="$(gateway_record openclaw openclaw-qwen36-openclaw openclaw)"
social_gateway="$(gateway_record social openclaw-qwen36-social social)"
readonly_gateway="$(gateway_record readonly openclaw-qwen36-readonly readonly)"
gateways="$(jq -s '.' < <(printf '%s\n%s\n%s\n' "$main_gateway" "$social_gateway" "$readonly_gateway"))"
router_gateway="$(gateway_record telegram-router openclaw-qwen36-telegram-router telegram-router)"
protected_singletons="$(jq -s '.' < <(printf '%s\n%s\n%s\n%s\n' \
  "$main_gateway" "$social_gateway" "$readonly_gateway" "$router_gateway"))"

deployments_json="$(kctl -n "$NAMESPACE" get deployments -o json)"
unavailable="$(jq '[.items[] | select((.status.availableReplicas // 0) != (.spec.replicas // 0)) | .metadata.name] | length' <<<"$deployments_json")"
[[ "$unavailable" == 0 ]] || fail "$unavailable OpenClaw deployment(s) are unavailable"

router_pod="$(jq -r '.pod' <<<"$router_gateway")"
router_status="$(kctl -n "$NAMESPACE" exec "$router_pod" -c telegram-router -- node -e 'fetch("http://127.0.0.1:8787/status").then(async r=>{if(!r.ok)process.exit(1);process.stdout.write(await r.text())})')"
jq -e '
  .paused == false and
  .deliveryAckEnabled == true and
  .activeBackend == "blue" and
  (.activeBackendUrl | contains("openclaw-qwen36-social")) and
  (.queueDepth // 0) == 0 and
  (.workerBusy // false) == false
' <<<"$router_status" >/dev/null ||
  fail "Telegram router backend, ACK, pause, queue, or worker state is unsafe"

if [[ "$MODE" == pre ]]; then
  failover_components="$(jq --arg target "$TARGET_NODE" '[.[] | select(.node == $target) | .component]' <<<"$protected_singletons")"
  mkdir -p "$(dirname "$STATE_FILE")"
  jq -n \
    --argjson started "$(date +%s)" \
    --arg targetNode "$TARGET_NODE" \
    --argjson gateways "$gateways" \
    --argjson protectedSingletons "$protected_singletons" \
    --argjson failoverComponents "$failover_components" \
    --argjson router "$router_status" \
    '{startedEpoch:$started,targetNode:$targetNode,gateways:$gateways,protectedSingletons:$protectedSingletons,failoverRequiredComponents:$failoverComponents,router:$router}' >"$STATE_FILE"
  chmod 0600 "$STATE_FILE"
  jq '{targetNode,failoverRequiredComponents,protectedSingletons:[.protectedSingletons[] | {component,pod,node}],queueDepth:.router.queueDepth,deadCount:.router.deadCount}' "$STATE_FILE"
  if [[ "$REQUIRE_OFF_TARGET" == true ]] &&
     [[ "$(jq 'length' <<<"$failover_components")" != 0 ]]; then
    fail "target $TARGET_NODE hosts protected singleton(s): $(jq -c . <<<"$failover_components"); perform a controlled failover first"
  fi
  exit 0
fi

[[ -f "$STATE_FILE" ]] || fail "pre-failover state file is missing"
recorded_target_node="$(jq -r '.targetNode' "$STATE_FILE")"
[[ "$recorded_target_node" == "$TARGET_NODE" ]] ||
  fail "state file target $recorded_target_node does not match $TARGET_NODE"

while IFS=$'\t' read -r component service container pod node; do
  source_node="$(jq -r --arg component "$component" '.gateways[] | select(.component == $component) | .node' "$STATE_FILE")"
  if [[ "$source_node" == "$TARGET_NODE" && "$node" == "$source_node" ]]; then
    fail "$component gateway has not failed over from drained node $source_node"
  fi
  ready_endpoints="$(kctl -n "$NAMESPACE" get endpointslices.discovery.k8s.io -l "kubernetes.io/service-name=$service" -o json | jq '[.items[].endpoints[]? | select(.conditions.ready == true and (.conditions.terminating // false) == false)] | length')"
  ((ready_endpoints >= 1)) || fail "$component gateway Service has no ready endpoint"
  kctl -n "$NAMESPACE" exec "$pod" -c "$container" -- node -e \
    'fetch("http://127.0.0.1:8080/readyz").then(async r=>{if(!r.ok)process.exit(1);const b=await r.json();if(b.ready!==true)process.exit(1)})'
done < <(jq -r '.[] | [.component,.service,.container,.pod,.node] | @tsv' <<<"$gateways")

source_router_node="$(jq -r '.protectedSingletons[] | select(.component == "telegram-router") | .node' "$STATE_FILE")"
current_router_node="$(jq -r '.node' <<<"$router_gateway")"
if [[ "$source_router_node" == "$TARGET_NODE" && "$current_router_node" == "$source_router_node" ]]; then
  fail "Telegram router has not failed over from drained node $source_router_node"
fi

pvc_names_json="$(kctl -n "$NAMESPACE" get pvc -o json | jq '[.items[] | select((.spec.storageClassName // "") | startswith("longhorn")) | .spec.volumeName | select(. != null and startswith("pvc-"))]')"
longhorn_json="$(kctl -n longhorn-system get volumes.longhorn.io -o json)"
matched_pvcs="$(jq --argjson names "$pvc_names_json" '[.items[] | select(.metadata.name as $n | $names | index($n))] | length' <<<"$longhorn_json")"
[[ "$matched_pvcs" == "$(jq 'length' <<<"$pvc_names_json")" ]] ||
  fail "one or more OpenClaw PVCs are missing from Longhorn"
bad_pvcs="$(jq --argjson names "$pvc_names_json" '[.items[] | select(.metadata.name as $n | $names | index($n)) | select(.status.robustness != "healthy" or .status.state != "attached" or .status.currentNodeID == "ubuntu") | {name:.metadata.name,state:.status.state,robustness:.status.robustness,node:.status.currentNodeID}]' <<<"$longhorn_json")"
[[ "$(jq 'length' <<<"$bad_pvcs")" == 0 ]] ||
  fail "OpenClaw Longhorn attachment is unsafe: $(jq -c . <<<"$bad_pvcs")"

pre_dead="$(jq -r '.router.deadCount // 0' "$STATE_FILE")"
post_dead="$(jq -r '.deadCount // 0' <<<"$router_status")"
((post_dead <= pre_dead)) ||
  fail "Telegram dead-letter count increased from $pre_dead to $post_dead"

finished="$(date +%s)"
started="$(jq -r '.startedEpoch' "$STATE_FILE")"
rto_seconds=$((finished - started))
moves="$(jq -n --argjson before "$(jq '.protectedSingletons' "$STATE_FILE")" --argjson after "$protected_singletons" '
  [$before[] as $old | $after[] | select(.component == $old.component) |
    {component:.component,sourceNode:$old.node,destinationNode:.node,pod:.pod,moved:($old.node != .node)}]
')"
result_file="${STATE_FILE%.json}.result.json"
jq -n \
  --argjson started "$started" \
  --argjson finished "$finished" \
  --argjson rtoSeconds "$rto_seconds" \
  --arg targetNode "$TARGET_NODE" \
  --argjson moves "$moves" \
  --argjson router "$router_status" \
  '{startedEpoch:$started,finishedEpoch:$finished,rtoUpperBoundSeconds:$rtoSeconds,targetNode:$targetNode,moves:$moves,router:$router}' >"$result_file"
chmod 0600 "$result_file"
jq '{rtoUpperBoundSeconds,targetNode,moves,queueDepth:.router.queueDepth,deadCount:.router.deadCount,oldestQueuedAgeSeconds:.router.oldestQueuedAgeSeconds}' "$result_file"
