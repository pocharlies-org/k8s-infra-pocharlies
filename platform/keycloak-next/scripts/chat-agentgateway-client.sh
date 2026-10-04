#!/bin/sh
set -eu

umask 077

# Dedicated confidential client for the chat surface (Open WebUI at
# chat.e-dani.com) to reach AgentGateway through its auth-proxy sidecar.
# It holds the REVIEWED SET of domain roles below and nothing else from the
# agentgateway-write family — never the legacy umbrella role — plus the one
# shared route role agentgateway-read:studio. Every role is CREATED elsewhere
# (agentgateway-domain-roles.sh, sync-wave 19, for the write domains;
# agentgateway-read-grants.sh, sync-wave 20, for the read role) and only
# VERIFIED here: this reconciler never creates, deletes or widens a realm role.
#
# 2026-09-17 (contract v2): the set grew from one role to six. The chat moved
# ALL its MCP tool servers onto the sidecar (they used to carry a hand-pasted,
# 30-day token of the umbrella client agentgateway-mcp, which expires
# 2026-09-27 and would have taken every tool down at once). The set is exactly
# the domains the chat already reaches today — media, social, workspace, gsc,
# synapse and the new hermes — so the move loses no capability while dropping
# the umbrella's reach over shopify, picqer, skirmshop-plugins and sauvage.
#
# 2026-09-26 (SC-699): the set grew to seven with agentgateway-read:studio,
# the ROUTE role /studio has required since INFRA-143 (2026-09-19, measured by
# qa: the sidecar's client-credentials token carried only the six write roles
# and initialize on /studio answered 403 authorization failed while /grok
# answered 200). Unlike the six write roles this one is SHARED: the same role
# is held by the agentgateway-mcp and openclaw service accounts, so the
# exclusive-service-account invariant applies to the agentgateway-write family
# only; the holder allowlist of the shared read role is owned by
# agentgateway-read-grants.sh (sync-wave 20), which runs before this hook.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-chat-agentgateway}"
# Space-separated and ORDER-INSENSITIVE for the guard below; keep it sorted.
ROLE_NAMES="${ROLE_NAMES:-agentgateway-read:studio agentgateway-write:gsc agentgateway-write:hermes agentgateway-write:media agentgateway-write:social agentgateway-write:synapse agentgateway-write:workspace}"
EXPECTED_ROLE_NAMES="agentgateway-read:studio agentgateway-write:gsc agentgateway-write:hermes agentgateway-write:media agentgateway-write:social agentgateway-write:synapse agentgateway-write:workspace"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
FORBIDDEN_REALM_ROLE="${FORBIDDEN_REALM_ROLE:-agentgateway-write}"
RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-2}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-chat-agentgateway-admin.config
CLIENT_CONFIG=/tmp/kcadm-chat-agentgateway-client.config

KCADM_TMP_FILES="${CLIENT_CONFIG}"
. "${0%/*}/kc-admin-common.sh"

progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${CLIENT_ID}" "$1"
}

[ "${FORBIDDEN_REALM_ROLE}" = "agentgateway-write" ] || fail "FORBIDDEN_REALM_ROLE is immutable"
[ "${RECONCILE_CONTRACT_VERSION}" = "2" ] || fail "unsupported reconcile contract version"
[ "${ROLE_NAMES}" = "${EXPECTED_ROLE_NAMES}" ] || \
  fail "ROLE_NAMES is immutable; review this reconciler, the domain-role allowlist and the gateway CEL together"
case "${CLIENT_ID}" in
  chat-agentgateway)
    CLIENT_SECRET="${CHAT_AGENTGATEWAY_CLIENT_SECRET:-}"
    MAPPER_NAME=chat-agentgateway-audience
    ;;
  *) fail "unsupported immutable client" ;;
esac
case "${MODE}" in
  ensure|audit)
    [ -n "${CLIENT_SECRET}" ] || fail "client secret is empty"
    ;;
  rollback) ;;
  *) fail "unsupported MODE=${MODE}" ;;
esac

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
  kget "roles/$1" --fields id >/dev/null 2>&1
}

verify_role() {
  # Write-domain roles are owned by agentgateway-domain-roles.sh and the read
  # role by agentgateway-read-grants.sh; a missing role means that hook has
  # not run for this commit, never a reason to create it here.
  role_exists "$1" || fail "$1 is missing; the agentgateway-domain-roles or agentgateway-read-grants hook owns it"
  composite="$(kget "roles/$1" --fields composite --format csv --noquotes | nonempty_lines)"
  [ "${composite}" = "false" ] || fail "$1 must remain non-composite"
}

verify_roles() {
  for role in ${ROLE_NAMES}; do
    verify_role "${role}"
  done
}

role_scope_has_direct_role() {
  kget "clients/${CLIENT_UUID}/scope-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "$1"
}

