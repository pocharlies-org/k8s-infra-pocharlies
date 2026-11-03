#!/bin/sh
set -eu

umask 077

# SC-4304 S6 (security ruling of 03-11-2026): the dedicated PUBLIC PKCE client
# of the Open WebUI connection to /chat-hindsight-personal, the chat twin of
# /hindsight-personal (bank `personal`: Dani's and Leila's personal memory,
# and nobody else — decision of Dani of 03-11-2026).
#
# Why a dedicated client and not the shared agentgateway-chat-mcp (option B of
# the ruling): agentgateway-chat-mcp is shared by every /chat-* route and its
# realm scope is exactly `agentgateway-write`; mapping the personal role into
# it would widen the token surface of every chat route at once. This client is
# the agentgateway-social-mcp pattern (a pre-registered public client the
# gateway short-circuits MCP DCR against) plus the explicit realm scope of
# agentgateway-chat-mcp-client.sh: fullScopeAllowed=false and a scope mapping
# of EXACTLY one role, so Keycloak 26 can emit agentgateway-read:hindsight-
# personal in this client's tokens for no other role and for no user who does
# not already hold it (UserRealmRoleMappingMapper -> RoleResolveUtil; measured
# by security in nota-security-c2-token.md). The role itself is owned by the
# catalog (ROLES.yaml, created by security in SC-4051) and granted by
# agentgateway-hindsight-personal-grants.sh (wave 25): this reconciler never
# creates a role and never grants one to anyone — a scope mapping grants
# nothing, it only makes the role emittable by this client.
#
# Division of ownership:
#   * the gateway route names this clientId (k8s-agentgateway-pocharlies,
#     route chat-hindsight-personal; the Open WebUI connection id
#     `hindsight-personal` derives the exact callback below);
#   * the holder set of the role is owned by
#     agentgateway-hindsight-personal-grants.sh;
#   * the catalog declarations (ROLES.yaml grantees, PRINCIPALS.md,
#     ROUTE-ROLES.md row) travel in the same PR (SC-4414).

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-agentgateway-chat-hindsight-mcp}"
# Space-separated exact redirect URIs (no wildcards). Open WebUI derives the
# callback from the connection id (`hindsight-personal`); extending the list
# is an additive token, never a wildcard.
REDIRECT_URIS="${REDIRECT_URIS:-https://chat.e-dani.com/oauth/clients/mcp:hindsight-personal/callback}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
PKCE_METHOD="${PKCE_METHOD:-S256}"
# Space-separated exact realm roles this client maps into its realm scope.
# The gateway's route gate on /chat-hindsight-personal requires exactly
# `agentgateway-read:hindsight-personal` in jwt.realm_access.roles. The role
# itself lives in the catalog (ROLES.yaml) and is granted by
# agentgateway-hindsight-personal-grants.sh: this reconciler never creates,
# deletes or widens a realm role, and it never grants one to a user. Keep the
# list sorted; the pin below is order-sensitive.
REALM_SCOPE_ROLE_NAMES="${REALM_SCOPE_ROLE_NAMES:-agentgateway-read:hindsight-personal}"
EXPECTED_REALM_SCOPE_ROLE_NAMES="agentgateway-read:hindsight-personal"
RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-agentgateway-chat-hindsight-admin.config

. "${0%/*}/kc-admin-common.sh"

# The bootstrap comes from kc-admin-common.sh and the mechanical helpers from
# the shared reconcile library (INFRA-477); this script keeps its own
# upsert_audience_mapper below, which overrides the library one: this PUBLIC
# client also pins userinfo.token.claim=false.
. "${0%/*}/keycloak-reconcile-lib.sh"

# Immutable identity of this reconciler: a PUBLIC PKCE browser client only.
# It carries no secret and no service account; it exists so the gateway can
# short-circuit MCP DCR against a pre-registered public client and Open WebUI
# can run the authorization-code + PKCE flow on /chat-hindsight-personal. Its
# tokens carry ONLY the realm roles explicitly mapped into its realm scope
# below — today exactly agentgateway-read:hindsight-personal. fullScopeAllowed
# stays false, so a role outside this reviewed set can never reach this
# client's tokens for any user. Pinning these keeps a future edit from
# silently widening a browser client into a confidential or direct-grant one.
[ "${CLIENT_ID}" = "agentgateway-chat-hindsight-mcp" ] || fail "CLIENT_ID is immutable"
[ "${REALM}" = "edani" ] || fail "REALM is immutable"
[ "${MAPPER_NAME}" = "aud-mcp" ] || fail "MAPPER_NAME is immutable"
[ "${PKCE_METHOD}" = "S256" ] || fail "PKCE_METHOD is immutable"
[ "${REALM_SCOPE_ROLE_NAMES}" = "${EXPECTED_REALM_SCOPE_ROLE_NAMES}" ] || \
  fail "REALM_SCOPE_ROLE_NAMES is immutable; review this reconciler and the gateway route gate together"
[ "${RECONCILE_CONTRACT_VERSION}" = "1" ] || fail "unsupported reconcile contract version"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "unsupported MODE=${MODE}" ;;
esac
# Every URI must be an exact https chat.e-dani.com callback: reject wildcards
# and anything that would widen the client beyond its own app origin.
for uri in ${REDIRECT_URIS}; do
  case "${uri}" in
    *\**) fail "REDIRECT_URIS contains a wildcard URI: ${uri}" ;;
    https://chat.e-dani.com/oauth/clients/mcp:*/callback) ;;
    *) fail "REDIRECT_URIS contains a non-exact or foreign URI: ${uri}" ;;
  esac
done

