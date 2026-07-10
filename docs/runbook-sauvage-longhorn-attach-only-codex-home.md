# Runbook: Sauvage attach-only + encrypted CODEX_HOME

Status: production rollout runbook. Tested against Longhorn chart/app version
`1.11.2` on 2026-07-10.

## Execution checkpoint — 2026-07-10 04:47 Europe/Madrid

- PR #21 and PR #23 are merged into `deploy/prod`; Argo `k8s-infra` is
  `Synced/Healthy` and owns all three safety Setting CRs.
- The manual Helm release was upgraded successfully from revision 3 to revision
  4 using the pinned 1.11.2 chart and this repository's values. The 110%
  bounded repair headroom and replica rebuild limit 1 were preserved.
- All 53 attached Longhorn volumes remained healthy; there were no degraded
  volumes, running unhealthy replicas, or engine replicas in write-only rebuild
  mode after the upgrade.
- `create-default-disk-labeled-nodes=true` is `APPLIED=true`.
- `system-managed-components-node-selector` and `taint-toleration` contain the
  correct desired values but remain `APPLIED=false`. Longhorn manager logs
  confirm that it refuses these updates while volumes are attached.
- The impact inventory contains 55 active Longhorn pod/PVC mounts across 19
  namespaces, including PostgreSQL, Vault, Harbor, RabbitMQ, monitoring and
  OpenClaw. Detaching every volume is therefore a cluster-wide storage outage,
  not an OpenClaw-only restart.
- The mandatory gate remains closed: Sauvage has **not** received
  `storage-longhorn=true`, has no Longhorn Node resource, and has zero replicas.
  The encrypted attach smoke on Sauvage is intentionally deferred.

Do not bypass this checkpoint by patching Setting status, editing generated
DaemonSets, removing the edge taint, or weakening the playbook assertion. The
supported completion path is an approved maintenance window that cleanly
detaches every Longhorn volume, waits for both settings to become
`APPLIED=true`, restores workloads, and only then runs Phase 3 and Phase 4.

## Target invariant

- `sauvage` can run Longhorn manager, CSI plugin, engine image and instance
  manager processes required to attach an RWO volume.
- `sauvage` never stores a Longhorn replica: `Node.spec.allowScheduling=false`,
  no schedulable Longhorn disk, and zero `Replica` resources with
  `spec.nodeID=sauvage`.
- `CODEX_HOME` uses `longhorn-openclaw-encrypted`: three replicas, all on
  Longhorn node tag `ks5-nvme` and disk tag `nvme`, with LUKS encryption.
- The passphrase is not in Git. The OpenClaw chart materializes a per-PVC
  Secret once from Vault in the PVC namespace. Its name equals the PVC name,
  as required by the StorageClass `${pvc.name}` templates.

Longhorn distinguishes user-deployed components from system-managed
components and requires node selection/tolerations for both. Its storage tags
control replica placement independently from the Kubernetes node that attaches
the volume:

- <https://longhorn.io/docs/1.11.2/advanced-resources/deploy/node-selector/>
- <https://longhorn.io/docs/1.11.2/nodes-and-volumes/nodes/storage-tags/>
- <https://longhorn.io/docs/1.11.2/advanced-resources/security/volume-encryption/>

## Verified starting state (2026-07-10)

- Helm release `longhorn` is `longhorn-1.11.2`, app version `v1.11.2`.
- `storage/longhorn/values.yaml` is **not** consumed by the current Argo
  `k8s-infra` Application. The live Helm release only records the four CSI
  replica-count overrides, so this values file must be applied explicitly or
  Longhorn must first be migrated to an Argo-managed Helm source.
- The minimum controlled transition keeps the chart at Helm release revision 4
  while Argo owns the three safety-critical Setting CRs through
  `storage/longhorn/attach-only-settings.yaml`. This prevents desired-state
  drift without attempting to adopt the existing Helm release in-place.
- `sauvage` is Ready, `amd64`, Ubuntu 24.04, tainted
  `role=edge:NoSchedule`, and does not yet have `storage-longhorn=true` or a
  Longhorn `Node` resource.
- On Sauvage, `open-iscsi`, `nfs-common`, `cryptsetup` and `dmsetup` are
  installed; `iscsid` is active/enabled; `iscsi_tcp` and `dm_crypt` are loaded;
  NFSv4 is supported; `multipathd` is inactive and masked; root is ext4.
- Live `create-default-disk-labeled-nodes=false`. **Do not label Sauvage for
  Longhorn in this state**: Longhorn creates a default disk on every newly
  discovered node when that setting is false.
