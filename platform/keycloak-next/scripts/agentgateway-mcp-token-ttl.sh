#!/bin/sh
set -eu

umask 077

# INFRA-187: owns the per-client access token lifespan override
# (attributes."access.token.lifespan") of the agentgateway-mcp client in the
# edani realm and NOTHING else. Measured 2026-09-19 the override was 2592000
# seconds (30 days), which let a stale pre-grant token of the local
# agentgateway-auth-proxy keep authenticating for days against the gated
# AgentGateway routes (INFRA-138/INFRA-139). This hook owns it as 3600 (1 h),
# so the proxy's own refresh (expires_in - 60 s) is the only way a token of
# this client can outlive one hour.
#
# Scope is deliberately the narrowest in this platform: this is the only
# client attribute the hook reads or writes. Roles, scope mappings, the secret
# and every other attribute belong to the other reconcilers
# (agentgateway-write-role, agentgateway-read-grants) and stay untouched
# here; the post-write checks below only VERIFY that the identity flags did
# not move. The hook never creates the client: it fails closed if
# agentgateway-mcp is missing, and fails closed if the override attribute is
# absent (then the realm default applies — a shorter TTL, the safe direction
# — and restoring an override is a reviewed change, not a guess).
#
# Why a full-document read-modify-write instead of kcadm -s: the attribute
# key itself contains dots ("access.token.lifespan"), which kcadm -s would
# interpret as nested paths, so the hook GETs the client, replaces exactly the
# one lifespan value in the retrieved document and PUTs that document back.
# Under any merge semantics of "kcadm update -f" (replace or merge) the
# written document is the full current representation with one value changed.
#
# Rollback = git revert of the commit owning EXPECTED_ACCESS_TOKEN_LIFESPAN:
# the target lives in this script, so the next PostSync restores the reverted
# value; no manual rollback Job is shipped for this hook.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-agentgateway-mcp}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
EXPECTED_ACCESS_TOKEN_LIFESPAN="${EXPECTED_ACCESS_TOKEN_LIFESPAN:-3600}"
ADMIN_CONFIG=/tmp/kcadm-mcp-token-ttl-admin.config
CLIENT_DOC=/tmp/kcadm-mcp-token-ttl-client.json
CLIENT_DOC_NEW=/tmp/kcadm-mcp-token-ttl-client.new.json

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_DOC}" "${CLIENT_DOC_NEW}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${CLIENT_ID}" "$1"
}

[ "${CLIENT_ID}" = "agentgateway-mcp" ] || fail "CLIENT_ID is immutable"
[ "${EXPECTED_ACCESS_TOKEN_LIFESPAN}" = "3600" ] || \
  fail "EXPECTED_ACCESS_TOKEN_LIFESPAN is immutable; change it only by reverting/reviewing INFRA-187"
case "${MODE}" in
  ensure|audit) ;;
  *) fail "MODE must be ensure or audit" ;;
esac

nonempty_lines() { sed '/^[[:space:]]*$/d'; }

line_count() {
  nonempty_lines | wc -l | tr -d '[:space:]'
}

login_admin() {
  attempt=1
  while [ "${attempt}" -le 30 ]; do
    if "${KCADM}" config credentials \
      --config "${ADMIN_CONFIG}" \
      --server "${KEYCLOAK_URL}" \
      --realm master \
      --user "${KC_BOOTSTRAP_ADMIN_USERNAME}" \
      --password "${KC_BOOTSTRAP_ADMIN_PASSWORD}" >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 5
  done
  fail "Keycloak admin login did not become ready"
}

kget() {
  "${KCADM}" get "$@" --config "${ADMIN_CONFIG}" -r "${REALM}"
}

client_field() {
  kget "clients/$1" --fields "$2" --format csv --noquotes | nonempty_lines
}

resolve_client() {
  rows="$(kget clients -q "clientId=${CLIENT_ID}" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" = "1" ] || fail "expected exactly one client ${CLIENT_ID}"
  printf '%s' "${rows}"
}

current_lifespan() {
  # Extract the one dotted-key attribute from the attributes map; empty when
  # the client carries no override (realm default applies then).
  kget "clients/$1" --fields attributes --format json | \
    sed -n 's/.*"access\.token\.lifespan"[[:space:]]*:[[:space:]]*"\([0-9][0-9]*\)".*/\1/p' | \
    nonempty_lines
}

login_admin
progress "admin logged in"

CLIENT_UUID="$(resolve_client)"
[ "$(client_field "${CLIENT_UUID}" enabled)" = "true" ] || \
  fail "client ${CLIENT_ID} is disabled"
