#!/usr/bin/env bash
set -euo pipefail

namespace="longhorn-system"
expected_context="${KUBE_CONTEXT:-x86-k3s}"
mode="audit"

usage() {
  cat <<'EOF'
Usage: scripts/longhorn_ks5_capacity_cleanup.sh [--audit|--execute]

Audits a fixed allowlist of obsolete KS5 smoke-test Longhorn volumes. The
default is read-only. Deletion additionally requires:

  CONFIRM_DELETE_KS5_SMOKE_VOLUMES=YES \
    scripts/longhorn_ks5_capacity_cleanup.sh --execute

The script fails closed if a volume is attached, has a PV/PVC reference, has
attachment tickets, is not a 1 GiB three-replica KS5/NVMe test volume, or its
replicas are not stopped and spread one per KS5 node.
EOF
}

case "${1:---audit}" in
  --audit) mode="audit" ;;
  --execute) mode="execute" ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

for binary in kubectl jq; do
  command -v "${binary}" >/dev/null || {
    echo "ERROR: missing required command: ${binary}" >&2
    exit 1
  }
done

current_context="$(kubectl config current-context)"
if [[ "${current_context}" != "${expected_context}" ]]; then
  echo "ERROR: expected kube context ${expected_context}, got ${current_context}" >&2
  exit 1
fi

# These seven volumes were created by the 2026-05-29/30 KS5 smoke tests. At
# audit time they had no PV or PVC, were detached, and allocated exactly one
# stopped 1 GiB replica on each KS5 node. Removing them recovers 7 GiB of
# scheduling budget per node while preserving the 30% disk reservation.
volumes=(
  pvc-c9a7bb40-6738-4c71-bb68-22230cf166f6
  pvc-0ddd37a5-16fd-4b2f-b718-e1b72be8888c
  pvc-e9bac87d-780b-4818-a9cc-871ede392c6c
  pvc-0fcf0aa5-d40f-4b96-8510-3576f3fb0a24
  pvc-6297dbad-b210-43ec-ab3b-6a9c095f8d75
  pvc-bd30267d-c521-479e-bb18-2c495f22f900
  pvc-9d40eb4b-1eaf-484e-ae66-1b3d30f71526
)

expected_pvc_names='^(ks5-nvme-smoketest|ks5-nvme-smoketest2|ks5-nvme-smoke3|ks5-nvme-smoke4|ks5-nvme-smoke5|ks5diag|nvme-test-claim)$'
expected_nodes=$'ks5-cp-1\nks5-cp-2\nks5-cp-3'
one_gib=1073741824
six_gib=6442450944
max_test_actual_bytes=67108864

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

headroom_report() {
  kubectl -n "${namespace}" get nodes.longhorn.io -o json | jq -r '
    .items[] | select(.metadata.name | test("^ks5-cp-[123]$")) |
    .metadata.name as $node |
    .spec.disks as $spec |
    .status.diskStatus | to_entries[] |
    .key as $disk |
    .value as $status |
    ($status.storageMaximum - $spec[$disk].storageReserved - $status.storageScheduled) as $headroom |
    [$node, $status.storageMaximum, $spec[$disk].storageReserved,
     $status.storageScheduled, $status.storageAvailable, $headroom] | @tsv'
}

echo "KS5 capacity before ${mode}:"
headroom_report | awk -F '\t' 'BEGIN { OFS="\t"; print "NODE","MAX_Gi","RESERVED_Gi","SCHEDULED_Gi","PHYSICAL_FREE_Gi","HEADROOM_Gi" }
  { for (i=2; i<=NF; i++) $i=sprintf("%.3f", $i/1073741824); print }'

