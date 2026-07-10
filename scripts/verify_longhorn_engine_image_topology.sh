#!/usr/bin/env bash
set -euo pipefail

namespace="${LONGHORN_NAMESPACE:-longhorn-system}"
exemption_annotation="upgrade-prep.pocharlies.org/longhorn-engineimage-exempt"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

for resource in \
  "engineimages.longhorn.io engineimages.json" \
  "nodes.longhorn.io longhorn-nodes.json" \
  "replicas.longhorn.io replicas.json"; do
  read -r kind output <<<"$resource"
  kubectl -n "$namespace" get "$kind" -o json >"$tmpdir/$output"
done

kubectl get nodes -o json >"$tmpdir/nodes.json"
kubectl get pods -A -o json >"$tmpdir/pods.json"
kubectl get pvc -A -o json >"$tmpdir/pvcs.json"
kubectl get pv -o json >"$tmpdir/pvs.json"

failures=0

while IFS=$'\t' read -r setting value applied; do
  printf 'setting=%s applied=%s value=%s\n' "$setting" "$applied" "$value"
  if [[ "$applied" != "true" ]]; then
    printf 'FAIL: Longhorn setting %s is not applied\n' "$setting" >&2
    failures=$((failures + 1))
  fi
done < <(
  kubectl -n "$namespace" get settings.longhorn.io \
    taint-toleration system-managed-components-node-selector \
    -o json | jq -r '.items[] | [.metadata.name, .value, (.status.applied | tostring)] | @tsv'
)

while IFS=$'\t' read -r image_name image_state node deployed; do
  printf 'engineimage=%s state=%s node=%s deployed=%s\n' \
    "$image_name" "$image_state" "$node" "$deployed"

  if [[ "$deployed" == "true" ]]; then
    continue
  fi

  annotation="$({
    jq -r --arg node "$node" --arg key "$exemption_annotation" \
      '.items[] | select(.metadata.name == $node) | .metadata.annotations[$key] // "false"' \
      "$tmpdir/nodes.json"
  } || true)"
  allow_scheduling="$({
    jq -r --arg node "$node" \
      '.items[] | select(.metadata.name == $node) | (.spec.allowScheduling | tostring)' \
      "$tmpdir/longhorn-nodes.json"
  } || true)"
  disk_count="$({
    jq -r --arg node "$node" \
      '[.items[] | select(.metadata.name == $node) | (.spec.disks // {} | to_entries[])] | length' \
      "$tmpdir/longhorn-nodes.json"
  } || true)"
  replica_count="$(
    jq -r --arg node "$node" \
      '[.items[] | select(.spec.nodeID == $node)] | length' \
      "$tmpdir/replicas.json"
  )"
  longhorn_pod_count="$(
    jq -n -r --arg node "$node" \
      --slurpfile pods "$tmpdir/pods.json" \
      --slurpfile pvcs "$tmpdir/pvcs.json" \
      --slurpfile pvs "$tmpdir/pvs.json" '
        [
          $pods[0].items[]
          | select(.spec.nodeName == $node)
          | . as $pod
          | (.spec.volumes // [])[]?
          | select(.persistentVolumeClaim != null)
          | .persistentVolumeClaim.claimName as $claim
          | $pvcs[0].items[]
          | select(
              .metadata.namespace == $pod.metadata.namespace
              and .metadata.name == $claim
              and .spec.volumeName != null
            )
          | .spec.volumeName as $pv_name
          | $pvs[0].items[]
          | select(
              .metadata.name == $pv_name
              and .spec.csi.driver == "driver.longhorn.io"
            )
          | [$pod.metadata.namespace, $pod.metadata.name]
        ]
        | unique
        | length
      '
  )"

  printf 'exception node=%s declared=%s allowScheduling=%s disks=%s replicas=%s longhornWorkloadPods=%s\n' \
    "$node" "$annotation" "${allow_scheduling:-missing}" "${disk_count:-missing}" \
    "$replica_count" "$longhorn_pod_count"

  if [[ "$annotation" == "true" \
    && "$allow_scheduling" == "false" \
    && "$disk_count" == "0" \
    && "$replica_count" == "0" \
    && "$longhorn_pod_count" == "0" ]]; then
    printf 'EXEMPT: %s satisfies the strict exclusion contract\n' "$node"
  else
    printf 'FAIL: %s is neither deployed nor safely exempt\n' "$node" >&2
    failures=$((failures + 1))
  fi
done < <(
  jq -r '
    .items[]
    | .metadata.name as $image
    | .status.state as $state
    | (.status.nodeDeploymentMap // {})
    | to_entries[]
    | [$image, $state, .key, (.value | tostring)]
    | @tsv
  ' "$tmpdir/engineimages.json"
)

if (( failures > 0 )); then
  printf 'RESULT=FAIL failures=%d\n' "$failures" >&2
  exit 1
fi

printf 'RESULT=PASS\n'
