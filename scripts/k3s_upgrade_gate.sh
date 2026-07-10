#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
shift || true
EXPECTED_VERSIONS=""
TARGET_NODE=""
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
EXPECTED_KUBE_CONTEXT="${EXPECTED_KUBE_CONTEXT:-x86-k3s}"

while (($#)); do
  case "$1" in
    --expected-versions) EXPECTED_VERSIONS="$2"; shift 2 ;;
    --target-node) TARGET_NODE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$MODE" != preflight && "$MODE" != post-node && "$MODE" != final ]]; then
  echo "Usage: $0 {preflight|post-node|final} --expected-versions VERSION[,VERSION] [--target-node NODE]" >&2
  exit 2
fi
if [[ -z "$EXPECTED_VERSIONS" ]]; then
  echo "--expected-versions is required" >&2
  exit 2
fi
if [[ "$MODE" == post-node && -z "$TARGET_NODE" ]]; then
  echo "--target-node is required for post-node" >&2
  exit 2
fi

failures=0
pass() { printf 'PASS %s\n' "$*"; }
warn() { printf 'WARN %s\n' "$*" >&2; }
fail() { printf 'FAIL %s\n' "$*" >&2; failures=$((failures + 1)); }
kctl() { "$KUBECTL_BIN" "$@"; }

