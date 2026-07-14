# Velero FSB selection and Kopia maintenance follow-up

This is the forward-only follow-up to the 2026-07-10 Velero 1.18 repair. It
does not change credentials, BackupStorageLocations, retention, protected
namespaces, or backup data. It narrows filesystem backup to durable volumes,
keeps existing PVC coverage, and makes Kopia maintenance frequent enough for
the observed repository churn.

## Proven 2026-07-14 failure

`daily-x86-critical-20260714023005` backed up all 3,461 Kubernetes items but
finished `PartiallyFailed` after four hours:

- 82 PodVolumeBackups were created;
- 72 targeted `emptyDir` scratch/cache volumes and only 10 targeted PVCs;
- all 10 PVC backups completed;
- all six cancelled PVBs were MetalLB `emptyDir` volumes;
- five helper Pods on `gx10-ec3d` could not reserve 256 MiB and one helper on
  `ks5-cp-2` could not reserve 100m CPU;
- the `metallb-system-x86-backup-minio-kopia` repository emitted
  `Found too many index blobs (1481)`.

All 61 BackupRepository objects were still configured for maintenance every
168 hours. The most recent successful maintenance wave was 2026-07-10; 12 new
repositories had no completed maintenance yet. The fault is therefore a
selection and maintenance-frequency problem, not failed durable PVC data.

## Invariants

1. Keep `defaultVolumesToFsBackup: true`: mounted PVCs remain opt-out and do
   not depend on every workload carrying an annotation.
2. The resource policy skips only `emptyDir`. It must not match PVC, CSI or
   NFS volumes.
3. Data-mover concurrency stays at one per node. Lower requests are scheduler
   reservations, not limits; the existing 1 CPU / 1 GiB limits remain.
4. Repository maintenance stays serialized and on `node-pool=ks5-nvme`.
5. The frequency migration patches only the old exact value `168h0m0s`.
   Custom repository frequencies fail closed and are reported, not overwritten.
6. Do not start this wave while a backup, restore, maintenance Job, Argo
   operation, or storage incident is active.

## Coordinated GitOps order

Two repositories intentionally share one policy without duplicate Argo
ownership:

1. Merge and sync `k8s-infra-pocharlies` first. It owns
   `ConfigMap/velero-fsb-volume-policy`, the primary schedules, node-agent
   ConfigMap and a suspended, manually triggered repository-frequency migrator.
2. Require the policy ConfigMap and all three primary schedules to be Synced.
3. Merge and sync `dgx-infra` second. Its `backup-hub` application adopts the
   previously orphaned `daily-x86-critical` Schedule and references the shared
   policy.

Do not sync `dgx-infra` first: a scheduled backup with a missing referenced
policy is a validation failure.

## Preflight

```bash
set -Eeuo pipefail
test "$(kubectl config current-context)" = x86-k3s

test "$(kubectl -n velero get backups.velero.io -o json | jq '[.items[] |
  (.status.phase // "") as $phase |
  select((["Completed", "PartiallyFailed", "Failed", "FailedValidation"] |
    index($phase)) == null)] | length')" = 0
test "$(kubectl -n velero get restores.velero.io -o json | jq '[.items[] |
  (.status.phase // "") as $phase |
  select((["Completed", "PartiallyFailed", "Failed", "FailedValidation"] |
    index($phase)) == null)] | length')" = 0
test "$(kubectl -n velero get jobs -l velero.io/repo-name -o json | jq
  '[.items[] | select((.status.active // 0) > 0)] | length')" = 0

kubectl -n velero get backupstoragelocations.velero.io -o json | jq -e '
  (.items | length) == 2 and all(.items[]; .status.phase == "Available")
' >/dev/null

repo_snapshot="$(mktemp "${TMPDIR:-/tmp}/velero-repositories.XXXXXX.json")"
kubectl -n velero get backuprepositories.velero.io -o json | jq '
  [.items[] | {name: .metadata.name,
               maintenanceFrequency: .spec.maintenanceFrequency}]
' >"$repo_snapshot"
test "$(jq length "$repo_snapshot")" -gt 0
```

## Argo-managed gates

After the `k8s-infra` sync:

```bash
kubectl -n velero get configmap velero-fsb-volume-policy -o json | jq -er '
  .data["policies.yaml"]
' | grep -F -- '- emptyDir'

for schedule in daily-critical daily-aiops weekly-all; do
  kubectl -n velero get schedule "$schedule" -o json | jq -e '
    .spec.template.defaultVolumesToFsBackup == true and
    .spec.template.resourcePolicy == {
      kind: "ConfigMap", name: "velero-fsb-volume-policy"
    }
  ' >/dev/null
done

kubectl -n velero get configmap velero-node-agent-config -o json | jq -er '
  .data["node-agent-config.json"] | fromjson |
  .loadConcurrency == {globalConfig: 1, prepareQueueLength: 6} and
  .podResources == {
    cpuRequest: "10m", cpuLimit: "1000m",
    memoryRequest: "128Mi", memoryLimit: "1Gi"
  }
' >/dev/null

kubectl -n velero get cronjob velero-repository-frequency-24h-v1 -o json |
  jq -e '.spec.suspend == true and .spec.concurrencyPolicy == "Forbid"' >/dev/null
```

