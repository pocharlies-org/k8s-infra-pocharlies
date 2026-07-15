# Velero 1.18 operability repair

> The 2026-07-10 repair below is historical. For the 2026-07-15 follow-up
> (emptyDir selection, daily Kopia maintenance and saturated-node scheduling),
> use `runbook-velero-fsb-maintenance-followup.md`. Its values and gates
> supersede the frequency, queue length and data-mover requests below.

This runbook repairs two independent production faults without scheduling the
Velero server or repository-maintenance jobs on `ubuntu`:

- filesystem backups are `PartiallyFailed` because `node-agent` runs only on
  `topology=lan`, while protected Pods and volumes run on the three KS5 nodes
  (`topology=ovh`);
- all 49 Kopia `BackupRepository` objects fail maintenance because the rendered
  maintenance resource configuration has an empty CPU limit. The values file
  also uses the unsupported key `defaultRepoMaintenanceFrequency`, so the
  intended weekly default never reaches Velero.

The repair keeps the Velero Deployment and every repository-maintenance job on
KS5 (`node-pool=ks5-nvme`). The node-agent DaemonSet covers the six reachable
LAN and OVH nodes because filesystem backup requires an agent on the source
Pod's node; the unreachable `topology=remote` Sauvage node remains excluded.

## Verified baseline and invariants

The live snapshot on 2026-07-10 was:

- release `velero` revision 6, chart 12.0.1, Velero 1.18.0;
- AWS plugin 1.13.0, although the plugin compatibility table maps Velero 1.18
  to AWS plugin 1.14.x;
- both `BackupStorageLocation/default` and `x86-backup-minio` `Available`;
- node-agent desired/ready 3, only on `gx10-ec3d`, `nvidia-dgx`, and `ubuntu`;
- the newest `daily-aiops`, `daily-critical`, and `daily-x86-critical` backups
  `PartiallyFailed`; their failed volume actions report that node-agent is not
  running on KS5;
- 49 repositories at `maintenanceFrequency=1h0m0s`, all with recent failed
  maintenance reporting an empty CPU limit; their last successful maintenance
  timestamps range from 2026-06-17 through 2026-06-21;
- three KS5 nodes with about 64 GiB allocatable memory each and no Velero
  ResourceQuota or LimitRange. Only one 512 Mi request / 2 GiB limit
  maintenance job is allowed at a time.

Use explicit Velero resource names in every command. In this cluster the short
name `backup` resolves to the Longhorn `Backup` CRD, not Velero.

Hard invariants throughout the change:

1. current context is `x86-k3s` and all Argo applications are Healthy/Synced
   with no operation running;
2. both BSLs remain `Available`;
3. the Velero Deployment and maintenance jobs run only on KS5;
4. node-agent runs on all and only the six reachable `lan`/`ovh` nodes;
5. at most one repository-maintenance job is active;
6. no credential name changes in this wave. In particular,
   `x86-backup-minio` keeps `cloud-credentials-backup-minio`;
7. do not merge or begin the MinIO credential cutover until both disposable
   PVC backup/restore smokes and the next scheduled backups complete cleanly.

## Wave 1: merge and sync the inert ConfigMap

The root kustomization manages only `ConfigMap/velero-node-agent-config` from
this repair. `platform/velero/values.yaml` is input to the standalone Helm
release and Argo does not apply it. Therefore a Git sync alone must not be
treated as the Helm rollout.

After merge and Argo sync, require:

```bash
set -Eeuo pipefail
test "$(kubectl config current-context)" = x86-k3s
kubectl -n argocd get applications.argoproj.io -o json | jq -e '
  [.items[] | select(
    .status.health.status != "Healthy" or
    .status.sync.status != "Synced" or
    (.status.operationState.phase == "Running")
  )] | length == 0
' >/dev/null

kubectl -n velero get configmap velero-node-agent-config -o json | jq -er '
  .data["node-agent-config.json"] | fromjson |
  .loadConcurrency == {globalConfig: 1, prepareQueueLength: 12} and
  .podResources == {
    cpuRequest: "100m", cpuLimit: "1000m",
    memoryRequest: "256Mi", memoryLimit: "1Gi"
  }
' >/dev/null
```

Stop if the ConfigMap is absent or malformed. It is inert until Helm adds the
node-agent argument.

## Wave 2: controlled Helm rollout

Run this wave in an approved change window. Do not start while a backup,
restore, repository-maintenance job, Argo operation, or storage incident is
active.

### Preflight and repository snapshot