for command in "$KUBECTL_BIN" jq; do
  if [[ "$command" == */* ]]; then
    [[ -x "$command" ]] || fail "required executable missing: $command"
  else
    command -v "$command" >/dev/null 2>&1 || fail "required executable missing: $command"
  fi
done
((failures == 0)) || exit 1

context="$(kctl config current-context 2>/dev/null || true)"
if [[ "$context" == "$EXPECTED_KUBE_CONTEXT" ]]; then
  pass "kubectl context is $context"
else
  fail "kubectl context is '$context', expected '$EXPECTED_KUBE_CONTEXT'"
fi

version_json="$(kctl version -o json 2>/dev/null || true)"
client_version="$(jq -r '.clientVersion.gitVersion // empty' <<<"$version_json")"
server_version="$(jq -r '.serverVersion.gitVersion // empty' <<<"$version_json")"
client_minor="$(sed -E 's/^v?[0-9]+\.([0-9]+).*/\1/' <<<"$client_version")"
server_minor="$(sed -E 's/^v?[0-9]+\.([0-9]+).*/\1/' <<<"$server_version")"
if [[ "$client_minor" =~ ^[0-9]+$ && "$server_minor" =~ ^[0-9]+$ ]] &&
   (( client_minor >= server_minor - 1 && client_minor <= server_minor + 1 )); then
  pass "kubectl $client_version is within one minor of API $server_version"
else
  fail "unsupported kubectl/API skew: client '$client_version', server '$server_version'"
fi

if kctl get --raw=/readyz >/dev/null 2>&1; then
  pass "Kubernetes API readyz"
else
  fail "Kubernetes API readyz failed"
fi

nodes_json="$(kctl get nodes -o json)"
not_ready="$(jq '[.items[] | select(([.status.conditions[]? | select(.type == "Ready") | .status] | first) != "True")] | length' <<<"$nodes_json")"
if [[ "$not_ready" == 0 ]]; then
  pass "all Kubernetes nodes Ready"
else
  fail "$not_ready Kubernetes node(s) are not Ready"
fi

unexpected_versions="$(jq --arg versions "$EXPECTED_VERSIONS" '[.items[] | select(.status.nodeInfo.kubeletVersion as $v | ($versions | split(",") | index($v) | not)) | {name:.metadata.name,version:.status.nodeInfo.kubeletVersion}]' <<<"$nodes_json")"
if [[ "$(jq 'length' <<<"$unexpected_versions")" == 0 ]]; then
  pass "all node versions are in [$EXPECTED_VERSIONS]"
else
  fail "unexpected node versions: $(jq -c . <<<"$unexpected_versions")"
fi

servers_json="$(kctl get nodes -l node-role.kubernetes.io/control-plane -o json)"
etcd_json="$(kctl get nodes -l node-role.kubernetes.io/etcd -o json)"
server_names="$(jq -r '.items[].metadata.name' <<<"$servers_json" | sort)"
etcd_names="$(jq -r '.items[].metadata.name' <<<"$etcd_json" | sort)"
if [[ "$(jq '.items | length' <<<"$servers_json")" == 3 && "$server_names" == "$etcd_names" ]]; then
  pass "three control-plane nodes are the three embedded-etcd members"
else
  fail "expected the same three control-plane and etcd nodes"
fi

if [[ "$MODE" == preflight || "$MODE" == final ]]; then
  cordoned="$(jq '[.items[] | select(.spec.unschedulable == true)] | length' <<<"$nodes_json")"
  if [[ "$cordoned" == 0 ]]; then
    pass "no node is left cordoned"
  else
    fail "$cordoned node(s) are unexpectedly cordoned"
  fi
fi

if [[ -n "$TARGET_NODE" ]]; then
  target_version="$(jq -r --arg n "$TARGET_NODE" '.items[] | select(.metadata.name == $n) | .status.nodeInfo.kubeletVersion' <<<"$nodes_json")"
  if [[ -n "$target_version" ]] && grep -Fqx "$target_version" < <(tr ',' '\n' <<<"$EXPECTED_VERSIONS"); then
    pass "$TARGET_NODE reports expected version $target_version"
  else
    fail "$TARGET_NODE has unexpected version '$target_version'"
  fi
fi

if kctl get crd applications.argoproj.io >/dev/null 2>&1; then
  apps_json="$(kctl -n argocd get applications.argoproj.io -o json)"
  bad_apps="$(jq '[.items[] | select(.status.sync.status != "Synced" or .status.health.status != "Healthy") | {name:.metadata.name,sync:.status.sync.status,health:.status.health.status}]' <<<"$apps_json")"
  if [[ "$(jq 'length' <<<"$bad_apps")" == 0 ]]; then
    pass "all Argo CD Applications Synced and Healthy"
  else
    fail "Argo CD Applications not green: $(jq -c . <<<"$bad_apps")"
  fi
  argocd_image="$(kctl -n argocd get statefulset argocd-application-controller -o json | jq -r '.spec.template.spec.containers[] | select(.name == "application-controller") | .image')"
  if [[ "$argocd_image" == quay.io/argoproj/argocd:v3.4.2 ]]; then
    pass "Argo CD v3.4.2 is in its official Kubernetes 1.35 test matrix"
  else
    fail "unexpected/unvalidated Argo CD controller image: $argocd_image"
  fi
else
  fail "Argo CD Application CRD missing"
fi

if kctl get namespace openclaw-qwen36 >/dev/null 2>&1; then
  openclaw_pods_json="$(kctl -n openclaw-qwen36 get pods -o json)"
  openclaw_terminating="$(jq '[.items[] | select(.metadata.deletionTimestamp != null)] | length' <<<"$openclaw_pods_json")"
  unsafe_openclaw_nodes="$(jq '[
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
  ]' <<<"$openclaw_pods_json")"
  if [[ "$openclaw_terminating" == 0 ]]; then
    pass "no OpenClaw pod is Terminating"
  else
    fail "$openclaw_terminating OpenClaw pod(s) are Terminating"
  fi
  if [[ "$(jq 'length' <<<"$unsafe_openclaw_nodes")" == 0 ]]; then
    pass "all active OpenClaw pods are on the four approved OVH nodes"
  else
    fail "active OpenClaw pod outside approved OVH nodes: $(jq -c . <<<"$unsafe_openclaw_nodes")"
  fi
else
  fail "OpenClaw namespace missing"
fi

if kctl get crd volumes.longhorn.io >/dev/null 2>&1; then
  longhorn_image="$(kctl -n longhorn-system get daemonset longhorn-manager -o json | jq -r '.spec.template.spec.containers[] | select(.name == "longhorn-manager") | .image')"
  if [[ "$longhorn_image" == docker.io/longhornio/longhorn-manager:v1.11.2 ]]; then
    pass "Longhorn 1.11.2 is in its official Kubernetes 1.35 test matrix"
  else
    fail "unexpected/unvalidated Longhorn manager image: $longhorn_image"
  fi
  volumes_json="$(kctl -n longhorn-system get volumes.longhorn.io -o json)"
  bad_volumes="$(jq '[.items[] | select(.status.robustness == "degraded" or .status.robustness == "faulted") | {name:.metadata.name,state:.status.state,robustness:.status.robustness}]' <<<"$volumes_json")"
  low_replica_volumes="$(jq '[.items[] | select((.spec.numberOfReplicas // 0) < 2) | {name:.metadata.name,replicas:.spec.numberOfReplicas}]' <<<"$volumes_json")"
  if [[ "$(jq 'length' <<<"$bad_volumes")" == 0 ]]; then
    pass "no Longhorn volume degraded or faulted"
  else
    fail "unhealthy Longhorn volumes: $(jq -c . <<<"$bad_volumes")"
  fi
  if [[ "$(jq 'length' <<<"$low_replica_volumes")" == 0 ]]; then
    pass "every Longhorn volume has at least two configured replicas"
  else
    fail "Longhorn volumes with fewer than two replicas: $(jq -c . <<<"$low_replica_volumes")"
  fi

  replicas_json="$(kctl -n longhorn-system get replicas.longhorn.io -o json)"
  rebuilding="$(jq '[.items[] | select((.status.currentState // "") == "rebuilding" or (.status.rebuildStatus // "") != "")] | length' <<<"$replicas_json")"
  if [[ "$rebuilding" == 0 ]]; then
    pass "no Longhorn replica rebuild in progress"
  else
    fail "$rebuilding Longhorn replica rebuild(s) in progress"
  fi

  drain_policy_json="$(kctl -n longhorn-system get settings.longhorn.io node-drain-policy -o json)"
  drain_policy="$(jq -r '.value // empty' <<<"$drain_policy_json")"
  drain_policy_applied="$(jq -r '.status.applied // false' <<<"$drain_policy_json")"
  if [[ "$drain_policy" == block-if-contains-last-replica && "$drain_policy_applied" == true ]]; then
    pass "Longhorn node-drain-policy protects the last healthy replica"
  else
    fail "unsafe/unapplied Longhorn node-drain-policy: value=$drain_policy applied=$drain_policy_applied"
  fi
else
  fail "Longhorn CRDs missing"
fi

pdb_json="$(kctl get poddisruptionbudgets.policy -A -o json)"
unhealthy_pdbs="$(jq '[.items[] | select((.status.currentHealthy // 0) < (.status.desiredHealthy // 0)) | {namespace:.metadata.namespace,name:.metadata.name,current:.status.currentHealthy,desired:.status.desiredHealthy}]' <<<"$pdb_json")"
if [[ "$(jq 'length' <<<"$unhealthy_pdbs")" == 0 ]]; then
  pass "all PDBs currently meet desired health"
else
  fail "PDBs below desired health: $(jq -c . <<<"$unhealthy_pdbs")"
fi
zero_disruption_pdbs="$(jq '[.items[] | select((.status.disruptionsAllowed // 0) == 0)] | length' <<<"$pdb_json")"
if [[ "$zero_disruption_pdbs" != 0 ]]; then
  warn "$zero_disruption_pdbs PDB(s) currently allow zero disruptions; the per-node server-side drain dry-run is authoritative and may block safely"
fi

if kctl get crd clusters.postgresql.cnpg.io >/dev/null 2>&1; then
  cnpg_deploy_json="$(kctl -n cnpg-system get deployment cnpg-cloudnative-pg -o json)"
  cnpg_image="$(jq -r '.spec.template.spec.containers[] | select(.name == "manager") | .image' <<<"$cnpg_deploy_json")"
  cnpg_ready="$(jq -r '.status.readyReplicas // 0' <<<"$cnpg_deploy_json")"
  cnpg_desired="$(jq -r '.spec.replicas // 0' <<<"$cnpg_deploy_json")"
  if grep -Fq 'v1.35.6+k3s1' <<<"$EXPECTED_VERSIONS"; then
    required_cnpg_version=1.30.0
  else
    required_cnpg_version=1.29.1
  fi
  required_cnpg_image="ghcr.io/cloudnative-pg/cloudnative-pg:$required_cnpg_version"
  if [[ "$cnpg_image" == "$required_cnpg_image" && "$cnpg_ready" == "$cnpg_desired" && "$cnpg_desired" -ge 2 ]]; then
    pass "CloudNativePG $required_cnpg_version operator is HA and supported for this stage"
  else
    fail "CloudNativePG prerequisite not met: image=$cnpg_image ready=$cnpg_ready/$cnpg_desired (require $required_cnpg_version and at least 2/2)"
  fi

  cnpg_clusters_json="$(kctl get clusters.postgresql.cnpg.io -A -o json)"
  bad_cnpg_clusters="$(jq '[.items[] | select((.status.readyInstances // 0) != (.spec.instances // 0) or .status.phase != "Cluster in healthy state" or ([.status.conditions[]? | select(.type == "ContinuousArchiving") | .status] | first) != "True") | {namespace:.metadata.namespace,name:.metadata.name,ready:.status.readyInstances,instances:.spec.instances,phase:.status.phase}]' <<<"$cnpg_clusters_json")"
  if [[ "$(jq 'length' <<<"$bad_cnpg_clusters")" == 0 && "$(jq '.items | length' <<<"$cnpg_clusters_json")" -gt 0 ]]; then
    pass "all CloudNativePG clusters ready, healthy, and continuously archiving"
  else
    fail "unhealthy CloudNativePG clusters: $(jq -c . <<<"$bad_cnpg_clusters")"
  fi

  cnpg_backups_json="$(kctl get backups.postgresql.cnpg.io -A -o json)"
  stale_cnpg_backups="$(jq --argjson clusters "$cnpg_clusters_json" '
    [$clusters.items[] as $cluster |
      select(([
        .items[] |
        select(.metadata.namespace == $cluster.metadata.namespace) |
        select(.spec.cluster.name == $cluster.metadata.name) |
        select(.status.phase == "completed") |
        select((.status.stoppedAt | fromdateiso8601) >= (now - 86400))
      ] | length) == 0) |
      {namespace:$cluster.metadata.namespace,name:$cluster.metadata.name}
    ]
  ' <<<"$cnpg_backups_json")"
  if [[ "$(jq 'length' <<<"$stale_cnpg_backups")" == 0 ]]; then
    pass "every CloudNativePG cluster has a completed backup from the last 24 hours"
  else
    fail "CloudNativePG clusters without fresh completed backup: $(jq -c . <<<"$stale_cnpg_backups")"
  fi
else
  fail "CloudNativePG CRDs missing"
fi

if [[ "$MODE" == preflight ]]; then
  snapshots_json="$(kctl get etcdsnapshotfiles.k3s.cattle.io -o json)"
  fresh_s3="$(jq '[.items[] | select((.spec.location // "") | startswith("s3://")) | select((.metadata.creationTimestamp | fromdateiso8601) >= (now - 43200))] | length' <<<"$snapshots_json")"
  if ((fresh_s3 > 0)); then
    pass "off-node S3 etcd snapshot exists from the last 12 hours"
  else
    fail "no off-node S3 etcd snapshot from the last 12 hours"
  fi
fi

if ((failures > 0)); then
  echo "K3s upgrade gate: FAIL ($failures check(s))" >&2
  exit 1
fi
echo "K3s upgrade gate: PASS ($MODE)"
