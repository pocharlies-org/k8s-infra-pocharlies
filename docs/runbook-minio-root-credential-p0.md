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
   `ExternalSecret/harbor-s3-credentials Ready=True`. The `k8s-infra`
   Application reconciles the ExternalSecret, but it does not manage the
   standalone Helm release. Merging the PR alone must not be treated as the
   consumer cutover.
2. Before changing Helm, require a current Harbor administrator credential
   from the approved secret manager. Do not assume that the initial
   `HARBOR_ADMIN_PASSWORD` retained in the Helm Secret still matches Harbor's
   database after an administrator has changed the password. Prove the
   credential can authenticate and delete artifacts before the upgrade, or
   stop here.
3. Perform a credential-only upgrade of release `harbor` 1.19.0. Stream the
   current user values through an in-memory transformer that removes the S3
   `accesskey`/`secretkey` fields and adds only `existingSecret`; pipe the
   sanitized result directly to `helm upgrade --atomic -f -`. Do not write the
   values to disk and do not use `--reuse-values`, because that would retain
   the retired values in Helm release state. This prevents the existing,
   unrelated Harbor node-selector drift from being bundled into the security
   cutover. Reconcile that placement in a separate change.

   Use this exact cutover sequence from the repository root. It pins the chart
   payload, performs a server-side dry run, and never materializes Helm values:

   ```bash
   set -Eeuo pipefail
   set +x
   umask 077
   ulimit -c 0 >/dev/null 2>&1 || true

   printf 'Current Harbor admin password: ' >/dev/tty
   IFS= read -r -s harbor_admin_password </dev/tty
   printf '\n' >/dev/tty
   test -n "$harbor_admin_password"
   harbor_auth="$(printf 'admin:%s' "$harbor_admin_password" | \
     base64 | tr -d '\n')"
   harbor_api_code() {
     printf 'header = "Authorization: Basic %s"\n' "$harbor_auth" | \
       curl --config - --silent --show-error --output /dev/null \
         --write-out '%{http_code}' "$@"
   }
   test "$(harbor_api_code --request GET --url \
     https://harbor.e-dani.com/api/v2.0/users/current)" = 200

   test "$(kubectl config current-context)" = x86-k3s
   kubectl -n argocd get applications.argoproj.io -o json | jq -e '
     [.items[] | select(
       .status.health.status != "Healthy" or
       .status.sync.status != "Synced" or
       (.status.operationState.phase == "Running")
     )] | length == 0
   ' >/dev/null
   kubectl -n harbor wait --for=condition=Ready \
     externalsecret/harbor-s3-credentials --timeout=2m
   test "$(kubectl -n harbor get secret harbor-s3-credentials -o json | \
     jq -r '.data | keys | sort | join(",")')" = \
     'REGISTRY_STORAGE_S3_ACCESSKEY,REGISTRY_STORAGE_S3_SECRETKEY'
   kubectl -n minio wait --for=condition=Ready pod/minio-0 --timeout=30s
   kubectl get --raw \
     '/api/v1/namespaces/harbor/services/http:harbor:80/proxy/api/v2.0/health' | \
     jq -e '.status == "healthy" and ([.components[].status] | all(. == "healthy"))' \
     >/dev/null

   previous_revision="$(helm status harbor -n harbor -o json | jq -r '.version')"
   test "$(helm list -n harbor -f '^harbor$' -o json | jq -r '.[0].chart')" = \
     harbor-1.19.0

   chart="$(mktemp "${TMPDIR:-/tmp}/harbor-1.19.0.tgz.XXXXXX")"
   cutover_active=false
   cutover_cleanup() {
     code=$?
     trap - EXIT
     set +e
     if [ "$code" -ne 0 ] && [ "${cutover_active:-false}" = true ]; then
       if ! helm rollback harbor "$previous_revision" -n harbor \
         --wait --wait-for-jobs --timeout=15m; then
         printf 'ERROR: automatic Harbor rollback failed\n' >&2
         code=90
       fi
     fi
     rm -f "${chart:-}"
     unset previous_revision chart harbor_admin_password harbor_auth
     exit "$code"
   }
   trap cutover_cleanup EXIT
   curl -fsSL https://helm.goharbor.io/harbor-1.19.0.tgz -o "$chart"
   test "$(shasum -a 256 "$chart" | awk '{print $1}')" = \
     6b4afcbcb038fbf07a01110e218a61d4d7298b4e90ac46051d8e4ee4505060b3

   harbor_values_without_root() {
     helm get values harbor -n harbor -o json | jq '
       del(
         .persistence.imageChartStorage.s3.accesskey,
         .persistence.imageChartStorage.s3.secretkey
       ) |
       .persistence.imageChartStorage.s3.existingSecret =
         "harbor-s3-credentials"
     '
   }

   harbor_values_without_root | helm upgrade harbor "$chart" \
     -n harbor --dry-run=server --hide-secret -f - >/dev/null
   cutover_started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
   harbor_values_without_root | helm upgrade harbor "$chart" \
     -n harbor --atomic --cleanup-on-fail --wait --wait-for-jobs \
     --timeout=15m -f -
   cutover_active=true
   ```