```bash
set -Eeuo pipefail
set +x
umask 077
ulimit -c 0 >/dev/null 2>&1 || true

test "$(kubectl config current-context)" = x86-k3s
test "$(helm list -n velero -f '^velero$' -o json | jq -r '.[0].chart')" = \
  velero-12.0.1
test "$(helm list -n velero -f '^velero$' -o json | jq -r '.[0].app_version')" = \
  1.18.0
test "$(kubectl -n velero get deployment velero -o jsonpath='{.spec.replicas}')" = 1

kubectl -n argocd get applications.argoproj.io -o json | jq -e '
  [.items[] | select(
    .status.health.status != "Healthy" or
    .status.sync.status != "Synced" or
    (.status.operationState.phase == "Running")
  )] | length == 0
' >/dev/null
kubectl -n velero get backupstoragelocations.velero.io -o json | jq -e '
  (.items | length) == 2 and all(.items[]; .status.phase == "Available") and
  ([.items[] | select(.metadata.name == "default") |
    .spec.credential.name] == ["velero-minio-creds"]) and
  ([.items[] | select(.metadata.name == "x86-backup-minio") |
    .spec.credential.name] == ["cloud-credentials-backup-minio"])
' >/dev/null
test "$(kubectl -n velero get backups.velero.io -o json | jq '
  [.items[] | select(.status.phase == "InProgress" or
    .status.phase == "WaitingForPluginOperations" or
    .status.phase == "WaitingForPluginOperationsPartiallyFailed" or
    .status.phase == "Finalizing" or
    .status.phase == "FinalizingPartiallyFailed")] | length
')" = 0
test "$(kubectl -n velero get restores.velero.io -o json | jq '
  [.items[] | select(.status.phase == "InProgress" or
    .status.phase == "WaitingForPluginOperations" or
    .status.phase == "Finalizing")] | length
')" = 0
test "$(kubectl -n velero get jobs -l velero.io/repo-name -o json | jq '
  [.items[] | select((.status.active // 0) > 0)] | length
')" = 0

previous_revision="$(helm status velero -n velero -o json | jq -r '.version')"
repo_snapshot="$(mktemp "${TMPDIR:-/tmp}/velero-repositories.XXXXXX.json")"
chart="$(mktemp "${TMPDIR:-/tmp}/velero-12.0.1.XXXXXX.tgz")"
kubectl -n velero get backuprepositories.velero.io -o json | jq '
  [.items[] | {
    name: .metadata.name,
    maintenanceFrequency: .spec.maintenanceFrequency
  }]
' >"$repo_snapshot"
test "$(jq 'length' "$repo_snapshot")" = 49
```

The corrected default applies only when Velero creates a repository with an
empty/default frequency. Patch the 49 existing CRs explicitly before restarting
the controller:

```bash
jq -r '.[].name' "$repo_snapshot" | while IFS= read -r repo; do
  kubectl -n velero patch backuprepositories.velero.io "$repo" \
    --type=merge -p '{"spec":{"maintenanceFrequency":"168h0m0s"}}' >/dev/null
done
kubectl -n velero get backuprepositories.velero.io -o json | jq -e '
  (.items | length) == 49 and
  all(.items[]; .spec.maintenanceFrequency == "168h0m0s")
' >/dev/null
```

The Velero Deployment has one replica and the BackupRepository controller uses
the controller-runtime default of one concurrent reconcile. Its reconcile waits
for the maintenance job to finish. This serializes the overdue backlog; do not
increase Deployment replicas or controller concurrency during the drain.

### Exact values transform and upgrade

The transform below starts from the effective live user values, changes only
this repair's fields, and must hash-identically to the tracked values. It never
writes Helm values to disk.

