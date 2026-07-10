#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
ulimit -c 0 >/dev/null 2>&1 || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPECTED_CONTEXT="${EXPECTED_CONTEXT:-x86-k3s}"

declare -A USERS=(
  [breakglass]="minio-breakglass-admin"
  [harbor]="harbor-s3"
  [velero]="velero-s3"
  [loki]="loki-s3"
)
declare -A PATHS=(
  [breakglass]="minio/breakglass-admin"
  [harbor]="minio/harbor-s3"
  [velero]="minio/velero-s3"
  [loki]="minio/loki-s3"
)
declare -A PASSWORDS
declare -a WRITTEN_PATHS=()
declare -a CREATED_POLICIES=()
declare -a CREATED_USERS=()
VAULT_TOKEN=""

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

minio_admin() {
  kubectl -n minio exec minio-0 -- sh -eu -c '
    d=$(mktemp -d)
    trap "rm -rf $d" EXIT
    mc --config-dir "$d" alias set admin http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc --config-dir "$d" "$@"
  ' sh "$@"
}

vault_path_exists() {
  local path="$1"
  printf '%s\n' "$VAULT_TOKEN" | kubectl -n vault exec -i vault-0 -- sh -eu -c '
    IFS= read -r token
    export VAULT_TOKEN="$token"
    vault kv get -mount=secret "$1" >/dev/null 2>&1
  ' sh "$path" >/dev/null 2>&1
}

vault_put() {
  local path="$1" access_key="$2" secret_key="$3"
  # Register first so an ambiguous transport failure after the server-side
  # write is still cleaned up.
  WRITTEN_PATHS+=("$path")
  printf '%s\n%s\n%s\n' "$VAULT_TOKEN" "$access_key" "$secret_key" |
    kubectl -n vault exec -i vault-0 -- sh -eu -c '
      IFS= read -r token
      IFS= read -r access_key
      IFS= read -r secret_key
      export VAULT_TOKEN="$token"
      vault kv put -mount=secret "$1" access_key="$access_key" secret_key="$secret_key" >/dev/null
      unset token access_key secret_key
    ' sh "$path" >/dev/null
}

create_policy() {
  local name="$1" file="$2"
  # Policy deletion is idempotent; register before the remote create in case
  # the API succeeds but the exec transport returns an error.
  CREATED_POLICIES+=("$name")
  kubectl -n minio exec -i minio-0 -- sh -eu -c '
    policy=$(mktemp)
    d=$(mktemp -d)
    trap "rm -f $policy; rm -rf $d" EXIT
    dd of="$policy" 2>/dev/null
    mc --config-dir "$d" alias set admin http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
    mc --config-dir "$d" admin policy create admin "$1" "$policy" >/dev/null
  ' sh "$name" < "$file" >/dev/null
}

create_user() {
  local key="$1" policy="$2"
  # Keep dependent expansions in separate declarations: Bash expands every
  # assignment in one `local` command before the earlier assignment is usable.
  local user="${USERS[$key]}"
  local password="${PASSWORDS[$key]}"
  # Register the rollback target before the remote operation. Removing a user
  # that was not created is harmless, while losing a user after a partial
  # add/attach sequence is not.
  CREATED_USERS+=("$user")
  printf '%s\n%s\n%s\n' "$user" "$password" "$policy" |
    kubectl -n minio exec -i minio-0 -- sh -eu -c '
      IFS= read -r user
      IFS= read -r password
      IFS= read -r policy
      d=$(mktemp -d)
      trap "rm -rf $d" EXIT
      mc --config-dir "$d" alias set admin http://127.0.0.1:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
      mc --config-dir "$d" admin user add admin "$user" "$password" >/dev/null
      mc --config-dir "$d" admin user info admin "$user" >/dev/null
      mc --config-dir "$d" admin policy attach admin "$policy" --user "$user" >/dev/null
      unset user password
    ' >/dev/null
}

probe_bucket() {
  local key="$1" bucket="$2" large="${3:-false}"
  local probe=".bootstrap-probe-$(date -u +%Y%m%d%H%M%S)-$RANDOM"
  printf '%s\n%s\n%s\n%s\n%s\n' "${USERS[$key]}" "${PASSWORDS[$key]}" "$bucket" "$probe" "$large" |
    kubectl -n minio exec -i minio-0 -- sh -eu -c '
      IFS= read -r user
      IFS= read -r password
      IFS= read -r bucket
      IFS= read -r probe
      IFS= read -r large
      d=$(mktemp -d)
      trap "rm -rf $d" EXIT
      mc --config-dir "$d" alias set scoped http://127.0.0.1:9000 "$user" "$password" >/dev/null
      if [ "$large" = true ]; then
        dd if=/dev/zero of="$d/probe" bs=1M count=65 2>/dev/null
      else
        printf probe > "$d/probe"
      fi
      mc --config-dir "$d" cp "$d/probe" "scoped/$bucket/$probe" >/dev/null
      mc --config-dir "$d" cat "scoped/$bucket/$probe" >/dev/null
      mc --config-dir "$d" rm "scoped/$bucket/$probe" >/dev/null
      mc --config-dir "$d" ls "scoped/$bucket/" >/dev/null
      other=harbor-blobs
      [ "$bucket" = harbor-blobs ] && other=velero-backups
      if mc --config-dir "$d" ls "scoped/$other/" >/dev/null 2>&1; then
        printf "unexpected cross-bucket permission\n" >&2
        exit 1
      fi
      unset user password
    ' >/dev/null
}

