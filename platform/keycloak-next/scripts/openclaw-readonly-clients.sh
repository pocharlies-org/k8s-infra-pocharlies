#!/bin/sh
set -eu

umask 077

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
UI_CLIENT_ID="${UI_CLIENT_ID:-openclaw-readonly-ui}"
AGENTGATEWAY_CLIENT_ID="${AGENTGATEWAY_CLIENT_ID:-openclaw-readonly-agentgateway}"
UI_REDIRECT_URI="${UI_REDIRECT_URI:-https://openclaw-k8s-readonly.e-dani.com/oauth2/callback}"
UI_PUBLIC_ORIGIN="${UI_PUBLIC_ORIGIN:-https://openclaw-k8s-readonly.e-dani.com}"
UI_LAN_ORIGIN="${UI_LAN_ORIGIN:-https://openclaw-k8s-readonly.lan.e-dani.com}"
OPERATOR_EMAIL="${OPERATOR_EMAIL:-info@e-dani.com}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
FORBIDDEN_REALM_ROLE="${FORBIDDEN_REALM_ROLE:-agentgateway-write}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-openclaw-readonly-admin.config
CLIENT_CONFIG=/tmp/kcadm-openclaw-readonly-client.config

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[ "${UI_CLIENT_ID}" = "openclaw-readonly-ui" ] || fail "UI_CLIENT_ID is immutable"
[ "${AGENTGATEWAY_CLIENT_ID}" = "openclaw-readonly-agentgateway" ] || fail "AGENTGATEWAY_CLIENT_ID is immutable"
[ "${OPERATOR_EMAIL}" = "info@e-dani.com" ] || fail "OPERATOR_EMAIL is immutable"
[ "${FORBIDDEN_REALM_ROLE}" = "agentgateway-write" ] || fail "FORBIDDEN_REALM_ROLE is immutable"
case "${MODE}" in
  ensure|audit)
    [ -n "${OPENCLAW_READONLY_UI_CLIENT_SECRET:-}" ] || fail "UI client secret is empty"
    [ -n "${OPENCLAW_READONLY_AGENTGATEWAY_CLIENT_SECRET:-}" ] || fail "AgentGateway client secret is empty"
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
  client_id="$1"
  rows="$(kget clients -q "clientId=${client_id}" --fields id --format csv --noquotes | nonempty_lines)"
  count="$(printf '%s\n' "${rows}" | line_count)"
  [ "${count}" -le 1 ] || fail "duplicate Keycloak client ${client_id}"
  printf '%s' "${rows}"
}

require_client() {
  client_id="$1"
  uuid="$(resolve_client_optional "${client_id}")"
  [ -n "${uuid}" ] || fail "Keycloak client ${client_id} is missing"
  printf '%s' "${uuid}"
}

client_field() {
  uuid="$1"
  field="$2"
  kget "clients/${uuid}" --fields "${field}" --format csv --noquotes | nonempty_lines
}

assert_client_boolean() {
  uuid="$1"
  field="$2"
  expected="$3"
  actual="$(client_field "${uuid}" "${field}")"
  [ "${actual}" = "${expected}" ] || fail "client field ${field} expected ${expected}"
}

