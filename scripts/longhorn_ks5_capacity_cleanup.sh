#!/usr/bin/env bash
set -euo pipefail

namespace="longhorn-system"
expected_context="${KUBE_CONTEXT:-default}"
mode="audit"

usage() {
  cat <<'EOF'
Usage: scripts/longhorn_ks5_capacity_cleanup.sh [--audit|--execute]

Audits a fixed allowlist of orphaned Longhorn volumes (restore-drill
leftovers). The default is read-only. Deletion additionally requires:

  CONFIRM_DELETE_KS5_SMOKE_VOLUMES=YES \
    scripts/longhorn_ks5_capacity_cleanup.sh --execute

The script fails closed if a volume is attached, has a PV/PVC reference, has
attachment tickets, is not a 2 GiB three-replica restore-drill volume, has a
backup reference, was restored from a backup that no longer exists, or has
replicas that are not stopped and spread one per node.
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

# These three volumes are leftovers of the 2026-08-18 restore drills in the
# opencode-restore-test namespaces. At audit time (INFRA-610, 2026-10-06) they
# had no PV or PVC, were detached, and retained three stopped 2 GiB replicas
# spread across ubuntu and the KS5 nodes. The earlier 2026-05-29/30 smoke-test
# allowlist is gone: those seven volumes no longer exist. pvc-436b923a-29c2-
# 4a3a-a405-226f303a9deb (rt-src) is deliberately NOT listed: it carries a
# backup reference (backup-7a489a86cc874b9d) and the backup guard aborts on
# it; it needs manual review, not this script.
volumes=(
  pvc-0bad5aa4-a4fc-48bd-9978-fd7c1b9761a3
  pvc-bafac363-85a0-405d-8032-8566193be5ef
  pvc-ec836794-82c9-4321-b4dc-e25808461204
)

expected_pvc_names='^rt-(restore-[ab]|src)$'
expected_namespaces='^opencode-restore-test(-r)?$'
two_gib=2147483648
six_gib=6442450944
max_drill_actual_bytes=1073741824

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
before_report="$(headroom_report)"
awk -F '\t' 'BEGIN { OFS="\t"; print "NODE","MAX_Gi","RESERVED_Gi","SCHEDULED_Gi","PHYSICAL_FREE_Gi","HEADROOM_Gi" }
  { for (i=2; i<=NF; i++) $i=sprintf("%.3f", $i/1073741824); print }' <<<"${before_report}"

for volume in "${volumes[@]}"; do
  volume_json="$(kubectl -n "${namespace}" get volumes.longhorn.io "${volume}" -o json)" ||
    fail "allowlisted volume ${volume} no longer exists"

  [[ "$(jq -r '.spec.size' <<<"${volume_json}")" == "${two_gib}" ]] ||
    fail "${volume}: size changed"
  [[ "$(jq -r '.spec.numberOfReplicas' <<<"${volume_json}")" == "3" ]] ||
    fail "${volume}: replica count changed"
  [[ "$(jq -r '.status.state' <<<"${volume_json}")" == "detached" ]] ||
    fail "${volume}: is not detached"
  [[ "$(jq -r '.status.kubernetesStatus.pvcName // ""' <<<"${volume_json}")" =~ ${expected_pvc_names} ]] ||
    fail "${volume}: unexpected historical PVC name"
  [[ "$(jq -r '.status.kubernetesStatus.namespace // ""' <<<"${volume_json}")" =~ ${expected_namespaces} ]] ||
    fail "${volume}: unexpected historical namespace"
  [[ "$(jq -r '.status.kubernetesStatus.pvStatus // ""' <<<"${volume_json}")" == "" ]] ||
    fail "${volume}: Longhorn still reports a PV state"
  [[ "$(jq -r '.spec.nodeSelector | join(",")' <<<"${volume_json}")" == "" ]] ||
    fail "${volume}: gained a node selector"
  [[ "$(jq -r '.spec.diskSelector | join(",")' <<<"${volume_json}")" == "" ]] ||
    fail "${volume}: gained a disk selector"
  from_backup="$(jq -r '.spec.fromBackup // ""' <<<"${volume_json}")"
  if [[ -n "${from_backup}" ]]; then
    # A restored drill volume is only safe to drop while the backup it came
    # from still exists, so its data stays recoverable.
    source_backup="$(sed -n 's/.*[?&]backup=\([^&]*\).*/\1/p' <<<"${from_backup}")"
    kubectl -n "${namespace}" get backups.longhorn.io "${source_backup}" >/dev/null 2>&1 ||
      fail "${volume}: restored from backup ${source_backup} which no longer exists"
  fi
  [[ "$(jq -r '.status.lastBackup // ""' <<<"${volume_json}")" == "" ]] ||
    fail "${volume}: has a backup reference and needs manual review"
  actual_size="$(jq -r '.status.actualSize // "0"' <<<"${volume_json}")"
  (( actual_size <= max_drill_actual_bytes )) ||
    fail "${volume}: actual data exceeds the 1 GiB drill ceiling"

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
  [[ "$(jq -r '[.items[].spec.volumeSize] | unique | .[]' <<<"${replicas_json}")" == "${two_gib}" ]] ||
    fail "${volume}: replica size changed"
  [[ "$(jq -r '[.items[].status.currentState] | unique | .[]' <<<"${replicas_json}")" == "stopped" ]] ||
    fail "${volume}: not all replicas are stopped"
  replica_node_count="$(jq -r '[.items[].spec.nodeID] | unique | length' <<<"${replicas_json}")"
  [[ "${replica_node_count}" == "3" ]] ||
    fail "${volume}: replicas are not spread across three distinct nodes"

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
before_report="${before_report:-}"
report="$(headroom_report)"
awk -F '\t' 'BEGIN { OFS="\t"; print "NODE","MAX_Gi","RESERVED_Gi","SCHEDULED_Gi","PHYSICAL_FREE_Gi","HEADROOM_Gi" }
  { for (i=2; i<=NF; i++) $i=sprintf("%.3f", $i/1073741824); print }' <<<"${report}"

while IFS=$'\t' read -r node _ _ _ _ headroom; do
  [[ "${node}" == "NODE" ]] && continue
  # KS5 headroom is negative at audit time because production replicas fill the
  # logical ceiling; the cleanup only has to recover the orphan budget, so the
  # postcondition is per-node no-regression, not an absolute floor.
  before="$(awk -F '\t' -v n="${node}" '$1==n {print $6}' <<<"${before_report}")"
  (( $(awk -v b="${before:-0}" -v h="${headroom}" 'BEGIN {print (h+1 >= b) ? 1 : 0}') )) ||
    fail "${node}: headroom regressed after cleanup (was ${before}, now ${headroom})"
done <<<"${report}"

echo "Cleanup complete: orphan budget recovered with no headroom regression."