- Live `system-managed-components-node-selector=storage-longhorn:true` reports
  `status.applied=false`; updates to system-managed selectors/tolerations can
  require component restarts and detached volumes.
- `ClusterSecretStore/vault-backend` is Ready. Its current policy can read but
  a temporary `PushSecret` write to the OpenClaw crypto path returned 403; seed
  the Vault value with an approved Vault-admin workflow, not PushSecret.

The prerequisite list matches Longhorn 1.11.2 documentation:
<https://longhorn.io/docs/1.11.2/deploy/install/>.

## Phase 0 — backup and change window

1. Confirm all Longhorn volumes are healthy and no rebuild is running.
2. Take and verify a backup of the OpenClaw volumes.
3. Record the release and settings without secret data:

   ```bash
   helm -n longhorn-system list
   helm -n longhorn-system get values longhorn -o yaml
   kubectl -n longhorn-system get volumes.longhorn.io
   kubectl -n longhorn-system get settings.longhorn.io \
     create-default-disk-labeled-nodes \
     system-managed-components-node-selector taint-toleration -o yaml
   ```

4. Pause provisioning, restore drills and replica rebuilds during the chart
   reconciliation. Longhorn warns that selector changes restart components and
   may not fully apply while volumes remain attached.

## Phase 1 — seed and verify the encryption key

Create one high-entropy `CRYPTO_KEY_VALUE` and the static provider property at
the Vault reference consumed by the OpenClaw chart:

```text
ClusterSecretStore: vault-backend
remoteRef.key: openclaw-qwen36/codex-crypto
properties: CRYPTO_KEY_VALUE, CRYPTO_KEY_PROVIDER=secret
```

Requirements:

- use the approved Vault-admin path; never paste the value into Git, a ticket,
  terminal history or chat;
- retain the key with the encrypted volume backups;
- do not overwrite it in place. A changed passphrase can make the existing
  LUKS volume unmountable;
- back up the Vault/etcd material needed for disaster recovery.

After OpenClaw GitOps applies its per-volume ExternalSecret, validate names
only:

```bash
kubectl -n openclaw-qwen36 wait --for=condition=Ready \
  externalsecret/openclaw-qwen36-codex-crypto --timeout=2m
kubectl -n openclaw-qwen36 get secret \
  openclaw-qwen36-codex-state-longhorn -o json \
  | jq -e '.data | has("CRYPTO_KEY_VALUE") and \
    has("CRYPTO_KEY_PROVIDER")' >/dev/null
```

`refreshPolicy: CreatedOnce` intentionally prevents a Vault edit from silently
changing the mounted key. Rotation is a data migration: create a new key and
StorageClass, copy data, prove restore, then retire the old volume/key.

Important: Longhorn encryption protects volume replicas and backups, but the
unlock key is materialized as a Kubernetes Secret. Production completion also
requires K3s/Kubernetes Secret encryption at rest; otherwise the key remains
readable from an etcd snapshot by an etcd administrator.

## Phase 2 — render and apply Longhorn 1.11.2 values

Render the exact pinned chart and inspect the diff:

```bash
helm template longhorn longhorn \
  --repo https://charts.longhorn.io \
  --version 1.11.2 \
  --namespace longhorn-system \
  --values storage/longhorn/values.yaml >/tmp/longhorn-1.11.2.yaml

helm upgrade longhorn longhorn \
  --repo https://charts.longhorn.io \
  --version 1.11.2 \
  --namespace longhorn-system \
  --reuse-values \
  --values storage/longhorn/values.yaml \
  --dry-run=server
```

Apply only inside the approved window:

```bash
helm upgrade longhorn longhorn \
  --repo https://charts.longhorn.io \
  --version 1.11.2 \
  --namespace longhorn-system \
  --reuse-values \
  --values storage/longhorn/values.yaml \
  --wait --timeout 20m
```

Do not continue until all three settings have the expected value and
`status.applied=true`:

```bash
kubectl -n longhorn-system get settings.longhorn.io \
  create-default-disk-labeled-nodes \
  system-managed-components-node-selector taint-toleration \
  -o custom-columns='NAME:.metadata.name,VALUE:.value,APPLIED:.status.applied'
```

Expected:

- `create-default-disk-labeled-nodes=true`
- `system-managed-components-node-selector=storage-longhorn:true`
- `taint-toleration` contains `role=edge:NoSchedule`

If `APPLIED=false`, do not label Sauvage. Follow the Longhorn selector-change
procedure, which may require detaching remaining volumes, and wait for all
components to become Ready.