ensure_role_scope_mapping() {
  for role in ${ROLE_NAMES}; do
    if ! role_scope_has_direct_role "${role}"; then
      role_id="$(kget "roles/${role}" --fields id --format csv --noquotes | nonempty_lines)"
      [ -n "${role_id}" ] || fail "${role} id is empty"
      role_body="$(printf '[{"id":"%s","name":"%s"}]' "${role_id}" "${role}")"
      "${KCADM}" create "clients/${CLIENT_UUID}/scope-mappings/realm" \
        --config "${ADMIN_CONFIG}" -r "${REALM}" -b "${role_body}" >/dev/null 2>&1 || \
        fail "failed to map ${role} into the client role scope"
      unset role_body role_id
    fi
    role_scope_has_direct_role "${role}" || fail "client role scope is missing ${role}"
  done
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

service_account_realm_roles() {
  kget "users/${SERVICE_ACCOUNT_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines
}

target_has_direct_role() {
  service_account_realm_roles | grep -Fxq "$1"
}

assert_reviewed_write_roles() {
  # The chat identity may hold the reviewed domain roles and NOTHING else from
  # the agentgateway-write family: not the legacy umbrella role, not a sibling
  # domain such as agentgateway-write:shopify. Anything outside the set fails.
  held="$(service_account_realm_roles | grep -E '^agentgateway-write' || true)"
  for role in ${held}; do
    case " ${ROLE_NAMES} " in
      *" ${role} "*) ;;
      *) fail "service account holds an unreviewed AgentGateway write role: ${role}" ;;
    esac
  done
  # The completeness check is write-family only: the shared read role is
  # granted by ensure_role_mapping and its presence asserted there and in
  # verify_client, but it never appears in the write-family listing above.
  for role in ${ROLE_NAMES}; do
    case "${role}" in
      agentgateway-write*)
        printf '%s\n' "${held}" | grep -Fxq "${role}" || fail "service account is missing ${role}" ;;
    esac
  done
}

assert_exclusive_role_mapping() {
  # Bounded role-member endpoints: at most one user (our service account) and
  # zero groups are allowed, so fetching two rows detects every violation.
  users="$(kget "roles/$1/users" -q first=0 -q max=2 \
    --fields username --format csv --noquotes | nonempty_lines)"
  groups="$(kget "roles/$1/groups" -q first=0 -q max=2 \
    --fields path --format csv --noquotes | nonempty_lines)"
  [ -z "${groups}" ] || fail "$1 is mapped to a group"
  if [ -n "${users}" ]; then
    while IFS= read -r username; do
      [ "${username}" = "${SERVICE_ACCOUNT_USERNAME}" ] || fail "$1 has an unauthorized user"
    done <<EOF
${users}
EOF
  fi
}

ensure_role_mapping() {
  # TWO passes on purpose: with several roles, checking and granting in the
  # same loop would have already granted the first roles by the time an
  # unauthorized holder is found on a later one. Nothing is mutated until
  # every role is clean. Exclusivity is checked for the agentgateway-write
  # family only: agentgateway-read:studio is a SHARED route role also held by
  # the agentgateway-mcp and openclaw service accounts, and its holder
  # allowlist is owned by agentgateway-read-grants.sh.
  for role in ${ROLE_NAMES}; do
    case "${role}" in
      agentgateway-write*) assert_exclusive_role_mapping "${role}" ;;
    esac
  done
  for role in ${ROLE_NAMES}; do
    if ! target_has_direct_role "${role}"; then
      "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${SERVICE_ACCOUNT_ID}" --rolename "${role}" >/dev/null 2>&1 || \
        fail "failed to map ${role}"
    fi
    case "${role}" in
      agentgateway-write*) assert_exclusive_role_mapping "${role}" ;;
    esac
  done
  assert_reviewed_write_roles
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
  resolve_service_account
  for role in ${ROLE_NAMES}; do
    role_scope_has_direct_role "${role}" || fail "client role scope is missing ${role}"
    target_has_direct_role "${role}" || fail "direct realm role missing: ${role}"
    # Exclusivity is a write-family invariant (shared read role: see
    # ensure_role_mapping).
    case "${role}" in
      agentgateway-write*) assert_exclusive_role_mapping "${role}" ;;
    esac
  done
  assert_reviewed_write_roles
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
  for role in ${ROLE_NAMES}; do
    printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"'"${role}"'"' || \
      fail "dedicated realm role missing in the minted token: ${role}"
  done
  if printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"agentgateway-write"'; then
    fail "minted token contains forbidden realm role"
  fi
  unset claims
}

rollback_identity() {
  # Deleting the client removes its service account and therefore the only
  # reviewed grant of the domain role. The role itself is retained: it is
  # owned by agentgateway-domain-roles.sh and referenced by the gateway CEL.
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to delete ${CLIENT_ID}"
  fi
  [ -z "$(resolve_client_optional)" ] || fail "client ${CLIENT_ID} remains after rollback"
  # Write-family roles only: deleting the client removes its service account,
  # the only reviewed holder of each write domain. The shared read role stays
  # in the realm WITH its other reviewed holders (agentgateway-mcp, openclaw)
  # — asserting emptiness there would fail by design.
  for role in ${ROLE_NAMES}; do
    case "${role}" in
      agentgateway-write*)
        if role_exists "${role}"; then
          users="$(kget "roles/${role}/users" --fields username --format csv --noquotes | nonempty_lines)"
          groups="$(kget "roles/${role}/groups" --fields path --format csv --noquotes | nonempty_lines)"
          [ -z "${users}${groups}" ] || fail "${role} still has mappings after client deletion"
        fi ;;
    esac
  done
  printf '{"client_id":"%s","realm_roles":"%s","client_present":false,"roles_retained":true}\n' \
    "${CLIENT_ID}" "${ROLE_NAMES}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    verify_roles
    upsert_client
    progress client-reconciled
    upsert_audience_mapper
    ensure_role_scope_mapping
    progress role-scope-verified
    resolve_service_account
    ensure_role_mapping
    progress role-mapping-verified
    verify_client
    verify_minted_claims
    printf '{"client_id":"%s","realm_roles":"%s","present":true,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAMES}"
    ;;
  audit)
    verify_roles
    verify_client
    verify_minted_claims
    printf '{"client_id":"%s","realm_roles":"%s","present":true,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAMES}"
    ;;
  rollback)
    rollback_identity
    ;;
esac