```bash
velero_values_repaired() {
  helm get values velero -n velero -o json | jq '
    .initContainers |= map(
      if .name == "velero-plugin-for-aws" then
        .image = "docker.io/velero/velero-plugin-for-aws:v1.14.2@sha256:0751144c1c8e52d52c48717fbd13ad5a3061e612ae4d7ad744a946cd5b139d1a"
      else . end
    ) |
    del(.configuration.defaultRepoMaintenanceFrequency) |
    .configuration.defaultRepoMaintainFrequency = "168h0m0s" |
    .configuration.repositoryMaintenanceJob.repositoryConfigData.global = {
      keepLatestMaintenanceJobs: 3,
      podResources: {
        cpuRequest: "100m", cpuLimit: "1",
        memoryRequest: "512Mi", memoryLimit: "2Gi"
      },
      loadAffinity: [{
        nodeSelector: {matchExpressions: [{
          key: "node-pool", operator: "In", values: ["ks5-nvme"]
        }]}
      }]
    } |
    del(.nodeAgent.nodeSelector, .nodeAgent.privileged) |
    .nodeAgent.affinity = {
      nodeAffinity: {
        requiredDuringSchedulingIgnoredDuringExecution: {
          nodeSelectorTerms: [{matchExpressions: [{
            key: "topology", operator: "In", values: ["lan", "ovh"]
          }]}]
        }
      }
    } |
    .nodeAgent.extraArgs = ["--node-agent-configmap=velero-node-agent-config"] |
    .nodeAgent.resources.limits.cpu = "1"
  '
}

tracked_values_json() {
  python3 - <<'PY'
import json
import yaml
with open("platform/velero/values.yaml", encoding="utf-8") as stream:
    print(json.dumps(yaml.safe_load(stream), separators=(",", ":")))
PY
}

live_hash="$(velero_values_repaired | jq -Sc . | shasum -a 256 | awk '{print $1}')"
tracked_hash="$(tracked_values_json | jq -Sc . | shasum -a 256 | awk '{print $1}')"
test "$live_hash" = "$tracked_hash"
unset live_hash tracked_hash

curl -fsSL \
  https://github.com/vmware-tanzu/helm-charts/releases/download/velero-12.0.1/velero-12.0.1.tgz \
  -o "$chart"
test "$(shasum -a 256 "$chart" | awk '{print $1}')" = \
  d6281a4a722870881c2312ac4814b9d545839a1a74908c4a2aec3dc75483382e

velero_values_repaired | helm upgrade velero "$chart" -n velero \
  --dry-run=server --hide-secret -f - >/dev/null
velero_values_repaired | helm upgrade velero "$chart" -n velero \
  --atomic --cleanup-on-fail --wait --wait-for-jobs --timeout=30m -f -
```

### Immediate runtime gates

```bash
kubectl -n velero rollout status deployment/velero --timeout=10m
kubectl -n velero rollout status daemonset/node-agent --timeout=15m

kubectl -n velero get deployment velero -o json | jq -e '
  .spec.template.spec.nodeSelector == {"node-pool":"ks5-nvme"} and
  ([.spec.template.spec.initContainers[] |
    select(.name == "velero-plugin-for-aws") | .image] == [
      "docker.io/velero/velero-plugin-for-aws:v1.14.2@sha256:0751144c1c8e52d52c48717fbd13ad5a3061e612ae4d7ad744a946cd5b139d1a"
    ])
' >/dev/null

kubectl -n velero get daemonset node-agent -o json | jq -e '
  .status.desiredNumberScheduled == 6 and
  .status.numberReady == 6 and
  (.spec.template.spec.nodeSelector == null) and
  ([.spec.template.spec.containers[] | select(.name == "node-agent") |
    .args[]] | index("--node-agent-configmap=velero-node-agent-config") != null) and
  ([.spec.template.spec.affinity.nodeAffinity
    .requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms[]
    .matchExpressions[] | select(.key == "topology") | .values] ==
    [["lan","ovh"]])
' >/dev/null
test "$(kubectl -n velero get pods -l name=node-agent -o json | jq '
  [.items[].spec.nodeName] | unique | length
')" = 6
test "$(kubectl -n velero get pods -l name=node-agent \
  --field-selector spec.nodeName=sauvage -o json | jq '.items | length')" = 0

kubectl -n velero get configmap velero-repo-maintenance -o json | jq -er '
  .data.global | fromjson |
  .keepLatestMaintenanceJobs == 3 and
  .podResources == {
    cpuRequest: "100m", cpuLimit: "1",
    memoryRequest: "512Mi", memoryLimit: "2Gi"
  } and
  (.loadAffinity | length) == 1 and
  .loadAffinity[0].nodeSelector.matchExpressions == [{
    key: "node-pool", operator: "In", values: ["ks5-nvme"]
  }]
' >/dev/null
kubectl -n velero get backupstoragelocations.velero.io -o json | jq -e '
  (.items | length) == 2 and all(.items[]; .status.phase == "Available")
' >/dev/null
```

As soon as the first maintenance job appears, prove its placement and limits.
Velero 1.18 consumes only the first `loadAffinity` entry; it does not inherit
the Deployment nodeSelector.

```bash
while :; do
  jobs="$(kubectl -n velero get jobs -l velero.io/repo-name -o json)"
  active="$(jq '[.items[] | select((.status.active // 0) > 0)] | length' <<<"$jobs")"
  test "$active" -le 1
  if test "$(jq '.items | length' <<<"$jobs")" -gt 0; then
    jq -e '
      all(.items[];
        (.spec.template.spec.affinity.nodeAffinity
          .requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms[0]
          .matchExpressions | any(
            .key == "node-pool" and .operator == "In" and
            .values == ["ks5-nvme"]
          )) and
        .spec.template.spec.containers[0].resources == {
          requests: {cpu:"100m",memory:"512Mi"},
          limits: {cpu:"1",memory:"2Gi"}
        }
      )
    ' <<<"$jobs" >/dev/null
    break
  fi
  sleep 10
done
unset jobs active
```

## Wave 3: sequential PVC backup/restore smokes

