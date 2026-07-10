# MinIO root credential P0 runbook

This runbook removes the main MinIO root identity from Harbor, Velero, and
Loki before rotating the singleton server root credential. It does not touch
`backup-hub/backup-minio` or K3s etcd snapshot credentials.

## Recovery evidence and hard gates

The OpenClaw restore drill completed on 2026-07-10. Full main and router
backups were restored to disposable Longhorn volumes, compared file by file,
validated with SQLite/JSON checks, and observed healthy with three replicas on
the three KS5 nodes. The retained backups are:

- `backup-sauvage-main-20260710t053337z`
- `backup-sauvage-router-20260710t053337z`

Do not start a migration while an Argo operation, BuildKit rollout, K3s wave,
storage maintenance, or unrelated incident is active. Require current backup
inventory, MinIO readiness, Harbor health, both Velero locations `Available`,
Loki readiness/query, and current CNPG backup status. Record Helm revisions
without exporting values containing credentials.

## Wave 1: create identities without changing consumers

1. Generate four independent high-entropy access/secret pairs in memory:
   break-glass, Harbor, Velero, and Loki.
2. Write them through an approved authenticated Vault session to these paths:
   `secret/minio/breakglass-admin`, `secret/minio/harbor-s3`,
   `secret/minio/velero-s3`, and `secret/minio/loki-s3`. Each path uses keys
   `access_key` and `secret_key`. Never put a value on a command line, in a
   manifest, or in a shell trace.
3. With an explicitly approved change window, run:

   ```bash
   MINIO_CHANGE_WINDOW_APPROVED=yes \
     scripts/minio/provision-workload-identities.sh --execute
   ```

   The script projects the four Vault paths only into a transient Secret in
   the MinIO namespace, creates the break-glass `consoleAdmin` user and three
   bucket-scoped users, and removes the transient Pod, Secret, ExternalSecret,
   and policy ConfigMap on every exit path. It intentionally suppresses command
   output that could contain access-key identifiers.
4. Validate each workload user can list/read/write/delete only its bucket. For
   Harbor and Velero also validate multipart upload/abort. Verify another
   bucket and bucket-root enumeration are denied. Do not weaken a policy to
   make a negative test pass.

## Wave 2: migrate one consumer at a time

Keep the old root valid throughout this wave so every consumer can be rolled
back independently.

### Harbor

1. Merge/sync the infra identity manifest and wait for
   `ExternalSecret/harbor-s3-credentials Ready=True`.
2. Upgrade release `harbor` 1.19.0 with `platform/harbor/values.yaml` and wait
   for all Harbor workloads. The registry and registryctl containers must both
   reference `harbor-s3-credentials`.
3. Push, pull, and delete a disposable artifact. Confirm registry health and
   no S3 `AccessDenied` around a dry-run garbage-collection job.
4. Rollback: `helm rollback harbor <previous-revision> --wait`. The old root
   remains valid and the old `harbor-registry` Secret is not deleted yet.

### Velero

1. Wait for `ExternalSecret/velero-s3-credentials Ready=True`.
2. Upgrade release `velero` 12.0.1 with `platform/velero/values.yaml` and wait
   for the Deployment. Confirm only `BackupStorageLocation/default` references
   the new Secret; `x86-backup-minio` must retain its own credential.
3. Create a disposable namespace and ConfigMap, back it up explicitly to
   `default`, delete it, restore it, and compare its data. Require backup and
   restore `Completed` plus `default=Available`.
4. Rollback: `helm rollback velero <previous-revision> --wait`, then require
   both BackupStorageLocations `Available`.

### Loki

1. Merge/sync the observability PR only after Harbor and Velero pass. Wait for
   `ExternalSecret/loki-s3-credentials Ready=True` and StatefulSet rollout.
2. Verify the generated ConfigMap contains only
   `${LOKI_S3_ACCESS_KEY}`/`${LOKI_S3_SECRET_KEY}`, the container has
   `-config.expand-env=true`, and its environment comes from the ESO Secret.
   Loki chart 7.0.0 wires these through `singleBinary.extraArgs` and
   `singleBinary.extraEnvFrom`; its SingleBinary template does not consume the
   equivalent `global` fields.
3. Ingest a unique marker and retrieve it through a range query. Require
   readiness, ruler/compactor health, and no object-store authorization errors.
4. Rollback the observability revision. The old ConfigMap values remain usable
   until this consumer has passed and the root cutover begins.

Run `scripts/minio/verify-workload-cutover.sh` after all three migrations. It
compares credentials only in memory, checks runtime references and health, and
prints a single pass marker.

## Wave 3: root-v2 projection and singleton cutover

Do not prepare or merge the cutover until all three consumers pass Wave 2.

1. Generate a root-v2 user/password pair unrelated to every workload user and
   store it at `secret/minio/root-v2`.
2. PR A adds only `ExternalSecret/minio-root-v2`. Merge/sync and require
   `Ready=True` and exactly keys `root-user`, `root-password`.
3. Prove by in-memory comparison that Harbor, Velero, Loki, CNPG, Keycloak,
   Langfuse, Synapse, and Longhorn do not use the old root. Scan current Git,
   rendered Helm output, ConfigMaps, pod specs, and non-server Secrets.
4. Announce a maintenance window. Quiesce writes and record the pre-cutover
   StatefulSet revision and health. The raw singleton reads root environment
   only at process start, so this step causes an intentional MinIO outage.
5. PR B removes the literal `Secret/minio-root`, points the StatefulSet and
   bucket bootstrap jobs to `minio-root-v2`, and changes an explicit rollout
   stamp. Let the old Pod terminate normally; never force-delete it.
6. Require MinIO readiness, bucket inventory, every workload test above,
   OpenClaw backup-target availability, current CNPG backups, and a fresh
   disposable Velero backup/restore.
7. Through a no-output authentication probe, prove root-v2 succeeds and the
   old root pair receives an authentication failure. Only then delete the old
   Kubernetes Secret and revoke the previous Vault version according to the
   retention policy.

Rollback before old-root revocation is a Git revert to the previous Secret
reference followed by one normal singleton restart. After revocation, use the
Vault-held break-glass admin and an approved prior Vault version; never restore
a literal into Git.

## Completion criteria

- No application uses MinIO root.
- Current Git, Helm renders, ConfigMaps, non-server Secrets, and pod specs have
  zero occurrences of the revoked pair.
- Root-v2 works; old root is rejected.
- Harbor push/pull/delete, Velero backup/restore, Loki ingest/query/retention,
  CNPG backups, and the OpenClaw backup target all pass.
- `backup-hub/backup-minio` and K3s etcd remain unchanged; their separate debt
  is handled in a later coordinated wave.

References:

- MinIO user management: https://min.io/docs/minio/linux/administration/identity-access-management/minio-user-management.html
- Harbor/Distribution S3 permissions: https://distribution.github.io/distribution/storage-drivers/s3/
- Velero AWS plugin permissions: https://github.com/velero-io/velero-plugin-for-aws/blob/main/README.md
- Loki storage permissions: https://grafana.com/docs/loki/latest/operations/storage/