upsert_ui_client() {
  uuid="$(resolve_client_optional "${UI_CLIENT_ID}")"
  if [ -z "${uuid}" ]; then
    "${KCADM}" create clients --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "clientId=${UI_CLIENT_ID}" \
      -s enabled=true \
      -s publicClient=false \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=false \
      -s serviceAccountsEnabled=false \
      -s fullScopeAllowed=false \
      -s protocol=openid-connect \
      -s "rootUrl=${UI_PUBLIC_ORIGIN}" \
      -s "baseUrl=${UI_PUBLIC_ORIGIN}" \
      -s "redirectUris=[\"${UI_REDIRECT_URI}\"]" \
      -s "webOrigins=[\"${UI_PUBLIC_ORIGIN}\",\"${UI_LAN_ORIGIN}\"]" \
      -s "secret=${OPENCLAW_READONLY_UI_CLIENT_SECRET}" >/dev/null 2>&1 || \
      fail "failed to create UI client"
    uuid="$(require_client "${UI_CLIENT_ID}")"
  else
    "${KCADM}" update "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s enabled=true \
      -s publicClient=false \
      -s standardFlowEnabled=true \
      -s directAccessGrantsEnabled=false \
      -s serviceAccountsEnabled=false \
      -s fullScopeAllowed=false \
      -s protocol=openid-connect \
      -s "rootUrl=${UI_PUBLIC_ORIGIN}" \
      -s "baseUrl=${UI_PUBLIC_ORIGIN}" \
      -s "redirectUris=[\"${UI_REDIRECT_URI}\"]" \
      -s "webOrigins=[\"${UI_PUBLIC_ORIGIN}\",\"${UI_LAN_ORIGIN}\"]" \
      -s "secret=${OPENCLAW_READONLY_UI_CLIENT_SECRET}" >/dev/null 2>&1 || \
      fail "failed to update UI client"
  fi
  UI_CLIENT_UUID="${uuid}"
}

upsert_agentgateway_client() {
  uuid="$(resolve_client_optional "${AGENTGATEWAY_CLIENT_ID}")"
  if [ -z "${uuid}" ]; then
    "${KCADM}" create clients --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "clientId=${AGENTGATEWAY_CLIENT_ID}" \
      -s enabled=true \
      -s publicClient=false \
      -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false \
      -s serviceAccountsEnabled=true \
      -s fullScopeAllowed=false \
      -s protocol=openid-connect \
      -s "secret=${OPENCLAW_READONLY_AGENTGATEWAY_CLIENT_SECRET}" >/dev/null 2>&1 || \
      fail "failed to create AgentGateway client"
    uuid="$(require_client "${AGENTGATEWAY_CLIENT_ID}")"
  else
    "${KCADM}" update "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s enabled=true \
      -s publicClient=false \
      -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false \
      -s serviceAccountsEnabled=true \
      -s fullScopeAllowed=false \
      -s protocol=openid-connect \
      -s "secret=${OPENCLAW_READONLY_AGENTGATEWAY_CLIENT_SECRET}" >/dev/null 2>&1 || \
      fail "failed to update AgentGateway client"
  fi
  AGENTGATEWAY_CLIENT_UUID="${uuid}"
}

mapper_uuid_optional() {
  client_uuid="$1"
  mapper_name="$2"
  rows="$(kget "clients/${client_uuid}/protocol-mappers/models" \
    --fields id,name --format csv --noquotes | \
    awk -F, -v expected="${mapper_name}" '$2 == expected {print $1}' | nonempty_lines)"
  count="$(printf '%s\n' "${rows}" | line_count)"
  [ "${count}" -le 1 ] || fail "duplicate protocol mapper ${mapper_name}"
  printf '%s' "${rows}"
}

upsert_groups_mapper() {
  uuid="$(mapper_uuid_optional "${UI_CLIENT_UUID}" openclaw-readonly-groups)"
  endpoint="clients/${UI_CLIENT_UUID}/protocol-mappers/models"
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="${endpoint}/${uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s name=openclaw-readonly-groups \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-group-membership-mapper \
    -s 'config."claim.name"=groups' \
    -s 'config."full.path"=true' \
    -s 'config."id.token.claim"=true' \
    -s 'config."access.token.claim"=true' \
    -s 'config."userinfo.token.claim"=true' \
    -s 'config."introspection.token.claim"=true' >/dev/null 2>&1 || \
    fail "failed to reconcile UI groups mapper"
}

upsert_audience_mapper() {
  uuid="$(mapper_uuid_optional "${AGENTGATEWAY_CLIENT_UUID}" openclaw-readonly-agentgateway-audience)"
  endpoint="clients/${AGENTGATEWAY_CLIENT_UUID}/protocol-mappers/models"
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="${endpoint}/${uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s name=openclaw-readonly-agentgateway-audience \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s "config.\"included.custom.audience\"=${AGENTGATEWAY_AUDIENCE}" \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' >/dev/null 2>&1 || \
    fail "failed to reconcile AgentGateway audience mapper"
}

assert_no_forbidden_role() {
  user_id="$1"
  if kget "users/${user_id}/role-mappings/realm/composite" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${FORBIDDEN_REALM_ROLE}"; then
    fail "${FORBIDDEN_REALM_ROLE} is effective for a read-only identity"
  fi
}

verify_operator_user() {
  rows="$(kget users -q "email=${OPERATOR_EMAIL}" -q exact=true \
    --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" = "1" ] || \
    fail "expected exactly one Keycloak user for ${OPERATOR_EMAIL}"
  OPERATOR_USER_ID="${rows}"
  enabled="$(kget "users/${OPERATOR_USER_ID}" --fields enabled --format csv --noquotes | nonempty_lines)"
  [ "${enabled}" = "true" ] || fail "operator user is disabled"
  assert_no_forbidden_role "${OPERATOR_USER_ID}"
}