Do not use a ConfigMap-only smoke: it cannot prove that node-agent and Kopia
work on KS5. For each BSL, create a disposable namespace with a Longhorn PVC
and a Pod explicitly placed on KS5, write a unique marker, create a Velero
`Backup` with filesystem backup enabled and snapshots disabled, delete the
namespace, restore it, and compare the marker.

Run the locations sequentially (`default`, then `x86-backup-minio`) so they do
not contend with backlog maintenance. Require:

- `backups.velero.io/<name>` phase `Completed` with zero errors;
- exactly one matching `podvolumebackups.velero.io` phase `Completed`, whose
  `.spec.node` has `node-pool=ks5-nvme`;
- `restores.velero.io/<name>` phase `Completed` with zero errors;
- restored Pod Ready and marker content identical;
- the selected BSL remains `Available` and active maintenance jobs never exceed
  one.

Retain each smoke backup for its 24-hour TTL or remove it through a
`DeleteBackupRequest`; never delete only the Backup CR because that can orphan
object-store data. Delete the disposable namespace and Restore CR after the
comparison.

## Backlog drain and completion gates

The controller drains 49 overdue repositories serially. Keep the three latest
maintenance jobs per repository during this incident so logs remain available.
Monitor, but never delete an in-flight job merely to speed up the wave:

```bash
while sleep 15; do
  kubectl -n velero get jobs -l velero.io/repo-name -o json | jq '
    {active: ([.items[] | select((.status.active // 0) > 0)] | length),
     succeeded: ([.items[] | select((.status.succeeded // 0) > 0)] | length),
     failed: ([.items[] | select((.status.failed // 0) > 0)] | length)}
  '
done
```

The wave is complete only when all 49 repositories have a new
`lastMaintenanceTime`, their latest maintenance result is `Succeeded`, no job
failed/OOMKilled, both PVC smokes pass, and the next executions of
`daily-aiops`, `daily-critical`, and `daily-x86-critical` are `Completed` with
zero errors. Until then, the MinIO credential cutover remains blocked.

## Rollback

If an immediate runtime gate fails, stop creating new work and wait for the
single active maintenance job to finish. Do not delete it. Then roll back Helm
and restore the exact BackupRepository frequencies captured before the wave:

```bash
helm rollback velero "$previous_revision" -n velero \
  --wait --wait-for-jobs --timeout=30m
kubectl -n velero rollout status deployment/velero --timeout=10m
kubectl -n velero rollout status daemonset/node-agent --timeout=15m

jq -c '.[]' "$repo_snapshot" | while IFS= read -r row; do
  repo="$(jq -r '.name' <<<"$row")"
  frequency="$(jq -r '.maintenanceFrequency' <<<"$row")"
  kubectl -n velero patch backuprepositories.velero.io "$repo" \
    --type=merge -p "$(jq -nc --arg value "$frequency" \
      '{spec:{maintenanceFrequency:$value}}')" >/dev/null
done
kubectl -n velero get backupstoragelocations.velero.io -o json | jq -e '
  (.items | length) == 2 and all(.items[]; .status.phase == "Available")
' >/dev/null
```

The GitOps node-agent ConfigMap is inert under the previous DaemonSet and may
remain until the Git revert is reviewed and synced. A Helm rollback restores
plugin 1.13.0, LAN-only node-agent placement, and the prior broken maintenance
values, so rollback restores availability but does not solve the audit finding.
Keep the incident open and reschedule a corrected rollout.

On success, remove only the local non-secret snapshot and chart:

```bash
rm -f "$repo_snapshot" "$chart"
unset repo_snapshot chart previous_revision
```

## Official implementation references

- AWS plugin compatibility for Velero 1.18:
  https://github.com/vmware-tanzu/velero-plugin-for-aws/blob/v1.14.2/README.md
- chart 12.0.1 repository-maintenance schema:
  https://github.com/vmware-tanzu/helm-charts/blob/velero-12.0.1/charts/velero/values.yaml#L519-L586
- Velero 1.18 node-agent configuration:
  https://velero.io/docs/v1.18/supported-configmaps/node-agent-configmap/
- maintenance job construction, first-affinity behavior, and resource parsing:
  https://github.com/velero-io/velero/blob/v1.18.0/pkg/repository/maintenance/maintenance.go#L531-L679
- BackupRepository controller setup and blocking maintenance reconcile:
  https://github.com/velero-io/velero/blob/v1.18.0/pkg/controller/backup_repository_controller.go#L53-L136
  and
  https://github.com/velero-io/velero/blob/v1.18.0/pkg/controller/backup_repository_controller.go#L493-L557
- controller-runtime's default single concurrent reconcile:
  https://github.com/kubernetes-sigs/controller-runtime/blob/v0.21.0/pkg/controller/controller.go#L215-L217
