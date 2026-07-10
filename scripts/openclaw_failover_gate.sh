#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
shift || true
STATE_FILE=""
TARGET_NODE=""
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
NAMESPACE="openclaw-qwen36"

while (($#)); do
  case "$1" in
    --state-file) STATE_FILE="$2"; shift 2 ;;
    --target-node) TARGET_NODE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$MODE" != pre && "$MODE" != post ]] ||
   [[ -z "$STATE_FILE" || -z "$TARGET_NODE" ]]; then
  echo "Usage: $0 {pre|post} --state-file FILE --target-node NODE" >&2
  exit 2
fi

kctl() { "$KUBECTL_BIN" "$@"; }
fail() { echo "OpenClaw failover gate: FAIL: $*" >&2; exit 1; }

pods_json="$(kctl -n "$NAMESPACE" get pods -o json)"
terminating="$(jq '[.items[] | select(.metadata.deletionTimestamp != null)] | length' <<<"$pods_json")"
[[ "$terminating" == 0 ]] || fail "$terminating OpenClaw pod(s) are still Terminating"

gateway_json="$(jq '[.items[] | select(.metadata.labels["app.kubernetes.io/component"] == "openclaw") | select(.metadata.deletionTimestamp == null) | select(.status.phase == "Running") | select(all(.status.containerStatuses[]?; .ready == true))]' <<<"$pods_json")"
[[ "$(jq 'length' <<<"$gateway_json")" == 1 ]] || fail "expected exactly one fully Ready gateway pod"
gateway_pod="$(jq -r '.[0].metadata.name' <<<"$gateway_json")"
gateway_node="$(jq -r '.[0].spec.nodeName' <<<"$gateway_json")"

node_pool="$(kctl get node "$gateway_node" -o jsonpath='{.metadata.labels.node-pool}')"
[[ "$gateway_node" != ubuntu && "$node_pool" == ks5-nvme ]] ||
  fail "gateway is on $gateway_node/$node_pool, expected a non-Ubuntu KS5 node"

deployments_json="$(kctl -n "$NAMESPACE" get deployments -o json)"
unavailable="$(jq '[.items[] | select((.status.availableReplicas // 0) != (.spec.replicas // 0)) | .metadata.name] | length' <<<"$deployments_json")"
[[ "$unavailable" == 0 ]] || fail "$unavailable OpenClaw deployment(s) are unavailable"

router_json="$(jq '[.items[] | select(.metadata.labels["app.kubernetes.io/component"] == "telegram-router") | select(.metadata.deletionTimestamp == null) | select(.status.phase == "Running") | select(all(.status.containerStatuses[]?; .ready == true))]' <<<"$pods_json")"
[[ "$(jq 'length' <<<"$router_json")" == 1 ]] ||
  fail "expected exactly one fully Ready Telegram router pod"
router_pod="$(jq -r '.[0].metadata.name' <<<"$router_json")"
router_status="$(kctl -n "$NAMESPACE" exec "$router_pod" -c telegram-router -- node -e 'fetch("http://127.0.0.1:8787/status").then(async r=>{if(!r.ok)process.exit(1);process.stdout.write(await r.text())})')"
jq -e '.paused == false and .deliveryAckEnabled == true and (.activeBackend | length > 0)' <<<"$router_status" >/dev/null ||
  fail "Telegram router is paused, lacks delivery ACK, or has no active backend"

if [[ "$MODE" == pre ]]; then
  mkdir -p "$(dirname "$STATE_FILE")"
  jq -n \
    --argjson started "$(date +%s)" \
    --arg gatewayPod "$gateway_pod" \
    --arg gatewayNode "$gateway_node" \
    --arg targetNode "$TARGET_NODE" \
    --argjson router "$router_status" \
    '{startedEpoch:$started,gatewayPod:$gatewayPod,gatewayNode:$gatewayNode,targetNode:$targetNode,failoverRequired:($gatewayNode == $targetNode),router:$router}' >"$STATE_FILE"
  chmod 0600 "$STATE_FILE"
  jq '{gatewayNode,gatewayPod,queueDepth:.router.queueDepth,deadCount:.router.deadCount}' "$STATE_FILE"
  exit 0
