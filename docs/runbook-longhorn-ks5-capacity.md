# KS5 Longhorn capacity recovery

## Why OpenClaw restore fails

Longhorn 1.11.2 evaluates replica capacity with:

```text
size + storageScheduled
  <= (storageMaximum - storageReserved) * storageOverProvisioningPercentage / 100
```

The three KS5 disks each have 877.541 GiB maximum, 263.262 GiB reserved
(30%), and 613.500 GiB scheduled. With over-provisioning fixed at 100%, only
0.779 GiB remains schedulable. This is why both the 5 GiB OpenClaw restore and
even the 1 GiB router restore fail although hundreds of GiB remain physically
free.

Do not reduce `storageReserved` or `storageMinimalAvailablePercentage`, and do
not increase logical over-provisioning as the first response. Seven obsolete
KS5 smoke-test volumes have no PV/PVC, are detached, and retain one 1 GiB
replica allocation on every KS5 node. Removing only those test volumes restores
7 GiB per node. A three-replica 5 GiB + 1 GiB OpenClaw pair then fits with
approximately 1.779 GiB remaining logical headroom per node.

## Procedure

1. Audit only (default):

   ```bash
   scripts/longhorn_ks5_capacity_cleanup.sh --audit
   ```

2. Review every `SAFE-CANDIDATE` line. The script aborts if any candidate has
   regained a PV, an attachment ticket, a running replica, a backup reference,
   or a changed placement/size.

3. Execute the reviewed cleanup:

   ```bash
   CONFIRM_DELETE_KS5_SMOKE_VOLUMES=YES \
     scripts/longhorn_ks5_capacity_cleanup.sh --execute
   ```

4. Recreate the two disposable restore-validation volumes. Require three
   replicas, exactly one on each of `ks5-cp-1`, `ks5-cp-2`, and `ks5-cp-3`.
   Delete the disposable restores after data validation before moving the live
   OpenClaw replicas.

5. Keep `storage-over-provisioning-percentage=100`. For both OpenClaw volumes,
   set `spec.replicaSoftAntiAffinity=disabled` and
   `spec.replicaDiskSoftAntiAffinity=disabled` during the controlled placement
   change, and require one replica per KS5 node before proceeding. Do not flip
   these settings globally in the capacity-recovery wave: the cluster contains
   existing bound volumes with co-located replicas and global auto-balance is
   `best-effort`, so that change needs its own rebuild-capacity review.

## Postconditions

```bash
kubectl -n longhorn-system get settings.longhorn.io \
  storage-over-provisioning-percentage \
  -o custom-columns=NAME:.metadata.name,VALUE:.value,APPLIED:.status.applied

kubectl -n longhorn-system get volumes.longhorn.io \
  pvc-13b814ca-2c90-4baf-b30d-7d66330cfdf2 \
  pvc-4013eddd-d2ff-4c23-a5c6-95d22cdcb4a8 \
  -o custom-columns=VOLUME:.metadata.name,NODE_ANTI_AFFINITY:.spec.replicaSoftAntiAffinity,DISK_ANTI_AFFINITY:.spec.replicaDiskSoftAntiAffinity

kubectl -n longhorn-system get nodes.longhorn.io -o json | jq -r '
  .items[] | select(.metadata.name | test("^ks5-cp-[123]$")) |
  .metadata.name as $node | .spec.disks as $spec |
  .status.diskStatus | to_entries[] | .key as $disk | .value as $status |
  [$node,
   (($status.storageMaximum - $spec[$disk].storageReserved - $status.storageScheduled) / 1073741824),
   ($status.storageAvailable / 1073741824)] | @tsv'
```

The first numeric column must be at least 6 GiB before creating the validation
pair. Physical available space must remain greater than 15% of disk maximum.
