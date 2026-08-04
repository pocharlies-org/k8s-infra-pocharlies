#!/usr/bin/env bash
set -euo pipefail

# Activate an ACL file already reconciled by External Secrets. Kubernetes
# refreshes the mounted Secret eventually, but Valkey keeps its ACL in memory
# until ACL LOAD (or a process restart). This gate waits for both layers before
# loading the file on every member and proving the new account's boundaries.

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
for pod in "${pods[@]}"; do
  kubectl -n "$namespace" exec "$pod" -c valkey -- sh -ec '
    attempt=1
    while [ "$attempt" -le 60 ]; do
      if grep -q "^user chatbot " /acl/users.acl; then
        exit 0
      fi
      attempt=$((attempt + 1))
      sleep 2
    done
    exit 1
  ' || fail "projected ACL file is stale on ${pod}"
done

for pod in "${pods[@]}"; do
  kubectl -n "$namespace" exec "$pod" -c valkey -- sh -ec '
    result="$(valkey-cli -p 6379 --user sentinel -a "$SENTINEL_VALKEY_PASSWORD" --no-auth-warning ACL LOAD)"
    [ "$result" = "OK" ]
  ' || fail "ACL LOAD failed on ${pod}"
done

master_count=0
replica_count=0
master_pod=""
for pod in "${pods[@]}"; do
  role="$(kubectl -n "$namespace" exec "$pod" -c valkey -- sh -ec \
    'valkey-cli -p 6379 --user sentinel -a "$SENTINEL_VALKEY_PASSWORD" --no-auth-warning ROLE | head -1')"
  case "$role" in
    master)
      master_count=$((master_count + 1))
      master_pod="$pod"
      ;;
    slave|replica) replica_count=$((replica_count + 1)) ;;
    *) fail "unexpected role on ${pod}: ${role}" ;;
  esac
done

[[ "$master_count" == 1 && "$replica_count" == 2 ]] || \
  fail "expected one master and two replicas; observed ${master_count} master(s) and ${replica_count} replica(s)"

for pod in "${pods[@]}"; do
  kubectl -n "$namespace" exec "$pod" -c valkey -- sh -ec '
    admin() {
      valkey-cli -p 6379 --user sentinel -a "$SENTINEL_VALKEY_PASSWORD" --no-auth-warning "$@"
    }

    [ "$(admin ACL DRYRUN chatbot PING)" = "OK" ]
    [ "$(admin ACL DRYRUN chatbot HSET skirmshop:commerce:v1:acl-activation-probe field value)" = "OK" ]
    denied="$(admin ACL DRYRUN chatbot HSET rho:forbidden:acl-activation-probe field value 2>&1 || true)"
    case "$denied" in
      *NOPERM*) ;;
      *) exit 1 ;;
    esac

    chatbot_password="$(awk '\''$1 == "user" && $2 == "chatbot" { for (i = 3; i <= NF; i += 1) if ($i ~ /^>/) { print substr($i, 2); exit } }'\'' /acl/users.acl)"
    [ -n "$chatbot_password" ]
    VALKEYCLI_AUTH="$chatbot_password" valkey-cli -p 6379 --user chatbot --no-auth-warning PING | grep -qx PONG
    VALKEYCLI_AUTH="$chatbot_password" valkey-cli -p 6379 --user chatbot --no-auth-warning \
      HGET skirmshop:commerce:v1:acl-activation-probe field >/dev/null
    unset chatbot_password
  ' || fail "chatbot ACL verification failed on ${pod}"
done

# A real write proves command authentication end to end. Run it only against
# the elected master; healthy replicas correctly reject writes as READONLY.
kubectl -n "$namespace" exec "$master_pod" -c valkey -- sh -ec '
  chatbot_password="$(awk '\''$1 == "user" && $2 == "chatbot" { for (i = 3; i <= NF; i += 1) if ($i ~ /^>/) { print substr($i, 2); exit } }'\'' /acl/users.acl)"
  [ -n "$chatbot_password" ]
  VALKEYCLI_AUTH="$chatbot_password" valkey-cli -p 6379 --user chatbot --no-auth-warning \
    HSET skirmshop:commerce:v1:acl-activation-probe field value | grep -Eq '\''^[01]$'\''
  VALKEYCLI_AUTH="$chatbot_password" valkey-cli -p 6379 --user chatbot --no-auth-warning \
    DEL skirmshop:commerce:v1:acl-activation-probe >/dev/null
  unset chatbot_password
' || fail "authenticated chatbot write probe failed on ${master_pod}"

printf 'shared-valkey ACL activation verified on all three members\n'
