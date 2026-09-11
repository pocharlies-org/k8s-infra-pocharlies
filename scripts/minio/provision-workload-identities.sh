#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
ulimit -c 0 >/dev/null 2>&1 || true

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXPECTED_CONTEXT="${EXPECTED_CONTEXT:-x86-k3s}"

# 1Password destination (SC-490 / SC-498): vault k8s-pocharlies, service account
# with Read & Write on that vault only. The token is provided either directly in
# OP_SERVICE_ACCOUNT_TOKEN or in a 0600 file via OP_SA_TOKEN_FILE (same pattern
# as _ops/vault-to-1password/op-sa.sh); it never appears on a command line.
OP_VAULT="${OP_VAULT:-k8s-pocharlies}"

declare -A USERS=(
  [breakglass]="minio-breakglass-admin"
  [harbor]="harbor-s3"
  [velero]="velero-s3"
  [loki]="loki-s3"
)
# Item titles follow the migration convention (vault path `/` -> `-`, mount
# dropped): secret/minio/harbor-s3 -> minio-harbor-s3. Field labels stay
# identical to the old KV keys: access_key / secret_key.
declare -A ITEMS=(
  [breakglass]="minio-breakglass-admin"
  [harbor]="minio-harbor-s3"
  [velero]="minio-velero-s3"
  [loki]="minio-loki-s3"
)
declare -A PASSWORDS
declare -a WRITTEN_ITEMS=()
declare -a CREATED_POLICIES=()
declare -a CREATED_USERS=()
declare -a OP_TEMPLATE_FILES=()

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

cleanup_op_templates() {
  local f
  for f in "${OP_TEMPLATE_FILES[@]}"; do
    shred -u "$f" >/dev/null 2>&1 || rm -f "$f" 2>/dev/null || true
  done
  OP_TEMPLATE_FILES=()
}

op_item_exists() {
  local item="$1"
  op item get "$item" --vault "$OP_VAULT" --format json >/dev/null 2>&1
}

op_item_create() {
  local item="$1" access_key="$2" secret_key="$3"
  # Register first so an ambiguous transport failure after the server-side
  # write is still cleaned up.
  WRITTEN_ITEMS+=("$item")
  # Values are passed through a 0600 template file, never via argv, and the
  # field labels match the old KV keys exactly. NOTE (verified 11-09 during the
  # Vault->1Password migration): `op item edit --template` does NOT merge, it
  # REPLACES the item's whole field list, so rotating an existing item must
  # always send the complete set (access_key + secret_key together). This
  # provisioner only ever creates: an existing item is refused up front.
  local tmp
  tmp="$(mktemp)"
  OP_TEMPLATE_FILES+=("$tmp")
  chmod 600 "$tmp"
  printf '%s\n' "{\"title\":\"${item}\",\"category\":\"SECURE_NOTE\",\"fields\":[{\"id\":\"access_key\",\"type\":\"CONCEALED\",\"label\":\"access_key\",\"value\":\"${access_key}\"},{\"id\":\"secret_key\",\"type\":\"CONCEALED\",\"label\":\"secret_key\",\"value\":\"${secret_key}\"}]}" >"$tmp"
  op item create --vault "$OP_VAULT" --template "$tmp" >/dev/null
  shred -u "$tmp" >/dev/null 2>&1 || rm -f "$tmp"
  local f kept=()
  for f in "${OP_TEMPLATE_FILES[@]}"; do
    [[ "$f" == "$tmp" ]] || kept+=("$f")
  done
  OP_TEMPLATE_FILES=("${kept[@]+"${kept[@]}"}")
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
    for item in "${WRITTEN_ITEMS[@]}"; do
      op item delete "$item" --vault "$OP_VAULT" >/dev/null 2>&1 || true
    done
    printf 'bootstrap failed; all resources created by this run were rolled back\n' >&2
  fi
  cleanup_op_templates
  for key in "${!PASSWORDS[@]}"; do unset 'PASSWORDS[$key]'; done
  exit "$code"
}
trap rollback EXIT

[[ "${1:-}" == "--execute" ]] || fail "usage: MINIO_CHANGE_WINDOW_APPROVED=yes $0 --execute"
[[ "${MINIO_CHANGE_WINDOW_APPROVED:-}" == "yes" ]] || fail "change window is not approved"
[[ "$(kubectl config current-context)" == "$EXPECTED_CONTEXT" ]] || fail "unexpected Kubernetes context"
for tool in kubectl jq openssl op; do command -v "$tool" >/dev/null 2>&1 || fail "missing tool: $tool"; done

if [[ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" && -n "${OP_SA_TOKEN_FILE:-}" ]]; then
  [[ -f "$OP_SA_TOKEN_FILE" ]] || fail "OP_SA_TOKEN_FILE not found"
  OP_SERVICE_ACCOUNT_TOKEN="$(cat "$OP_SA_TOKEN_FILE")"
  export OP_SERVICE_ACCOUNT_TOKEN
fi
[[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]] ||
  fail "set OP_SERVICE_ACCOUNT_TOKEN (or OP_SA_TOKEN_FILE) for a service account with Read & Write on vault $OP_VAULT"
op item list --vault "$OP_VAULT" --format json >/dev/null ||
  fail "1Password service account cannot read vault $OP_VAULT"

kubectl -n argocd get applications.argoproj.io -o json | jq -e '
  [.items[] | select(
    .status.health.status != "Healthy" or
    .status.sync.status != "Synced" or
    (.status.operationState.phase == "Running")
  )] | length == 0
' >/dev/null || fail "Argo is not globally quiescent"
kubectl -n minio wait --for=condition=Ready pod/minio-0 --timeout=30s >/dev/null

for key in harbor velero loki; do jq -e . "$ROOT/storage/minio/$key-s3-policy.json" >/dev/null; done

for key in breakglass harbor velero loki; do
  op_item_exists "${ITEMS[$key]}" && fail "refusing to overwrite an existing 1Password item: ${ITEMS[$key]}"
  minio_admin admin user info admin "${USERS[$key]}" >/dev/null 2>&1 && fail "refusing to overwrite an existing MinIO user: ${USERS[$key]}"
  PASSWORDS[$key]="$(openssl rand -hex 24)"
done
for policy in harbor-s3 velero-s3 loki-s3; do
  minio_admin admin policy info admin "$policy" >/dev/null 2>&1 && fail "refusing to overwrite an existing MinIO policy: $policy"
done

for key in breakglass harbor velero loki; do
  op_item_create "${ITEMS[$key]}" "${USERS[$key]}" "${PASSWORDS[$key]}"
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
trap - EXIT
printf 'MINIO_WORKLOAD_IDENTITIES_READY\n'
