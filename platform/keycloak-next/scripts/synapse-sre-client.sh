#!/bin/sh
set -eu

umask 077

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-synapse-sre-orchestrator}"
ROLE_NAME="${ROLE_NAME:-synapse-sre-m2m}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
FORBIDDEN_REALM_ROLE="${FORBIDDEN_REALM_ROLE:-agentgateway-write}"
RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-synapse-sre-admin.config
CLIENT_CONFIG=/tmp/kcadm-synapse-sre-client.config

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${CLIENT_ID}" "$1"
}

[ "${FORBIDDEN_REALM_ROLE}" = "agentgateway-write" ] || fail "FORBIDDEN_REALM_ROLE is immutable"
[ "${RECONCILE_CONTRACT_VERSION}" = "1" ] || fail "unsupported reconcile contract version"
case "${CLIENT_ID}:${ROLE_NAME}" in
  synapse-sre-orchestrator:synapse-sre-m2m)
    CLIENT_SECRET="${SYNAPSE_SRE_CLIENT_SECRET:-}"
    MAPPER_NAME=synapse-sre-agentgateway-audience
    ROLE_DESCRIPTION='Allows only the typed Synapse and OpenClaw SRE M2M planes'
    ;;
  synapse-draft-orchestrator:synapse-draft-m2m)
    CLIENT_SECRET="${SYNAPSE_DRAFT_CLIENT_SECRET:-}"
    MAPPER_NAME=synapse-draft-agentgateway-audience
    ROLE_DESCRIPTION='Allows only the typed Synapse and OpenClaw draft M2M planes'
    ;;
  *) fail "unsupported immutable client/role pair" ;;
esac
case "${MODE}" in
  ensure|audit)
    [ -n "${CLIENT_SECRET}" ] || fail "client secret is empty"
    ;;
  rollback) ;;
  *) fail "unsupported MODE=${MODE}" ;;
esac

nonempty_lines() {
  sed '/^[[:space:]]*$/d'
}

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

resolve_client_optional() {
  rows="$(kget clients -q "clientId=${CLIENT_ID}" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate client ${CLIENT_ID}"
  printf '%s' "${rows}"
}

require_client() {
  uuid="$(resolve_client_optional)"
  [ -n "${uuid}" ] || fail "client ${CLIENT_ID} is missing"
  printf '%s' "${uuid}"
}

client_field() {
  kget "clients/$1" --fields "$2" --format csv --noquotes | nonempty_lines
}

assert_client_boolean() {
  actual="$(client_field "$1" "$2")"
  [ "${actual}" = "$3" ] || fail "client field $2 expected $3"
}

upsert_client() {
  uuid="$(resolve_client_optional)"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=false \
    -s standardFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=true \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s "secret=${CLIENT_SECRET}" >/dev/null 2>&1 || \
    fail "failed to reconcile ${CLIENT_ID}"
  CLIENT_UUID="$(require_client)"
}

filter_mapper_id() {
  expected="$1"
  while IFS=, read -r mapper_id mapper_name; do
    if [ "${mapper_name}" = "${expected}" ]; then
      printf '%s\n' "${mapper_id}"
    fi
  done
}

mapper_uuid_optional() {
  mapper_name="$1"
  rows="$(kget "clients/${CLIENT_UUID}/protocol-mappers/models" \
    --fields id,name --format csv --noquotes | \
    filter_mapper_id "${mapper_name}" | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate mapper ${mapper_name}"
  printf '%s' "${rows}"
}

upsert_audience_mapper() {
  mapper_name="${MAPPER_NAME}"
  mapper_uuid="$(mapper_uuid_optional "${mapper_name}")"
  endpoint="clients/${CLIENT_UUID}/protocol-mappers/models"
  action=create
  if [ -n "${mapper_uuid}" ]; then
    endpoint="${endpoint}/${mapper_uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "name=${mapper_name}" \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s "config.\"included.custom.audience\"=${AGENTGATEWAY_AUDIENCE}" \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' >/dev/null 2>&1 || \
    fail "failed to reconcile audience mapper"
}

role_exists() {
  kget "roles/${ROLE_NAME}" --fields id >/dev/null 2>&1
}

ensure_role() {
  if ! role_exists; then
    "${KCADM}" create roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "name=${ROLE_NAME}" \
      -s "description=${ROLE_DESCRIPTION}" \
      -s composite=false >/dev/null 2>&1 || fail "failed to create ${ROLE_NAME}"
  fi
  verify_role
}

verify_role() {
  role_exists || fail "${ROLE_NAME} is missing"
  composite="$(kget "roles/${ROLE_NAME}" --fields composite --format csv --noquotes | nonempty_lines)"
  [ "${composite}" = "false" ] || fail "${ROLE_NAME} must remain non-composite"
}

role_scope_has_direct_role() {
  kget "clients/${CLIENT_UUID}/scope-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${ROLE_NAME}"
}

ensure_role_scope_mapping() {
  if ! role_scope_has_direct_role; then
    role_id="$(kget "roles/${ROLE_NAME}" --fields id --format csv --noquotes | nonempty_lines)"
    [ -n "${role_id}" ] || fail "${ROLE_NAME} id is empty"
    role_body="$(printf '[{"id":"%s","name":"%s"}]' "${role_id}" "${ROLE_NAME}")"
    "${KCADM}" create "clients/${CLIENT_UUID}/scope-mappings/realm" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" -b "${role_body}" >/dev/null 2>&1 || \
      fail "failed to map ${ROLE_NAME} into the client role scope"
    unset role_body role_id
  fi
  role_scope_has_direct_role || fail "client role scope is missing ${ROLE_NAME}"
}

