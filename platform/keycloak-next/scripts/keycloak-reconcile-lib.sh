#!/bin/sh
# keycloak-reconcile-lib.sh — pure mechanical helpers shared by the
# keycloak-next PostSync reconcilers (INFRA-477, architect ruling on PR #234).
#
# NOT a standalone script: it is sourced with `.` by
#   agentgateway-domain-roles.sh, chat-agentgateway-client.sh,
#   agentgateway-chat-mcp-client.sh, jarvis-echo-client.sh and
#   hermes-enviar-client.sh,
# which mount it in their ConfigMap next to the entrypoint. Every helper
# resolves its configuration (KCADM, ADMIN_CONFIG, CLIENT_CONFIG, KEYCLOAK_URL,
# REALM, CLIENT_ID, CLIENT_UUID, MAPPER_NAME, AGENTGATEWAY_AUDIENCE) at CALL
# time from the sourcing script's globals, so nothing here is parameterized
# and no policy lives here: allowlists, immutable guards, role-verification
# wording and the fullScopeAllowed flip order stay in each reconciler.
#
# This file must never execute anything at source time — definitions only.
#
# The bootstrap (cleanup trap, fail, nonempty_lines, line_count, login_admin,
# kget) is NOT defined here: it is kc-admin-common.sh, sourced FIRST by every
# script that sources this file. The helpers below call it.

# Machine-readable progress line for the Job log; CLIENT_ID is the sourcing
# reconciler's own identity.
progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${CLIENT_ID}" "$1"
}

# Client uuid by CLIENT_ID, or empty when absent (never fatal).
resolve_client_optional() {
  rows="$(kget clients -q "clientId=${CLIENT_ID}" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate client ${CLIENT_ID}"
  printf '%s' "${rows}"
}

# The same lookup, fatal when the client does not exist.
require_client() {
  uuid="$(resolve_client_optional)"
  [ -n "${uuid}" ] || fail "client ${CLIENT_ID} is missing"
  printf '%s' "${uuid}"
}

# One scalar field of a client by uuid.
client_field() {
  kget "clients/$1" --fields "$2" --format csv --noquotes | nonempty_lines
}

# Boolean client attribute pinned to an exact literal value.
assert_client_boolean() {
  actual="$(client_field "$1" "$2")"
  [ "${actual}" = "$3" ] || fail "client field $2 expected $3"
}

# True when the realm role exists; role CREATION is owned by the earlier
# domain-roles/read-grants hooks, never by a client reconciler.
role_exists() {
  kget "roles/$1" --fields id >/dev/null 2>&1
}

# csv "id,name" rows on stdin: print the id of the mapper named $1.
filter_mapper_id() {
  expected="$1"
  while IFS=, read -r mapper_id mapper_name; do
    if [ "${mapper_name}" = "${expected}" ]; then
      printf '%s\n' "${mapper_id}"
    fi
  done
}

# Mapper uuid of MAPPER_NAME under CLIENT_UUID, or empty; two mappers with
# the same name is drift, not something to guess about.
mapper_uuid_optional() {
  rows="$(kget "clients/${CLIENT_UUID}/protocol-mappers/models" \
    --fields id,name --format csv --noquotes | \
    filter_mapper_id "${MAPPER_NAME}" | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate mapper ${MAPPER_NAME}"
  printf '%s' "${rows}"
}

# House audience-mapper pattern: the reviewed MCP resource audience goes into
# the access and introspection tokens, never into the id token.
upsert_audience_mapper() {
  mapper_uuid="$(mapper_uuid_optional)"
  endpoint="clients/${CLIENT_UUID}/protocol-mappers/models"
  action=create
  # Update in place when the mapper exists, create it when it does not.
  if [ -n "${mapper_uuid}" ]; then
    endpoint="${endpoint}/${mapper_uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "name=${MAPPER_NAME}" \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s "config.\"included.custom.audience\"=${AGENTGATEWAY_AUDIENCE}" \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' >/dev/null 2>&1 || \
    fail "failed to reconcile audience mapper"
}

