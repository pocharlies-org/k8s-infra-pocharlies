# Longhorn EngineImage topology maintenance

This runbook closes the pre-Kubernetes-upgrade gate for Longhorn system-managed
components. It does not authorize a Kubernetes drain, a K3s restart, or deletion
of Longhorn Replica, Engine, Volume, or EngineImage resources.

## Why a maintenance window is required

Longhorn applies `taint-toleration` and
`system-managed-components-node-selector` to system-managed components such as
CSI and engine-image pods. Longhorn 1.11.2 deliberately leaves these settings
unapplied while volumes remain attached. Do not work around that protection by
patching generated DaemonSets or removing deliberate GPU taints.

The intended topology is:

- every node labelled `storage-longhorn=true` receives CSI and engine-image
  pods, including attach-only nodes;
- replica scheduling remains independently disabled on attach-only Longhorn
  Node resources;
- production replica placement continues to use the `ks5-nvme`/`nvme` tags.

## Preflight

Record the current state before the window:

```bash
kubectl -n longhorn-system get settings.longhorn.io \
  taint-toleration system-managed-components-node-selector \
  -o custom-columns='NAME:.metadata.name,VALUE:.value,APPLIED:.status.applied'
kubectl -n longhorn-system get engineimages.longhorn.io -o yaml
kubectl -n longhorn-system get volumes.longhorn.io \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID'
```

Before changing workload replicas, create a fresh etcd checkpoint and verify
that the Longhorn backups required by the upgrade-preparation plan are Ready.
Quiesce stateful applications using each application's own procedure, then
scale their controllers down in a separately approved maintenance window.

Do not continue until both commands return zero:

```bash
kubectl -n longhorn-system get volumes.longhorn.io -o json \
  | jq '[.items[] | select(.status.state == "attached")] | length'
kubectl -n longhorn-system get volumes.longhorn.io -o json \
  | jq '[.items[] | select(.status.robustness != "healthy")] | length'
```

## Reconciliation

The desired values are already declared in `storage/longhorn/values.yaml`.
Once every volume is detached, wait for Longhorn to reconcile both settings;
do not patch generated DaemonSets:

```bash
kubectl -n longhorn-system get settings.longhorn.io \
  taint-toleration system-managed-components-node-selector -w
```

Both settings must report `status.applied=true`. Wait for all Longhorn
deployments and DaemonSets to become available, then run:

```bash
scripts/verify_longhorn_engine_image_topology.sh
```

The verifier permits an EngineImage exception only when a node has an explicit
`upgrade-prep.pocharlies.org/longhorn-engineimage-exempt=true` annotation,
Longhorn scheduling disabled, zero disks, zero Replica resources, and zero pods
using Longhorn volumes. Never add the annotation merely to make the gate pass.

## Restore service and rollback

Restore application controller replicas in dependency order and verify every
Longhorn volume is `healthy` before ending the window. If a system-managed pod
does not become ready, keep applications quiesced, collect Longhorn manager and
pod events, and revert only the declarative setting change that caused the
failure. Do not force-detach volumes and do not delete Longhorn custom
resources.

The gate is closed only when the verifier returns `RESULT=PASS` and all
application health checks have passed.