The Setting CRs are GitOps-managed, but Longhorn deliberately leaves
`status.applied=false` while any volume is attached. Argo `Synced` is therefore
not equivalent to the operational gate: the playbook requires Longhorn's own
`status.applied=true` before it labels Sauvage.

## Phase 3 — admit Sauvage as attach-only

Run the gated playbook. It installs prerequisites idempotently, refuses unsafe
Longhorn settings, removes any default-disk opt-in, labels the Kubernetes node,
forces Longhorn node/disk scheduling off, waits for the required pods, and
asserts that zero replicas exist on Sauvage.

```bash
CONFIRM_SAUVAGE_LONGHORN_ATTACH_ONLY=enable-sauvage-attach-only \
  ansible-playbook -i ansible/inventory/generated/ks5.ini \
  ansible/playbooks/enable-sauvage-longhorn-attach-only.yml
```

Independent verification:

```bash
kubectl get node sauvage -L storage-longhorn,workload.openclaw
kubectl -n longhorn-system get nodes.longhorn.io sauvage -o json \
  | jq -e '.spec.allowScheduling == false and \
    ([.spec.disks[]? | select(.allowScheduling == true)] | length == 0)'
kubectl -n longhorn-system get replicas.longhorn.io \
  -l longhornnode=sauvage --no-headers
kubectl -n longhorn-system get pods --field-selector spec.nodeName=sauvage \
  -l app=longhorn-manager
kubectl -n longhorn-system get pods --field-selector spec.nodeName=sauvage \
  -l app=longhorn-csi-plugin
kubectl -n longhorn-system get pods --field-selector spec.nodeName=sauvage \
  -l longhorn.io/component=engine-image
kubectl -n longhorn-system get pods --field-selector spec.nodeName=sauvage \
  -l longhorn.io/component=instance-manager
```

The replica command must return no rows. Manager, CSI, engine-image and instance
manager pods must be Ready.

## Phase 4 — encrypted attach smoke test

After the canonical StorageClass is Ready, create a disposable namespace, an
ExternalSecret whose target name equals the disposable PVC, and a 1 GiB PVC
with `storageClassName: longhorn-openclaw-encrypted`. Mount it in a disposable
pod explicitly scheduled to Sauvage with the `role=edge` toleration. Write
data, restart the pod, and verify the checksum.

For the resulting PV/Longhorn volume, prove:

```bash
PV="$(kubectl -n <smoke-namespace> get pvc <smoke-pvc> -o jsonpath='{.spec.volumeName}')"
kubectl -n longhorn-system get volumes.longhorn.io "$PV" -o json \
  | jq -e '.spec.encrypted == true and .spec.numberOfReplicas == 3 \
    and .spec.nodeSelector == ["ks5-nvme"] \
    and .spec.diskSelector == ["nvme"]'
kubectl -n longhorn-system get replicas.longhorn.io \
  -l "longhornvolume=$PV" -o json \
  | jq -e '[.items[].spec.nodeID] | sort \
    == ["ks5-cp-1","ks5-cp-2","ks5-cp-3"]'
```

Delete the smoke pod/PVC only after the checksum and placement pass. Because the
StorageClass uses `Retain`, explicitly delete the disposable retained PV and
Longhorn volume after confirming it is the smoke volume.

Only then create/migrate the real `CODEX_HOME` PVC. StorageClass is immutable
for an existing PVC, so migration requires a new PVC and verified data copy or
backup/restore; editing the old claim does not encrypt it.

## Rollback

1. Stop/relocate any workload using a Longhorn PVC on Sauvage and wait for the
   volume to detach.
2. Remove only the admission label:

   ```bash
   kubectl label node sauvage storage-longhorn-
   ```

3. Keep `nodes.longhorn.io/sauvage.spec.allowScheduling=false` and verify zero
   replicas before deleting the Longhorn node resource.
4. If the Helm change destabilized system components, use the recorded release
   revision with `helm rollback`, then verify all volumes before resuming work.
5. Never delete the crypto Secret or Vault key while encrypted volumes or their
   backups exist.

## Production acceptance

- Longhorn release and all system/user components Ready.
- `sauvage`: attach works, node and disks unschedulable, zero replicas.
- Three healthy CODEX_HOME replicas exactly on KS5-1/2/3.
- Encrypted smoke write/remount/checksum succeeds on Sauvage.
- Backup and restore drill of the encrypted PVC succeeds with the retained key.
- Kubernetes Secret encryption at rest is enabled and verified.
- Monitoring alerts on a replica appearing on Sauvage, missing CSI/manager on
  Sauvage, encrypted volume degradation, and ExternalSecret not Ready.