for volume in "${volumes[@]}"; do
  volume_json="$(kubectl -n "${namespace}" get volumes.longhorn.io "${volume}" -o json)" ||
    fail "allowlisted volume ${volume} no longer exists"

  [[ "$(jq -r '.spec.size' <<<"${volume_json}")" == "${one_gib}" ]] ||
    fail "${volume}: size changed"
  [[ "$(jq -r '.spec.numberOfReplicas' <<<"${volume_json}")" == "3" ]] ||
    fail "${volume}: replica count changed"
  [[ "$(jq -r '.status.state' <<<"${volume_json}")" == "detached" ]] ||
    fail "${volume}: is not detached"
  [[ "$(jq -r '.status.kubernetesStatus.pvcName // ""' <<<"${volume_json}")" =~ ${expected_pvc_names} ]] ||
    fail "${volume}: unexpected historical PVC name"
  [[ "$(jq -r '.status.kubernetesStatus.pvStatus // ""' <<<"${volume_json}")" == "" ]] ||
    fail "${volume}: Longhorn still reports a PV state"
  [[ "$(jq -r '.spec.nodeSelector | join(",")' <<<"${volume_json}")" == "ks5-nvme" ]] ||
    fail "${volume}: node selector changed"
  [[ "$(jq -r '.spec.diskSelector | join(",")' <<<"${volume_json}")" == "nvme" ]] ||
    fail "${volume}: disk selector changed"
  [[ "$(jq -r '.spec.fromBackup // ""' <<<"${volume_json}")" == "" ]] ||
    fail "${volume}: was created from a backup"
  [[ "$(jq -r '.status.lastBackup // ""' <<<"${volume_json}")" == "" ]] ||
    fail "${volume}: has a backup reference and needs manual review"
  actual_size="$(jq -r '.status.actualSize // "0"' <<<"${volume_json}")"
  (( actual_size <= max_test_actual_bytes )) ||
    fail "${volume}: actual data exceeds the 64 MiB smoke-test ceiling"

  pv_count="$(kubectl get pv -o json | jq --arg volume "${volume}" \
    '[.items[] | select((.spec.csi.volumeHandle // "") == $volume)] | length')"
  [[ "${pv_count}" == "0" ]] || fail "${volume}: a Kubernetes PV still references it"

  ticket_count="$(kubectl -n "${namespace}" get volumeattachments.longhorn.io "${volume}" -o json | \
    jq '.spec.attachmentTickets | length')"
  [[ "${ticket_count}" == "0" ]] || fail "${volume}: has Longhorn attachment tickets"

  replicas_json="$(kubectl -n "${namespace}" get replicas.longhorn.io \
    -l "longhornvolume=${volume}" -o json)"
  [[ "$(jq '.items | length' <<<"${replicas_json}")" == "3" ]] ||
    fail "${volume}: expected exactly three replicas"
  [[ "$(jq -r '[.items[].spec.volumeSize] | unique | .[]' <<<"${replicas_json}")" == "${one_gib}" ]] ||
    fail "${volume}: replica size changed"
  [[ "$(jq -r '[.items[].status.currentState] | unique | .[]' <<<"${replicas_json}")" == "stopped" ]] ||
    fail "${volume}: not all replicas are stopped"
  replica_nodes="$(jq -r '.items[].spec.nodeID' <<<"${replicas_json}" | sort -u)"
  [[ "${replica_nodes}" == "${expected_nodes}" ]] ||
    fail "${volume}: replicas are not spread exactly across the KS5 trio"

  echo "SAFE-CANDIDATE ${volume}"
done

if [[ "${mode}" == "audit" ]]; then
  echo "Audit passed. No resources were changed."
  exit 0
fi

[[ "${CONFIRM_DELETE_KS5_SMOKE_VOLUMES:-}" == "YES" ]] ||
  fail "set CONFIRM_DELETE_KS5_SMOKE_VOLUMES=YES for --execute"

kubectl -n "${namespace}" delete volumes.longhorn.io "${volumes[@]}" --wait=false

deadline=$((SECONDS + 300))
for volume in "${volumes[@]}"; do
  until ! kubectl -n "${namespace}" get volumes.longhorn.io "${volume}" >/dev/null 2>&1; do
    (( SECONDS < deadline )) || fail "timed out waiting for ${volume} deletion"
    sleep 2
  done
done

echo "KS5 capacity after cleanup:"
report="$(headroom_report)"
awk -F '\t' 'BEGIN { OFS="\t"; print "NODE","MAX_Gi","RESERVED_Gi","SCHEDULED_Gi","PHYSICAL_FREE_Gi","HEADROOM_Gi" }
  { for (i=2; i<=NF; i++) $i=sprintf("%.3f", $i/1073741824); print }' <<<"${report}"

while IFS=$'\t' read -r node _ _ _ _ headroom; do
  (( headroom >= six_gib )) || fail "${node}: less than 6 GiB scheduling headroom after cleanup"
done <<<"${report}"

echo "Cleanup complete: each KS5 node has at least 6 GiB logical headroom."
