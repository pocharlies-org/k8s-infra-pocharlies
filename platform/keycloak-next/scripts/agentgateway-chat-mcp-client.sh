#!/bin/sh
set -eu

umask 077

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-agentgateway-chat-mcp}"
# Space-separated exact redirect URIs (no wildcards). Open WebUI derives the
# callback from the connection id; OWU-29 registers the chat-atlassian
# connection. Extending the list is an additive token, never a wildcard.
REDIRECT_URIS="${REDIRECT_URIS:-https://chat.e-dani.com/oauth/clients/mcp:chat-atlassian/callback}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
PKCE_METHOD="${PKCE_METHOD:-S256}"
# Space-separated exact realm roles this client maps into its realm scope.
# The gateway's write rules on /chat-atlassian require exactly
# `agentgateway-write` in jwt.realm_access.roles. The role itself is CREATED
# by agentgateway-write-role.sh and only VERIFIED here: this reconciler never
# creates, deletes or widens a realm role, and it never grants one to a user
# (holder management belongs to agentgateway-write-role.sh and
# agentgateway-write-grant-daniel.sh). Keep the list sorted; the pin below is
# order-sensitive.
REALM_SCOPE_ROLE_NAMES="${REALM_SCOPE_ROLE_NAMES:-agentgateway-write}"
EXPECTED_REALM_SCOPE_ROLE_NAMES="agentgateway-write"
RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-agentgateway-chat-admin.config

cleanup() {
  rm -f "${ADMIN_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${CLIENT_ID}" "$1"
}

# Immutable identity of this reconciler: a PUBLIC PKCE browser client only.
# It carries no secret and no service account; it exists so the gateway can
# short-circuit MCP DCR against a pre-registered public client and Open WebUI
# can run the authorization-code + PKCE flow on every /chat-* route that names
# it. Its tokens carry ONLY the realm roles explicitly mapped into its realm
# scope below — today exactly `agentgateway-write`, the role the gateway's
# write rules on /chat-atlassian read out of jwt.realm_access.roles (OWU-28
# C2; security note nota-security-c2-token.md, 2026-09-25). fullScopeAllowed
# stays false, so a role outside this reviewed set can never reach this
# client's tokens for any user, and mapping a role grants it to nobody — it
# only becomes emittable by this client for users who already hold it.
# Pinning these keeps a future edit from silently widening a browser client
# into a confidential or direct-grant one.
[ "${CLIENT_ID}" = "agentgateway-chat-mcp" ] || fail "CLIENT_ID is immutable"
[ "${REALM}" = "edani" ] || fail "REALM is immutable"
[ "${MAPPER_NAME}" = "aud-mcp" ] || fail "MAPPER_NAME is immutable"
[ "${PKCE_METHOD}" = "S256" ] || fail "PKCE_METHOD is immutable"
[ "${REALM_SCOPE_ROLE_NAMES}" = "${EXPECTED_REALM_SCOPE_ROLE_NAMES}" ] || \
  fail "REALM_SCOPE_ROLE_NAMES is immutable; review this reconciler and the gateway write rules together"
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
  # roles only through the explicit, reviewed scope mapping reconciled below
  # (today exactly agentgateway-write), never the whole realm.
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

filter_mapper_id() {
  expected="$1"
  while IFS=, read -r mapper_id mapper_name; do
    if [ "${mapper_name}" = "${expected}" ]; then
      printf '%s\n' "${mapper_id}"
    fi
  done
}

mapper_uuid_optional() {
  rows="$(kget "clients/${CLIENT_UUID}/protocol-mappers/models" \
    --fields id,name --format csv --noquotes | \
    filter_mapper_id "${MAPPER_NAME}" | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate mapper ${MAPPER_NAME}"
  printf '%s' "${rows}"
}

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

role_exists() {
  kget "roles/$1" --fields id >/dev/null 2>&1
}

verify_realm_roles() {
  # The realm role is owned by agentgateway-write-role.sh; a missing role
  # means that hook has not run for this commit, never a reason to create it.
  for role in ${REALM_SCOPE_ROLE_NAMES}; do
    role_exists "${role}" || fail "${role} is missing; the agentgateway-write-role hook owns it"
  done
}

role_scope_has_direct_role() {
  kget "clients/${CLIENT_UUID}/scope-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "$1"
}

ensure_realm_scope_mapping() {
  # House pattern (chat-agentgateway-client.sh, agentgateway-read-grants.sh):
  # one explicit role per scope-mappings/realm entry, created only when absent
  # and re-read after to fail loud. With fullScopeAllowed=false, Keycloak 26
  # emits in the token only the realm roles that are BOTH in this client's
  # realm scope mapping AND actually held by the user
  # (UserRealmRoleMappingMapper -> RoleResolveUtil; measured by security in
  # nota-security-c2-token.md). Everything outside the reviewed set stays
  # denied by default, and the mapping itself grants no role to anyone.
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

verify_client() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient true
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled true
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled false
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
  # Post-ensure/audit assertion (OWU-28 C2): every reviewed realm role must sit
  # in the client's realm scope mapping, or the gateway's write rules can
  # never see it in jwt.realm_access.roles and the chat's write case is dead.
  for role in ${REALM_SCOPE_ROLE_NAMES}; do
    role_scope_has_direct_role "${role}" || \
      fail "client realm scope mapping is missing ${role}"
  done
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