[ "$(client_field "${CLIENT_UUID}" serviceAccountsEnabled)" = "true" ] || \
  fail "client ${CLIENT_ID} has no service account"
progress "client resolved"

before_lifespan="$(current_lifespan "${CLIENT_UUID}")"
[ -n "${before_lifespan}" ] || \
  fail "client ${CLIENT_ID} carries no access.token.lifespan override: refusing to write one blind (realm default applies and is shorter than the owned 3600)"

# Identity flags this hook must leave exactly as it found them.
before_enabled="$(client_field "${CLIENT_UUID}" enabled)"
before_service_accounts="$(client_field "${CLIENT_UUID}" serviceAccountsEnabled)"
before_fullscope="$(client_field "${CLIENT_UUID}" fullScopeAllowed)"
before_standard_flow="$(client_field "${CLIENT_UUID}" standardFlowEnabled)"

if [ "${MODE}" = "audit" ]; then
  [ "${before_lifespan}" = "${EXPECTED_ACCESS_TOKEN_LIFESPAN}" ] || \
    fail "audit: access.token.lifespan is ${before_lifespan} not ${EXPECTED_ACCESS_TOKEN_LIFESPAN} on ${CLIENT_ID}"
  printf '{"client_id":"%s","access_token_lifespan":"%s","in_sync":true}\n' "${CLIENT_ID}" "${before_lifespan}"
  exit 0
fi

if [ "${before_lifespan}" = "${EXPECTED_ACCESS_TOKEN_LIFESPAN}" ]; then
  printf '{"client_id":"%s","access_token_lifespan":"%s","in_sync":true}\n' "${CLIENT_ID}" "${before_lifespan}"
  exit 0
fi

# Read-modify-write of the full client document (see header for why).
kget "clients/${CLIENT_UUID}" > "${CLIENT_DOC}" || fail "failed to read the ${CLIENT_ID} client document"
[ "$(grep -c '"access\.token\.lifespan"' "${CLIENT_DOC}")" = "1" ] || \
  fail "expected exactly one access.token.lifespan entry in the ${CLIENT_ID} document, found $(grep -c '"access\.token\.lifespan"' "${CLIENT_DOC}")"
sed 's/"access\.token\.lifespan"[[:space:]]*:[[:space:]]*"[0-9][0-9]*"/"access.token.lifespan":"'"${EXPECTED_ACCESS_TOKEN_LIFESPAN}"'"/' \
  "${CLIENT_DOC}" > "${CLIENT_DOC_NEW}" || fail "failed to rewrite the client document"
[ "$(grep -c '"access\.token\.lifespan"[[:space:]]*:[[:space:]]*"'"${EXPECTED_ACCESS_TOKEN_LIFESPAN}"'"' "${CLIENT_DOC_NEW}")" = "1" ] || \
  fail "rewritten document does not carry exactly one access.token.lifespan=${EXPECTED_ACCESS_TOKEN_LIFESPAN}"

"${KCADM}" update "clients/${CLIENT_UUID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
  -f "${CLIENT_DOC_NEW}" >/dev/null 2>&1 || \
  fail "failed to set access.token.lifespan=${EXPECTED_ACCESS_TOKEN_LIFESPAN} on ${CLIENT_ID}"
[ "$(current_lifespan "${CLIENT_UUID}")" = "${EXPECTED_ACCESS_TOKEN_LIFESPAN}" ] || \
  fail "access.token.lifespan did not become ${EXPECTED_ACCESS_TOKEN_LIFESPAN} on ${CLIENT_ID}"

# Post-write invariants: the write must not have moved anything but the TTL.
[ "$(client_field "${CLIENT_UUID}" enabled)" = "${before_enabled}" ] || \
  fail "enabled changed on ${CLIENT_ID} during the TTL write"
[ "$(client_field "${CLIENT_UUID}" serviceAccountsEnabled)" = "${before_service_accounts}" ] || \
  fail "serviceAccountsEnabled changed on ${CLIENT_ID} during the TTL write"
[ "$(client_field "${CLIENT_UUID}" fullScopeAllowed)" = "${before_fullscope}" ] || \
  fail "fullScopeAllowed changed on ${CLIENT_ID} during the TTL write"
[ "$(client_field "${CLIENT_UUID}" standardFlowEnabled)" = "${before_standard_flow}" ] || \
  fail "standardFlowEnabled changed on ${CLIENT_ID} during the TTL write"

printf '{"client_id":"%s","access_token_lifespan":"%s","previous":"%s","in_sync":true}\n' \
  "${CLIENT_ID}" "${EXPECTED_ACCESS_TOKEN_LIFESPAN}" "${before_lifespan}"