# Direct (non-composite) realm role present in the client role scope.
role_scope_has_direct_role() {
  kget "clients/${CLIENT_UUID}/scope-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "$1"
}

# Map ONE realm role into the client role scope, created only when absent and
# re-read after to fail loud. $1 = role name. With fullScopeAllowed=false,
# Keycloak 26 emits in the token only the realm roles that are BOTH in this
# client's realm scope mapping AND actually held by the user; the mapping
# itself grants nothing to anyone. Which roles belong in the scope (and the
# check that nothing else does) is policy and stays in the reconciler.
ensure_role_in_client_scope() {
  if ! role_scope_has_direct_role "$1"; then
    role_id="$(kget "roles/$1" --fields id --format csv --noquotes | nonempty_lines)"
    [ -n "${role_id}" ] || fail "$1 id is empty"
    role_body="$(printf '[{"id":"%s","name":"%s"}]' "${role_id}" "$1")"
    "${KCADM}" create "clients/${CLIENT_UUID}/scope-mappings/realm" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" -b "${role_body}" >/dev/null 2>&1 || \
      fail "failed to map $1 into the client role scope"
    unset role_body role_id
  fi
  role_scope_has_direct_role "$1" || fail "client role scope is missing $1"
}

# The service account Keycloak derives from a confidential client; its id and
# its exact `service-account-<client>` username, pinned.
resolve_service_account() {
  SERVICE_ACCOUNT_ID="$(kget "clients/${CLIENT_UUID}/service-account-user" \
    --fields id --format csv --noquotes | nonempty_lines)"
  SERVICE_ACCOUNT_USERNAME="$(kget "clients/${CLIENT_UUID}/service-account-user" \
    --fields username --format csv --noquotes | nonempty_lines)"
  [ -n "${SERVICE_ACCOUNT_ID}" ] || fail "service account id is empty"
  [ "${SERVICE_ACCOUNT_USERNAME}" = "service-account-${CLIENT_ID}" ] || \
    fail "unexpected service account username"
}

# Realm roles held directly by the resolved service account.
service_account_realm_roles() {
  kget "users/${SERVICE_ACCOUNT_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines
}

target_has_direct_role() {
  service_account_realm_roles | grep -Fxq "$1"
}

# Read the CURRENT client secret through the admin API (GET, never POST:
# reading must not rotate it). Never printed. $1 = client uuid.
client_secret_via_admin() {
  kget "clients/$1/client-secret" --fields value --format csv --noquotes | nonempty_lines
}

# Mint a client_credentials token for CLIENT_ID and print the decoded JWT
# claims. $1 = client secret, $2 = message when the credentials call fails.
# Neither the secret nor the token is ever printed; the config file is wiped.
mint_claims_with_secret() {
  "${KCADM}" config credentials \
    --config "${CLIENT_CONFIG}" \
    --server "${KEYCLOAK_URL}" \
    --realm "${REALM}" \
    --client "${CLIENT_ID}" \
    --secret "$1" >/dev/null 2>&1 || fail "$2"
  # kcadm persists the bearer token inside the client config file.
  token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${CLIENT_CONFIG}" | head -n1)"
  [ -n "${token}" ] || fail "access token is missing"
  payload="$(printf '%s' "${token}" | cut -d. -f2)"
  unset token
  # Restore the '=' padding base64url dropped before decoding the payload.
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

# stdin: decoded JWT claims. stdout: sorted comma list of realm_access roles.
token_realm_roles() {
  sed -n 's/.*"realm_access"[[:space:]]*:[[:space:]]*{[^}]*"roles"[[:space:]]*:[[:space:]]*\(\[[^]]*\]\).*/\1/p' \
    | tr -d '[]"' | tr ',' '\n' | nonempty_lines | sort | tr '\n' ',' | sed 's/,$//'
}
