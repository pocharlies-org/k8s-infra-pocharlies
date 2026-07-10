# OpenClaw secondary backup target on Sauvage MinIO

This is a transitional backup path that removes the OpenClaw gateway and
Telegram router's immediate dependency on the NFS backup target hosted by the
node named `ubuntu`. It is not an external disaster-recovery target: MinIO is a
single StatefulSet pod backed by `/srv/minio/data` on `sauvage`.

Longhorn 1.11 supports multiple `BackupTarget` resources. The existing
`BackupTarget/default` remains unchanged. The new `openclaw-sauvage` target
uses only `s3://longhorn-backups@us-east-1/openclaw/` and a dedicated MinIO
identity. Do not attach other volumes to this target.

## Security boundary

- Vault KV v2 is the source of truth at
  `secret/longhorn/openclaw-sauvage-backup`.
- `ExternalSecret/longhorn-openclaw-sauvage-backup` projects exactly
  `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and `AWS_ENDPOINTS` into
  `longhorn-system`.
- The MinIO policy in
  `storage/minio/longhorn-openclaw-sauvage-policy.json` can list only the
  `openclaw/` prefix and can read, create, or delete only objects below that
  prefix. It grants no admin, policy, user, or access to another bucket.
- Never use `minio-root` as the Longhorn credential and never put a credential
  value in Git, a shell argument, a log, an annotation, or a ConfigMap.
- Do not configure an object lifecycle/retention rule on this prefix. Longhorn
  owns the backup object lifecycle.

## Required maintenance gate

Stop if any condition is false:

1. `Application/openclaw-qwen36` is `Synced`, `Healthy`, and has no running
   operation.
2. The social gateway rollout and its PostSync smoke are complete; the router
   is resumed and reports no worker in flight.
3. No Kubernetes/K3s node upgrade, drain, or storage maintenance is active.
4. Both production volumes are `healthy`, have three replicas, and their
   replicas are on `ks5-cp-1`, `ks5-cp-2`, and `ks5-cp-3` only.
5. `BackupTarget/default` remains available. The procedure below never edits
   it.

## Credential and MinIO identity bootstrap

Generate a random secret in memory. Write the access key, secret key, and the
endpoint `http://minio-s3.minio.svc.cluster.local:9000` directly to Vault
without printing them. Apply/sync this GitOps resource and wait until the
`ExternalSecret` is `Ready=True`.

Create the MinIO user with the same dedicated credential and attach only the
policy in `storage/minio/longhorn-openclaw-sauvage-policy.json`. A safe
bootstrap may temporarily copy the already-projected Secret from
`longhorn-system` to `minio` without decoding it, mount both that copy and the
existing root Secret in a short-lived `minio/mc` pod, and then delete the pod
and copied Secret. No credential value may appear in the pod command, output,
or logs.

Validate the identity before creating the target:

- listing `longhorn-backups/openclaw/` succeeds;
- writing, reading, and deleting a random object in that prefix succeeds;
- listing another prefix and reading another bucket are denied.

The MinIO identity name and policy name are both
`longhorn-openclaw-sauvage`. Rotate by creating a new credential in Vault,
updating the MinIO user, forcing ESO refresh, and revalidating the four checks.

## Assign only the two OpenClaw volumes

Resolve the dynamic Longhorn volume names from the PVCs. Record the previous
target (`default`) for rollback. Use the Longhorn API action
`updateBackupTargetName` or patch `spec.backupTargetName` only on these two
Volume CRs:

- `openclaw-qwen36-openclaw-data-longhorn`
- `openclaw-qwen36-telegram-router-data-longhorn`

The desired target value is `openclaw-sauvage`. Verify all other Longhorn
volumes still report their previous target.

## Quiesced full-backup procedure

1. Record router `deadCount`. Wait until it is unpaused with `queueDepth=0`
   and `workerBusy=false`, then call its authenticated pause endpoint.
2. Scale the OpenClaw main Deployment to zero and wait for every regular and
   native-sidecar container to terminate normally. Never force-delete a pod.
3. Scale the router Deployment to zero. Telegram will receive temporary 503
   responses and retry; wait until the router pod exits normally.
4. Wait until both VolumeAttachments are gone. Abort and roll back if any pod,
   CRI sandbox, mount, or attachment remains; do not clean it with force.
5. Attach each original PVC read-only to a short-lived audit pod on a
   `node-pool=ks5-nvme` node. This starts the Longhorn engine without allowing
   an application writer.
6. Create a uniquely named Longhorn `Snapshot` for each volume and wait for
   `status.readyToUse=true`.
7. Create a uniquely named Longhorn `Backup` with `backupMode: full` for each
   snapshot. Wait for `status.state=Completed`, target
   `openclaw-sauvage`, and an S3 URL under the expected prefix.
8. Delete the read-only attachment pods normally and wait for detachment.

Do not resume production until both backups are completed and the restore
drill below passes.

## Disposable restore drill

For each completed backup, create a temporary Longhorn `Volume` with:

- `fromBackup` set to the backup URL;
- `backupTargetName: openclaw-sauvage`;
- `numberOfReplicas: 3`;
- `nodeSelector: [ks5-nvme]` and `diskSelector: [nvme]`;
- `dataLocality: disabled`, `replicaAutoBalance: best-effort`, and V1 engine.

Wait for `restoreRequired=false` and `robustness=healthy`. Bind each temporary
volume to a retained static PV/PVC and mount origin and restore read-only in an
audit pod running with the data owner's UID.

Acceptance evidence for both volumes:

- exact regular-file path, size, mode, UID/GID, and SHA-256 match;
- every SQLite database returns `PRAGMA quick_check = ok`;
- every router JSON file parses successfully;
- the restore has exactly three running replicas, one on each KS5 and none on
  `ubuntu`, `sauvage`, or a GPU node.

Delete the audit pod, temporary PVC, PV, and restored Volume CR in that order,
waiting for clean detachment. Keep the two completed backups.

## Resume and final checks

Scale main to one and wait for all containers Ready. Scale router to one, wait
for `/status`, then call the authenticated resume endpoint. Require:

- `paused=false`, `queueDepth=0`, `workerBusy=false`;
- `deadCount` did not increase during the maintenance;
- Workboard smoke passes;
- strict Codex Kubernetes smoke returns the exact expected marker;
- social gateway smoke passes;
- both production volumes remain healthy with three KS5 replicas;
- the default target and backups belonging to other workloads are unchanged.

## Rollback

If target creation or credential validation fails, delete only
`BackupTarget/openclaw-sauvage`, leave `default` untouched, remove the MinIO
user/policy, and remove the Vault path after ESO deletion is confirmed.

If a backup or restore drill fails, delete only the failed temporary backup,
snapshot, audit pod/PVC/PV, and restored Volume resources. Set the two
production Volume CRs back to their recorded target (`default`), scale main and
router to one, and resume the router after health checks. Never delete the
production PVCs, never change `BackupTarget/default`, and never force-delete a
pod or VolumeAttachment.

## Production limitation

This target removes `ubuntu` from the OpenClaw backup path, but it does not
provide site, host, or provider independence. Production DR still requires an
external object store, TLS/KMS-backed encryption, monitoring, and a repeated
restore drill against that external target.