resolve_service_account() {
  SERVICE_ACCOUNT_ID="$(kget "clients/${CLIENT_UUID}/service-account-user" \
    --fields id --format csv --noquotes | nonempty_lines)"
  SERVICE_ACCOUNT_USERNAME="$(kget "clients/${CLIENT_UUID}/service-account-user" \
    --fields username --format csv --noquotes | nonempty_lines)"
  [ -n "${SERVICE_ACCOUNT_ID}" ] || fail "service account id is empty"
  [ "${SERVICE_ACCOUNT_USERNAME}" = "service-account-${CLIENT_ID}" ] || \
    fail "unexpected service account username"
}

target_has_direct_role() {
  kget "users/${SERVICE_ACCOUNT_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${ROLE_NAME}"
}

assert_exclusive_role_mapping() {
  # Keycloak exposes bounded role-member endpoints. They provide the same
  # exclusivity evidence without starting one kcadm JVM for every realm user
  # and service account, which exceeded the PostSync deadline in production.
  # At most one user and zero groups are allowed, so fetching two is sufficient
  # to detect every policy violation while keeping reconciliation O(1).
  users="$(kget "roles/${ROLE_NAME}/users" -q first=0 -q max=2 \
    --fields username --format csv --noquotes | nonempty_lines)"
  groups="$(kget "roles/${ROLE_NAME}/groups" -q first=0 -q max=2 \
    --fields path --format csv --noquotes | nonempty_lines)"
  [ -z "${groups}" ] || fail "${ROLE_NAME} is mapped to a group"
  if [ -n "${users}" ]; then
    while IFS= read -r username; do
      [ "${username}" = "${SERVICE_ACCOUNT_USERNAME}" ] || fail "${ROLE_NAME} has an unauthorized user"
    done <<EOF
${users}
EOF
  fi
}

ensure_role_mapping() {
  assert_exclusive_role_mapping
  if ! target_has_direct_role; then
    "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      --uid "${SERVICE_ACCOUNT_ID}" --rolename "${ROLE_NAME}" >/dev/null 2>&1 || \
      fail "failed to map ${ROLE_NAME}"
  fi
  assert_exclusive_role_mapping
}

verify_client() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient false
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled true
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  [ -n "$(mapper_uuid_optional "${MAPPER_NAME}")" ] || fail "audience mapper missing"
  role_scope_has_direct_role || fail "client role scope is missing ${ROLE_NAME}"
  resolve_service_account
  target_has_direct_role || fail "direct realm role missing"
  assert_exclusive_role_mapping
}

mint_claims() {
  "${KCADM}" config credentials \
    --config "${CLIENT_CONFIG}" \
    --server "${KEYCLOAK_URL}" \
    --realm "${REALM}" \
    --client "${CLIENT_ID}" \
    --secret "${CLIENT_SECRET}" >/dev/null 2>&1 || fail "client token mint failed"
  token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${CLIENT_CONFIG}" | head -n1)"
  [ -n "${token}" ] || fail "access token is missing"
  payload="$(printf '%s' "${token}" | cut -d. -f2)"
  unset token
  case $((${#payload} % 4)) in
    0) ;;
    2) payload="${payload}==" ;;
    3) payload="${payload}=" ;;
    *) fail "JWT payload has invalid base64url length" ;;
  esac
  claims="$(printf '%s' "${payload}" | tr '_-' '/+' | base64 -d 2>/dev/null)" || fail "JWT decode failed"
  unset payload
  rm -f "${CLIENT_CONFIG}"
  printf '%s' "${claims}"
}

verify_minted_claims() {
  claims="$(mint_claims)"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${CLIENT_ID}"'"' || \
    fail "minted token has wrong azp"
  printf '%s' "${claims}" | grep -Fq "${AGENTGATEWAY_AUDIENCE}" || fail "audience missing"
  printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"'"${ROLE_NAME}"'"' || \
    fail "dedicated realm role missing"
  if printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"agentgateway-write"'; then
    fail "minted token contains forbidden realm role"
  fi
  unset claims
}

rollback_identity() {
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to delete ${CLIENT_ID}"
  fi
  if role_exists; then
    users="$(kget "roles/${ROLE_NAME}/users" --fields username --format csv --noquotes | nonempty_lines)"
    groups="$(kget "roles/${ROLE_NAME}/groups" --fields path --format csv --noquotes | nonempty_lines)"
    [ -z "${users}${groups}" ] || fail "role still has mappings after client deletion"
    "${KCADM}" delete "roles/${ROLE_NAME}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to delete ${ROLE_NAME}"
  fi
  printf '{"client_id":"%s","realm_role":"%s","present":false}\n' "${CLIENT_ID}" "${ROLE_NAME}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    upsert_client
    progress client-reconciled
    upsert_audience_mapper
    ensure_role
    ensure_role_scope_mapping
    progress role-scope-verified
    resolve_service_account
    ensure_role_mapping
    progress role-mapping-verified
    verify_client
    verify_minted_claims
    printf '{"client_id":"%s","realm_role":"%s","present":true,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAME}"
    ;;
  audit)
    verify_role
    verify_client
    verify_minted_claims
    printf '{"client_id":"%s","realm_role":"%s","present":true,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAME}"
    ;;
  rollback)
    rollback_identity
    ;;
esac