verify_clients() {
  UI_CLIENT_UUID="$(require_client "${UI_CLIENT_ID}")"
  AGENTGATEWAY_CLIENT_UUID="$(require_client "${AGENTGATEWAY_CLIENT_ID}")"

  assert_client_boolean "${UI_CLIENT_UUID}" enabled true
  assert_client_boolean "${UI_CLIENT_UUID}" publicClient false
  assert_client_boolean "${UI_CLIENT_UUID}" standardFlowEnabled true
  assert_client_boolean "${UI_CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${UI_CLIENT_UUID}" serviceAccountsEnabled false
  assert_client_boolean "${UI_CLIENT_UUID}" fullScopeAllowed false

  assert_client_boolean "${AGENTGATEWAY_CLIENT_UUID}" enabled true
  assert_client_boolean "${AGENTGATEWAY_CLIENT_UUID}" publicClient false
  assert_client_boolean "${AGENTGATEWAY_CLIENT_UUID}" standardFlowEnabled false
  assert_client_boolean "${AGENTGATEWAY_CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${AGENTGATEWAY_CLIENT_UUID}" serviceAccountsEnabled true
  assert_client_boolean "${AGENTGATEWAY_CLIENT_UUID}" fullScopeAllowed false

  [ -n "$(mapper_uuid_optional "${UI_CLIENT_UUID}" openclaw-readonly-groups)" ] || \
    fail "UI groups mapper is missing"
  [ -n "$(mapper_uuid_optional "${AGENTGATEWAY_CLIENT_UUID}" openclaw-readonly-agentgateway-audience)" ] || \
    fail "AgentGateway audience mapper is missing"

  service_user_id="$(kget "clients/${AGENTGATEWAY_CLIENT_UUID}/service-account-user" \
    --fields id --format csv --noquotes | nonempty_lines)"
  [ -n "${service_user_id}" ] || fail "AgentGateway service account is missing"
  assert_no_forbidden_role "${service_user_id}"
  verify_operator_user
}

mint_readonly_claims() {
  "${KCADM}" config credentials \
    --config "${CLIENT_CONFIG}" \
    --server "${KEYCLOAK_URL}" \
    --realm "${REALM}" \
    --client "${AGENTGATEWAY_CLIENT_ID}" \
    --secret "${OPENCLAW_READONLY_AGENTGATEWAY_CLIENT_SECRET}" >/dev/null 2>&1 || \
    fail "read-only client_credentials token mint failed"
  token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${CLIENT_CONFIG}" | head -n1)"
  [ -n "${token}" ] || fail "kcadm did not persist an access token"
  payload="$(printf '%s' "${token}" | cut -d. -f2)"
  unset token
  case $((${#payload} % 4)) in
    0) ;;
    2) payload="${payload}==" ;;
    3) payload="${payload}=" ;;
    *) fail "JWT payload has invalid base64url length" ;;
  esac
  claims="$(printf '%s' "${payload}" | tr '_-' '/+' | base64 -d 2>/dev/null)" || \
    fail "JWT payload decode failed"
  unset payload
  rm -f "${CLIENT_CONFIG}"
  printf '%s' "${claims}"
}

verify_minted_claims() {
  claims="$(mint_readonly_claims)"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"openclaw-readonly-agentgateway"' || \
    fail "minted token has the wrong authorized party"
  printf '%s' "${claims}" | grep -Fq "${AGENTGATEWAY_AUDIENCE}" || \
    fail "minted token is missing AgentGateway audience"
  if printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"agentgateway-write"'; then
    fail "minted read-only token contains ${FORBIDDEN_REALM_ROLE}"
  fi
  unset claims
}

delete_dedicated_client() {
  client_id="$1"
  uuid="$(resolve_client_optional "${client_id}")"
  [ -z "${uuid}" ] && return 0
  "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
    fail "failed to delete dedicated client ${client_id}"
}

assert_dedicated_client_absent() {
  client_id="$1"
  [ -z "$(resolve_client_optional "${client_id}")" ] || \
    fail "dedicated client ${client_id} remains after rollback"
}

login_admin

case "${MODE}" in
  ensure)
    upsert_ui_client
    upsert_agentgateway_client
    upsert_groups_mapper
    upsert_audience_mapper
    verify_clients
    verify_minted_claims
    printf '{"ui_client":"%s","agentgateway_client":"%s","operator_email":"%s","write_role_present":false}\n' \
      "${UI_CLIENT_ID}" "${AGENTGATEWAY_CLIENT_ID}" "${OPERATOR_EMAIL}"
    ;;
  audit)
    verify_clients
    verify_minted_claims
    printf '{"ui_client":"%s","agentgateway_client":"%s","operator_email":"%s","write_role_present":false}\n' \
      "${UI_CLIENT_ID}" "${AGENTGATEWAY_CLIENT_ID}" "${OPERATOR_EMAIL}"
    ;;
  rollback)
    # Recovery must not depend on either application secret, a mintable token,
    # the operator user remaining enabled, or the client still being safely
    # configured. Delete the two immutable dedicated IDs with the admin API;
    # this also contains an accidental forbidden-role grant.
    delete_dedicated_client "${AGENTGATEWAY_CLIENT_ID}"
    delete_dedicated_client "${UI_CLIENT_ID}"
    assert_dedicated_client_absent "${AGENTGATEWAY_CLIENT_ID}"
    assert_dedicated_client_absent "${UI_CLIENT_ID}"
    printf '{"ui_client":"%s","agentgateway_client":"%s","present":false}\n' \
      "${UI_CLIENT_ID}" "${AGENTGATEWAY_CLIENT_ID}"
    ;;
esac
