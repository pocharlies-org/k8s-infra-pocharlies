#!/usr/bin/env bash
set -euo pipefail

# Activate an ACL file already reconciled by External Secrets. Kubernetes
# refreshes the mounted Secret eventually, but Valkey keeps its ACL in memory
# until ACL LOAD (or a process restart). This gate waits for both layers before
# loading the file on every member and checks the quorum topology afterwards.
# Per-account boundaries are not proven here: the ACL content is owned by the
# secret in 1Password, not by this script.

namespace="${VALKEY_NAMESPACE:-databases}"
external_secret="${VALKEY_EXTERNAL_SECRET:-shared-valkey-acl}"
secret_name="${VALKEY_ACL_SECRET:-shared-valkey-acl}"
pods=(shared-valkey-0 shared-valkey-1 shared-valkey-2)
wait_attempts="${VALKEY_ACL_WAIT_ATTEMPTS:-60}"

fail() {
  printf 'shared-valkey ACL activation failed: %s\n' "$*" >&2
  exit 1
}

kubectl -n "$namespace" get "externalsecret/${external_secret}" >/dev/null
previous_refresh_time="$(kubectl -n "$namespace" get "externalsecret/${external_secret}" -o jsonpath='{.status.refreshTime}')"
kubectl -n "$namespace" annotate "externalsecret/${external_secret}" \
  "force-sync=$(date -u +%Y%m%dT%H%M%SZ)-$$" --overwrite >/dev/null

for ((attempt = 1; attempt <= wait_attempts; attempt += 1)); do
  ready="$(kubectl -n "$namespace" get "externalsecret/${external_secret}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')"
  reason="$(kubectl -n "$namespace" get "externalsecret/${external_secret}" -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}')"
  refresh_time="$(kubectl -n "$namespace" get "externalsecret/${external_secret}" -o jsonpath='{.status.refreshTime}')"
  if [[ "$ready" == "True" && "$reason" == "SecretSynced" && -n "$refresh_time" && "$refresh_time" != "$previous_refresh_time" ]]; then
    break
  fi
  if [[ "$attempt" == "$wait_attempts" ]]; then
    fail "ExternalSecret did not report a new SecretSynced refresh"
  fi
  sleep 2
done

actual_keys="$(kubectl -n "$namespace" get "secret/${secret_name}" -o go-template='{{range $key, $_ := .data}}{{printf "%s\n" $key}}{{end}}' | LC_ALL=C sort)"
expected_keys="$(printf '%s\n' replication-password sentinel-password sentinel-valkey-password users.acl | LC_ALL=C sort)"
[[ "$actual_keys" == "$expected_keys" ]] || fail "Secret key set is incomplete or contains unexpected keys"

for pod in "${pods[@]}"; do
  kubectl -n "$namespace" wait --for=condition=Ready "pod/${pod}" --timeout=120s >/dev/null
done

# Wait until kubelet has projected the reconciled ACL file on every pod before
# changing any process. This keeps a retry from leaving members on two files.
# The projected file is compared against the Secret content by hash, so the
# gate is independent of which accounts the ACL happens to define.
expected_sha="$(kubectl -n "$namespace" get "secret/${secret_name}" \
  -o "jsonpath={.data.users\.acl}" | base64 -d | sha256sum | cut -d' ' -f1)"
[[ -n "$expected_sha" ]] || fail "secret/${secret_name} has no users.acl content"
for pod in "${pods[@]}"; do
  kubectl -n "$namespace" exec "$pod" -c valkey -- sh -ec '
    expected="$1"
    attempt=1
    while [ "$attempt" -le 60 ]; do
      actual="$(sha256sum /acl/users.acl 2>/dev/null | cut -d" " -f1)"
      [ "$actual" = "$expected" ] && exit 0
      attempt=$((attempt + 1))
      sleep 2
    done
    exit 1
  ' sh "$expected_sha" || fail "projected ACL file is stale on ${pod}"
done

for pod in "${pods[@]}"; do
  kubectl -n "$namespace" exec "$pod" -c valkey -- sh -ec '
    result="$(valkey-cli -p 6379 --user sentinel -a "$SENTINEL_VALKEY_PASSWORD" --no-auth-warning ACL LOAD)"
    [ "$result" = "OK" ]
  ' || fail "ACL LOAD failed on ${pod}"
done

master_count=0
replica_count=0
for pod in "${pods[@]}"; do
  role="$(kubectl -n "$namespace" exec "$pod" -c valkey -- sh -ec \
    'valkey-cli -p 6379 --user sentinel -a "$SENTINEL_VALKEY_PASSWORD" --no-auth-warning ROLE | head -1')"
  case "$role" in
    master) master_count=$((master_count + 1)) ;;
    slave|replica) replica_count=$((replica_count + 1)) ;;
    *) fail "unexpected role on ${pod}: ${role}" ;;
  esac
done

[[ "$master_count" == 1 && "$replica_count" == 2 ]] || \
  fail "expected one master and two replicas; observed ${master_count} master(s) and ${replica_count} replica(s)"

printf 'shared-valkey ACL activation loaded on all three members\n'