4. Wait for the registry rollout and prove the runtime contract without
   printing either credential:

   ```bash
   kubectl -n harbor rollout status deployment/harbor-registry --timeout=15m
   helm get values harbor -n harbor -o json | jq -e '
     .persistence.imageChartStorage.s3.existingSecret ==
       "harbor-s3-credentials" and
     (.persistence.imageChartStorage.s3 | has("accesskey") | not) and
     (.persistence.imageChartStorage.s3 | has("secretkey") | not)
   ' >/dev/null
   kubectl -n harbor get deployment harbor-registry -o json | jq -e '
     [.spec.template.spec.containers[] |
       select(.name == "registry" or .name == "registryctl") |
       [(.envFrom // [])[]?.secretRef.name] |
       index("harbor-s3-credentials") != null
     ] | length == 2 and all
   ' >/dev/null
   kubectl -n harbor get secret harbor-registry -o json | jq -e '
     (.data | has("REGISTRY_STORAGE_S3_ACCESSKEY") | not) and
     (.data | has("REGISTRY_STORAGE_S3_SECRETKEY") | not)
   ' >/dev/null
   kubectl get --raw \
     '/api/v1/namespaces/harbor/services/http:harbor:80/proxy/api/v2.0/health' | \
     jq -e '.status == "healthy" and ([.components[].status] | all(. == "healthy"))' \
     >/dev/null
   ```

5. Push and fully pull a uniquely tagged disposable artifact through
   `harbor.e-dani.com` with the normal `robot$gha-org-ci` credential. Delete it
   through Harbor API v2 with the separately prevalidated administrator
   credential, then require a subsequent manifest lookup to return not found.
   The CI robot intentionally has only `push`/`pull` on project `homelab`; do
   not grant it permanent `delete` merely to simplify this smoke test. Confirm
   registry health and no S3 `AccessDenied` around a dry-run
   garbage-collection job.

   Continue in the same protected Bash session as the cutover. This streams the
   existing robot Docker config into a tmpfs-only crane container, pushes a
   real layer, pulls the full image tarball, deletes the artifact through the
   Harbor API, and proves the manifest disappeared:

   ```bash
   smoke_ref="harbor.e-dani.com/homelab/minio-credential-smoke:$(date -u +%Y%m%d%H%M%S)"
   crane_image='gcr.io/go-containerregistry/crane:debug@sha256:1b1fb24d2b1bb27a9daf81a588157e68463876904e8e537a812edba6284fb252'

   smoke_digest="$(
     kubectl -n buildkit get secret harbor-push \
       -o go-template='{{ index .data ".dockerconfigjson" | base64decode }}' |
       docker run --rm -i \
         --mount type=tmpfs,destination=/work \
         --env SMOKE_REF="$smoke_ref" \
         --entrypoint /busybox/sh "$crane_image" -eu -c '
           umask 077
           export DOCKER_CONFIG=/work/docker
           mkdir -p "$DOCKER_CONFIG"
           cat > "$DOCKER_CONFIG/config.json"
           printf credential-cutover-smoke > /work/marker
           /busybox/tar -C /work -cf /work/layer.tar marker
           /ko-app/crane append --oci-empty-base \
             --new_layer /work/layer.tar --new_tag "$SMOKE_REF" >/dev/null
           digest="$(/ko-app/crane digest "$SMOKE_REF")"
           /ko-app/crane pull "$SMOKE_REF@$digest" /work/pulled.tar >/dev/null
           test "$(/ko-app/crane digest --tarball /work/pulled.tar)" = "$digest"
           printf "%s\n" "$digest"
         '
   )"
   case "$smoke_digest" in sha256:*) ;; *) false ;; esac

   delete_code="$(harbor_api_code --request DELETE --url \
     "https://harbor.e-dani.com/api/v2.0/projects/homelab/repositories/minio-credential-smoke/artifacts/$smoke_digest")"
   case "$delete_code" in 200|202) ;; *) false ;; esac

   kubectl -n buildkit get secret harbor-push \
     -o go-template='{{ index .data ".dockerconfigjson" | base64decode }}' |
     docker run --rm -i \
       --mount type=tmpfs,destination=/work \
       --env SMOKE_REF="$smoke_ref" \
       --entrypoint /busybox/sh "$crane_image" -eu -c '
         umask 077
         export DOCKER_CONFIG=/work/docker
         mkdir -p "$DOCKER_CONFIG"
         cat > "$DOCKER_CONFIG/config.json"
         attempts=0
         while [ "$attempts" -lt 15 ]; do
           if ! /ko-app/crane digest "$SMOKE_REF" >/dev/null 2>&1; then
             exit 0
           fi
           attempts=$((attempts + 1))
           /busybox/sleep 2
         done
         exit 1
       '

   if kubectl -n harbor logs deployment/harbor-registry -c registry \
     --since-time "$cutover_started" 2>&1 | \
     rg -i 'AccessDenied|InvalidAccessKeyId|SignatureDoesNotMatch'; then
     false
   fi
   cutover_active=false
   unset harbor_admin_password harbor_auth smoke_digest delete_code
   printf 'HARBOR_MINIO_CREDENTIAL_CUTOVER_PASS\n'
   ```