redirect_uris_json() {
  # JSON array of the exact URIs, from the space-separated list.
  first=1
  out='['
  for uri in ${REDIRECT_URIS}; do
    if [ "${first}" -eq 1 ]; then first=0; else out="${out},"; fi
    out="${out}\"${uri}\""
  done
  printf '%s]' "${out}"
}

upsert_client() {
  uuid="$(resolve_client_optional)"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  # publicClient=true and no secret: the browser holds no secret and the
  # gateway short-circuits MCP DCR to this pre-registered client. The flow is
  # authorization-code + PKCE only, so direct access, implicit and service
  # accounts stay off. fullScopeAllowed stays false: this client emits realm
  # roles only through the explicit, reviewed scope mapping reconciled below.
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=true \
    -s standardFlowEnabled=true \
    -s directAccessGrantsEnabled=false \
    -s implicitFlowEnabled=false \
    -s serviceAccountsEnabled=false \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s "redirectUris=$(redirect_uris_json)" \
    -s "attributes.\"pkce.code.challenge.method\"=${PKCE_METHOD}" >/dev/null 2>&1 || \
    fail "failed to reconcile ${CLIENT_ID}"
  CLIENT_UUID="$(require_client)"
}

# Overrides the library upsert_audience_mapper: this public browser client
# also pins userinfo.token.claim=false (house pattern verified on
# agentgateway-social-mcp), which the shared helper does not carry.
upsert_audience_mapper() {
  mapper_uuid="$(mapper_uuid_optional)"
  endpoint="clients/${CLIENT_UUID}/protocol-mappers/models"
  action=create
  if [ -n "${mapper_uuid}" ]; then
    endpoint="${endpoint}/${mapper_uuid}"
    action=update
  fi
  # House audience-mapper pattern (verified on agentgateway-social-mcp): the MCP
  # resource audience lands in access and introspection tokens only, never in
  # the id token or userinfo.
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "name=${MAPPER_NAME}" \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s "config.\"included.custom.audience\"=${AGENTGATEWAY_AUDIENCE}" \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' \
    -s 'config."userinfo.token.claim"=false' >/dev/null 2>&1 || \
    fail "failed to reconcile audience mapper"
}

verify_realm_roles() {
  # The role is owned by the catalog (created by security in SC-4051, declared
  # in ROLES.yaml); a missing role means the catalog moved out from under this
  # client: fail loud, never create the role from this hook.
  for role in ${REALM_SCOPE_ROLE_NAMES}; do
    role_exists "${role}" || fail "${role} is missing from realm ${REALM}: owned by the catalog, refusing to create it here"
  done
}

ensure_realm_scope_mapping() {
  # House pattern (chat-agentgateway-client.sh, agentgateway-read-grants.sh):
  # one explicit role per scope-mappings/realm entry, created only when absent
  # and re-read after to fail loud. With fullScopeAllowed=false, Keycloak 26
  # emits in the token only the realm roles that are BOTH in this client's
  # realm scope mapping AND actually held by the user. The mapping itself
  # grants no role to anyone.
  for role in ${REALM_SCOPE_ROLE_NAMES}; do
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

scope_names() {
  kget "clients/${CLIENT_UUID}/scope-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | sort | tr '\n' ',' | sed 's/,$//'
}

verify_client() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient true
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled true
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled false
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  redirect="$(client_field "${CLIENT_UUID}" redirectUris)"
  for uri in ${REDIRECT_URIS}; do
    printf '%s' "${redirect}" | grep -Fq "${uri}" || \
      fail "client redirect URI ${uri} is missing"
  done
  # kcadm serializes map fields like `attributes` EMPTY when they are selected
  # through the field filter (measured 2026-09-21, INFRA-197: selecting the
  # attributes map returns {"attributes": {}} while the attribute is set on the
  # server); the full JSON representation does serialize the map. So the PKCE
  # check reads the client WITHOUT a field filter. Match key and value paired
  # so an S256 living in any other attribute cannot satisfy the check.
  attrs="$(kget "clients/${CLIENT_UUID}" --format json)"
  printf '%s' "${attrs}" | grep -Eq \
    "\"pkce\.code\.challenge\.method\"[[:space:]]*:[[:space:]]*\"${PKCE_METHOD}\"" || \
    fail "client PKCE challenge method is missing"
  [ -n "$(mapper_uuid_optional)" ] || fail "audience mapper missing"
  # EXACT scope comparison, never a subset (agentgateway-read-grants precedent):
  # a role slipped into this client's scope would become emittable for every
  # holder of it and the isolation this client exists for would be gone.
  actual="$(scope_names)"
  [ "${actual}" = "${REALM_SCOPE_ROLE_NAMES}" ] || \
    fail "client realm scope mapping must be exactly ${REALM_SCOPE_ROLE_NAMES}, found [${actual}]"
}

rollback_identity() {
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to delete ${CLIENT_ID}"
  fi
  printf '{"client_id":"%s","present":false}\n' "${CLIENT_ID}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    upsert_client
    progress client-reconciled
    upsert_audience_mapper
    progress mapper-reconciled
    verify_realm_roles
    ensure_realm_scope_mapping
    progress scope-reconciled
    verify_client
    printf '{"client_id":"%s","present":true,"public_client":true,"pkce":"%s"}\n' \
      "${CLIENT_ID}" "${PKCE_METHOD}"
    ;;
  audit)
    verify_client
    printf '{"client_id":"%s","present":true,"public_client":true,"pkce":"%s"}\n' \
      "${CLIENT_ID}" "${PKCE_METHOD}"
    ;;
  rollback)
    rollback_identity
    ;;
esac