After the `dgx-infra` sync:

```bash
kubectl -n velero get schedule daily-x86-critical -o json | jq -e '
  .metadata.annotations["argocd.argoproj.io/tracking-id"] != null and
  .spec.template.defaultVolumesToFsBackup == true and
  .spec.template.resourcePolicy == {
    kind: "ConfigMap", name: "velero-fsb-volume-policy"
  }
' >/dev/null
```

## Standalone Helm rollout

`platform/velero/values.yaml` is input to the standalone Helm release; the
`k8s-infra` Argo application does not apply it. In the same approved window,
upgrade chart `velero-12.0.1` with the tracked values and existing secret, then
restart node-agent because it reads its ConfigMap only at startup:

```bash
previous_revision="$(helm status velero -n velero -o json | jq -r .version)"
chart="$(mktemp "${TMPDIR:-/tmp}/velero-12.0.1.XXXXXX.tgz")"
curl -fsSL \
  https://github.com/vmware-tanzu/helm-charts/releases/download/velero-12.0.1/velero-12.0.1.tgz \
  -o "$chart"
test "$(shasum -a 256 "$chart" | awk '{print $1}')" = \
  d6281a4a722870881c2312ac4814b9d545839a1a74908c4a2aec3dc75483382e
helm upgrade velero "$chart" -n velero \
  --reuse-values -f platform/velero/values.yaml \
  --atomic --cleanup-on-fail --wait --wait-for-jobs --timeout=30m
kubectl -n velero rollout restart daemonset/node-agent
kubectl -n velero rollout status daemonset/node-agent --timeout=15m
kubectl -n velero rollout status deployment/velero --timeout=10m
```

Require the rendered server argument to be `24h0m0s`, the maintenance
ConfigMap to keep one Job, and all six LAN/OVH node agents Ready. No node-agent
may run on a `topology=remote` node.

Only after those gates pass, start the guarded one-shot migration from the
suspended CronJob template. A Git merge or Argo sync cannot start it:

```bash
migration_job="velero-repository-frequency-$(date -u +%Y%m%d%H%M%S)"
kubectl -n velero create job "$migration_job" \
  --from=cronjob/velero-repository-frequency-24h-v1
kubectl -n velero wait --for=condition=complete "job/$migration_job" --timeout=10m
kubectl -n velero logs "job/$migration_job"
kubectl -n velero get backuprepositories.velero.io -o json | jq -e '
  all(.items[]; .spec.maintenanceFrequency != "168h0m0s")
' >/dev/null
```

The migrator rechecks backups, restores and maintenance Jobs plus both BSLs
immediately before its first patch. Backup and Restore phases use a terminal
allowlist; an active, unknown or missing phase fails closed. It changes only
the exact old value; any custom frequency is logged and left untouched.

Changing existing repositories from seven days to one day makes overdue
maintenance immediately eligible. Let Velero drain it serially; do not delete
or parallelize maintenance Jobs. Completion requires every latest maintenance
result to be `Succeeded` and no active Job.

## Functional proof

Run the existing disposable Longhorn PVC backup/restore smoke sequentially
against `default` and `x86-backup-minio`. For each location require Backup and
Restore phase `Completed`, zero errors, exactly one completed PVB, and an
unchanged marker checksum after restore. Both BSLs must remain `Available`.

Then create one on-demand backup from `daily-x86-critical` and require that its
PVB set contains PVC volumes only, with no `emptyDir`, no cancellation, and no
`too many index blobs` warning. Do not claim the incident closed before this
post-maintenance proof.

## Rollback

Revert both GitOps PRs in reverse order. Roll back Helm, restart node-agent,
and restore exact per-repository frequencies from the preflight snapshot:

```bash
helm rollback velero "$previous_revision" -n velero --wait --timeout=30m
kubectl -n velero rollout restart daemonset/node-agent
jq -c '.[]' "$repo_snapshot" | while IFS= read -r row; do
  name="$(jq -r .name <<<"$row")"
  frequency="$(jq -r .maintenanceFrequency <<<"$row")"
  kubectl -n velero patch backuprepositories.velero.io "$name" --type=merge \
    -p "$(jq -nc --arg value "$frequency" \
      '{spec:{maintenanceFrequency:$value}}')" >/dev/null
done
```

Never delete BackupRepository objects or Kopia blobs as rollback.

## Official references

- Velero 1.18 resource-policy ordering and `emptyDir` volume matching:
  https://velero.io/docs/v1.18/resource-filtering/
- Velero 1.18 opt-out FSB and per-Pod exclusions:
  https://velero.io/docs/v1.18/file-system-backup/
- Velero 1.18 node-agent concurrency and Pod resources:
  https://velero.io/docs/v1.18/supported-configmaps/node-agent-configmap/
- Velero 1.18 repository-maintenance resources and placement:
  https://velero.io/docs/v1.18/repository-maintenance/