6. Rollback on any post-upgrade failure before root revocation:

   ```bash
   helm rollback harbor "$previous_revision" -n harbor \
     --wait --wait-for-jobs --timeout=15m
   kubectl -n harbor rollout status deployment/harbor-registry --timeout=15m
   helm get values harbor -n harbor -o json | jq -e '
     (.persistence.imageChartStorage.s3 | has("accesskey")) and
     (.persistence.imageChartStorage.s3 | has("secretkey")) and
     (.persistence.imageChartStorage.s3 | has("existingSecret") | not)
   ' >/dev/null
   cutover_active=false
   ```

   The old root remains valid during this wave. Helm patches the
   `harbor-registry` Secret to remove the two old S3 keys on a successful
   cutover; rollback reconstructs them from the previous Helm revision. Do not
   depend on the live Secret retaining retired keys.

ESO refreshes the Secret but this chart does not hash the external Secret's
contents into the registry Pod template. A later Harbor S3 credential rotation
therefore requires an explicit, reviewed registry rollout after ESO reports the
new Secret Ready; changing Vault alone is not a complete rotation.

### Velero

1. Wait for `ExternalSecret/velero-s3-credentials Ready=True`.
2. Stream current Velero user values through an in-memory transformer that
   changes only `credentials.existingSecret` and the default
   BackupStorageLocation credential name, then pipe directly to
   `helm upgrade --atomic -f -`. Wait for the Deployment. Confirm only
   `BackupStorageLocation/default` references the new Secret;
   `x86-backup-minio` must retain its own credential.
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
   The separately operated `backup-hub/backup-minio` currently uses the same
   literal pair and is an explicit exception: do not edit it in this wave and
   do not mistake its continued acceptance for acceptance by the main endpoint.
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
  zero occurrences of the revoked pair within the main-MinIO server and
  consumer scope. `backup-hub` remains a documented exception until its own
  coordinated K3s-etcd-safe rotation.
- Root-v2 works on the main MinIO endpoint; old root is rejected by that same
  endpoint.
- Harbor push/pull/delete, Velero backup/restore, Loki ingest/query/retention,
  CNPG backups, and the OpenClaw backup target all pass.
- `backup-hub/backup-minio` and K3s etcd remain unchanged; their separate debt
  is handled in a later coordinated wave.

References:

- MinIO user management: https://min.io/docs/minio/linux/administration/identity-access-management/minio-user-management.html
- Harbor/Distribution S3 permissions: https://distribution.github.io/distribution/storage-drivers/s3/
- Velero AWS plugin permissions: https://github.com/velero-io/velero-plugin-for-aws/blob/main/README.md
- Loki storage permissions: https://grafana.com/docs/loki/latest/operations/storage/