fi

[[ -f "$STATE_FILE" ]] || fail "pre-failover state file is missing"
source_node="$(jq -r '.gatewayNode' "$STATE_FILE")"
recorded_target_node="$(jq -r '.targetNode' "$STATE_FILE")"
[[ "$recorded_target_node" == "$TARGET_NODE" ]] ||
  fail "state file target $recorded_target_node does not match $TARGET_NODE"
failover_required="$(jq -r '.failoverRequired' "$STATE_FILE")"
if [[ "$failover_required" == true && "$gateway_node" == "$source_node" ]]; then
  fail "gateway has not failed over from drained node $source_node"
fi

ready_endpoints="$(kctl -n "$NAMESPACE" get endpointslices.discovery.k8s.io -l kubernetes.io/service-name=openclaw-qwen36-openclaw -o json | jq '[.items[].endpoints[]? | select(.conditions.ready == true and (.conditions.terminating // false) == false)] | length')"
((ready_endpoints >= 1)) || fail "gateway Service has no ready non-terminating endpoint"

kctl -n "$NAMESPACE" exec "$gateway_pod" -c openclaw -- node -e \
  'fetch("http://127.0.0.1:8080/readyz").then(async r=>{if(!r.ok)process.exit(1);const b=await r.json();if(b.ready!==true)process.exit(1)})'

pvc_names_json="$(kctl -n "$NAMESPACE" get pvc -o json | jq '[.items[].spec.volumeName | select(. != null and startswith("pvc-"))]')"
longhorn_json="$(kctl -n longhorn-system get volumes.longhorn.io -o json)"
bad_pvcs="$(jq --argjson names "$pvc_names_json" '[.items[] | select(.metadata.name as $n | $names | index($n)) | select(.status.robustness != "healthy" or .status.state != "attached" or .status.currentNodeID == "ubuntu") | {name:.metadata.name,state:.status.state,robustness:.status.robustness,node:.status.currentNodeID}]' <<<"$longhorn_json")"
[[ "$(jq 'length' <<<"$bad_pvcs")" == 0 ]] || fail "OpenClaw Longhorn attachment is unsafe: $(jq -c . <<<"$bad_pvcs")"

pre_dead="$(jq -r '.router.deadCount // 0' "$STATE_FILE")"
post_dead="$(jq -r '.deadCount // 0' <<<"$router_status")"
((post_dead <= pre_dead)) || fail "Telegram dead-letter count increased from $pre_dead to $post_dead"

finished="$(date +%s)"
started="$(jq -r '.startedEpoch' "$STATE_FILE")"
rto_seconds=$((finished - started))
result_file="${STATE_FILE%.json}.result.json"
jq -n \
  --argjson started "$started" \
  --argjson finished "$finished" \
  --argjson rtoSeconds "$rto_seconds" \
  --arg sourceNode "$source_node" \
  --arg targetNode "$TARGET_NODE" \
  --arg destinationNode "$gateway_node" \
  --arg gatewayPod "$gateway_pod" \
  --argjson failoverRequired "$failover_required" \
  --argjson router "$router_status" \
  '{startedEpoch:$started,finishedEpoch:$finished,rtoUpperBoundSeconds:$rtoSeconds,targetNode:$targetNode,failoverRequired:$failoverRequired,sourceNode:$sourceNode,destinationNode:$destinationNode,gatewayPod:$gatewayPod,router:$router}' >"$result_file"
chmod 0600 "$result_file"
jq '{rtoUpperBoundSeconds,targetNode,failoverRequired,sourceNode,destinationNode,gatewayPod,queueDepth:.router.queueDepth,deadCount:.router.deadCount,oldestQueuedAgeSeconds:.router.oldestQueuedAgeSeconds}' "$result_file"