probe_breakglass() {
  printf '%s\n%s\n' "${USERS[breakglass]}" "${PASSWORDS[breakglass]}" |
    kubectl -n minio exec -i minio-0 -- sh -eu -c '
      IFS= read -r user
      IFS= read -r password
      d=$(mktemp -d)
      trap "rm -rf $d" EXIT
      mc --config-dir "$d" alias set breakglass http://127.0.0.1:9000 "$user" "$password" >/dev/null
      mc --config-dir "$d" admin info breakglass >/dev/null
      unset user password
    ' >/dev/null
}

rollback() {
  local code=$?
  if (( code != 0 )); then
    for user in "${CREATED_USERS[@]}"; do
      minio_admin admin user remove admin "$user" >/dev/null 2>&1 || true
    done
    for policy in "${CREATED_POLICIES[@]}"; do
      minio_admin admin policy remove admin "$policy" >/dev/null 2>&1 || true
    done
    for path in "${WRITTEN_PATHS[@]}"; do
      printf '%s\n' "$VAULT_TOKEN" | kubectl -n vault exec -i vault-0 -- sh -eu -c '
        IFS= read -r token
        export VAULT_TOKEN="$token"
        vault kv metadata delete -mount=secret "$1" >/dev/null
      ' sh "$path" >/dev/null 2>&1 || true
    done
    printf 'bootstrap failed; all resources created by this run were rolled back\n' >&2
  fi
  for key in "${!PASSWORDS[@]}"; do unset 'PASSWORDS[$key]'; done
  unset VAULT_TOKEN
  exit "$code"
}
trap rollback EXIT

[[ "${1:-}" == "--execute" ]] || fail "usage: MINIO_CHANGE_WINDOW_APPROVED=yes $0 --execute"
[[ "${MINIO_CHANGE_WINDOW_APPROVED:-}" == "yes" ]] || fail "change window is not approved"
[[ "$(kubectl config current-context)" == "$EXPECTED_CONTEXT" ]] || fail "unexpected Kubernetes context"
for tool in kubectl jq openssl; do command -v "$tool" >/dev/null 2>&1 || fail "missing tool: $tool"; done

kubectl -n argocd get applications.argoproj.io -o json | jq -e '
  [.items[] | select(
    .status.health.status != "Healthy" or
    .status.sync.status != "Synced" or
    (.status.operationState.phase == "Running")
  )] | length == 0
' >/dev/null || fail "Argo is not globally quiescent"
kubectl -n vault wait --for=condition=Ready pod/vault-0 --timeout=30s >/dev/null
kubectl -n minio wait --for=condition=Ready pod/minio-0 --timeout=30s >/dev/null

for key in harbor velero loki; do jq -e . "$ROOT/storage/minio/$key-s3-policy.json" >/dev/null; done

VAULT_TOKEN="$(kubectl -n vault get secret vault-admin-token -o go-template='{{ index .data "token" | base64decode }}')"
[[ -n "$VAULT_TOKEN" ]] || fail "Vault admin token is unavailable"

for key in breakglass harbor velero loki; do
  vault_path_exists "${PATHS[$key]}" && fail "refusing to overwrite an existing Vault path: ${PATHS[$key]}"
  minio_admin admin user info admin "${USERS[$key]}" >/dev/null 2>&1 && fail "refusing to overwrite an existing MinIO user: ${USERS[$key]}"
  PASSWORDS[$key]="$(openssl rand -hex 24)"
done
for policy in harbor-s3 velero-s3 loki-s3; do
  minio_admin admin policy info admin "$policy" >/dev/null 2>&1 && fail "refusing to overwrite an existing MinIO policy: $policy"
done

for key in breakglass harbor velero loki; do
  vault_put "${PATHS[$key]}" "${USERS[$key]}" "${PASSWORDS[$key]}"
done

create_user breakglass consoleAdmin
create_policy harbor-s3 "$ROOT/storage/minio/harbor-s3-policy.json"
create_user harbor harbor-s3
create_policy velero-s3 "$ROOT/storage/minio/velero-s3-policy.json"
create_user velero velero-s3
create_policy loki-s3 "$ROOT/storage/minio/loki-s3-policy.json"
create_user loki loki-s3

probe_breakglass
probe_bucket harbor harbor-blobs true
probe_bucket velero velero-backups true
probe_bucket loki loki-chunks false

for key in "${!PASSWORDS[@]}"; do unset 'PASSWORDS[$key]'; done
unset VAULT_TOKEN
trap - EXIT
printf 'MINIO_WORKLOAD_IDENTITIES_READY\n'
