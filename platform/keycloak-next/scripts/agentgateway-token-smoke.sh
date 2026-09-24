#!/bin/sh
set -eu

umask 077

# INFRA-248 (INFRA-219 P2, criterion C2): read-only smoke of the roles→token
# path for the AgentGateway clients. It changes NOTHING in the realm: every
# admin call is a GET, and the only other server interaction is one
# client_credentials mint per minted client.
#
# The rule it proves is the same for every client, so no role matrix is copied
# here (ROLES.yaml and the reconcilers own those):
#
#   realm_access.roles of a freshly minted token
#     == effective realm roles of the client's service account
#        ∩ effective realm scope of the client
#
# (clients/<uuid>/scope-mappings/realm/composite returns every realm role when
# fullScopeAllowed=true and the expanded scope-mappings when it is false, so
# one formula covers both flag states — measured 2026-09-24: 43 roles for the
# fullScopeAllowed=true client, 6 for chat-agentgateway, 0 for cloudblue; the
# only client scope carrying a realm scope mapping is the OPTIONAL
# offline_access, which a client_credentials mint without scope= never
# requests.)
#
# Tokens minted (architecture ruling C-5): chat-agentgateway,
# company-metrics-agentgateway and the negative subject cloudblue, whose
# service account holds only default-roles-edani (audited 2026-09-24). The
# agentgateway-mcp and openclaw-readonly-agentgateway tokens are NOT minted
# here: agentgateway-read-grants.sh mints and asserts them exactly on every
# PostSync (wave 20). Those two and the public agentgateway-social-mcp (no
# service account, user flow) are checked by CONFIG only: fullScopeAllowed,
# the `roles` default client scope and the realm scope mappings.
#
# Secrets never reach argv: the admin password and each client secret go to
# kcadm through KC_CLI_PASSWORD / KC_CLI_CLIENT_SECRET (documented by
# `kcadm.sh config credentials --help` of the pinned image). The token and the
# secret are never printed; only role names are.

KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
MINTED_CLIENT_IDS="${MINTED_CLIENT_IDS:-chat-agentgateway company-metrics-agentgateway}"
NEGATIVE_CLIENT_ID="${NEGATIVE_CLIENT_ID:-cloudblue}"
CONFIG_CLIENT_IDS="${CONFIG_CLIENT_IDS:-agentgateway-mcp openclaw-readonly-agentgateway agentgateway-social-mcp}"
GATEWAY_ROLE_PREFIX=agentgateway-
ADMIN_CONFIG=/tmp/kcadm-token-smoke-admin.config
CLIENT_CONFIG=/tmp/kcadm-token-smoke-client.config

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[ "${MINTED_CLIENT_IDS}" = "chat-agentgateway company-metrics-agentgateway" ] || \
  fail "MINTED_CLIENT_IDS is immutable (architecture ruling C-5)"
[ "${NEGATIVE_CLIENT_ID}" = "cloudblue" ] || fail "NEGATIVE_CLIENT_ID is immutable"
[ "${CONFIG_CLIENT_IDS}" = "agentgateway-mcp openclaw-readonly-agentgateway agentgateway-social-mcp" ] || \
  fail "CONFIG_CLIENT_IDS is immutable"

nonempty_lines() { sed '/^[[:space:]]*$/d'; }

line_count() { nonempty_lines | wc -l | tr -d '[:space:]'; }

sorted_comma() { nonempty_lines | sort | tr '\n' ',' | sed 's/,$//'; }

json_array() {
  # stdin: comma list. stdout: JSON array of strings (role names carry no quotes).
  list="$(cat)"
  if [ -z "${list}" ]; then
    printf '[]'
  else
    printf '["%s"]' "$(printf '%s' "${list}" | sed 's/,/","/g')"
  fi
}

gateway_count() {
  # stdin: comma list. stdout: number of agentgateway-* entries.
  tr ',' '\n' | grep -c "^${GATEWAY_ROLE_PREFIX}" || true
}

login_admin() {
  attempt=1
  while [ "${attempt}" -le 30 ]; do
    if KC_CLI_PASSWORD="${KC_BOOTSTRAP_ADMIN_PASSWORD}" "${KCADM}" config credentials \
      --config "${ADMIN_CONFIG}" \
      --server "${KEYCLOAK_URL}" \
      --realm master \
      --user "${KC_BOOTSTRAP_ADMIN_USERNAME}" >/dev/null 2>&1; then
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

resolve_client() {
  # $1 = clientId. stdout: "uuid fullScopeAllowed publicClient". The
  # server-side clientId= filter is a substring match, so the exact row is
  # selected here. One field per call: kcadm's csv column order is not part
  # of any contract this script can rely on.
  rows="$(kget clients -q "clientId=$1" --fields id,clientId --format csv --noquotes \
    | nonempty_lines | grep -F ",$1" | grep -E ",$1\$" || true)"
  [ "$(printf '%s\n' "${rows}" | line_count)" = "1" ] || fail "expected exactly one client $1"
  uuid="${rows%%,*}"
  fullscope="$(kget "clients/${uuid}" --fields fullScopeAllowed --format csv --noquotes | nonempty_lines)"
  public="$(kget "clients/${uuid}" --fields publicClient --format csv --noquotes | nonempty_lines)"
  case "${fullscope}" in true|false) ;; *) fail "unexpected fullScopeAllowed for $1" ;; esac
  case "${public}" in true|false) ;; *) fail "unexpected publicClient for $1" ;; esac
  printf '%s %s %s' "${uuid}" "${fullscope}" "${public}"
}

assert_roles_default_scope() {
  # $1 = client uuid, $2 = clientId. Without the `roles` default scope the
  # realm-role mapper never runs and realm_access disappears from the token.
  kget "clients/$1/default-client-scopes" --fields name --format csv --noquotes | nonempty_lines \
    | grep -Fxq roles || fail "$2 does not carry the roles default client scope"
}

assert_realm_role_mapper() {
  # The realm `roles` client scope must map realm roles into
  # realm_access.roles of the ACCESS token: that is the claim the gateway CEL
  # reads for every route.
  scope_rows="$(kget client-scopes --fields id,name --format csv --noquotes | nonempty_lines | grep ',roles$' || true)"
  [ "$(printf '%s\n' "${scope_rows}" | line_count)" = "1" ] || fail "expected exactly one roles client scope"
  scope_id="$(printf '%s' "${scope_rows}" | cut -d, -f1)"
  mapper_rows="$(kget "client-scopes/${scope_id}/protocol-mappers/models" --fields id,protocolMapper \
    --format csv --noquotes | nonempty_lines | grep ',oidc-usermodel-realm-role-mapper$' || true)"
  [ "$(printf '%s\n' "${mapper_rows}" | line_count)" = "1" ] || fail "expected exactly one realm role mapper in the roles scope"
  mapper_id="$(printf '%s' "${mapper_rows}" | cut -d, -f1)"
  mapper="$(kget "client-scopes/${scope_id}/protocol-mappers/models/${mapper_id}" | tr -d '\n\t ')"
  printf '%s' "${mapper}" | grep -Fq '"claim.name":"realm_access.roles"' || \
    fail "realm role mapper does not write realm_access.roles"
  printf '%s' "${mapper}" | grep -Fq '"access.token.claim":"true"' || \
    fail "realm role mapper does not write the access token"
  printf '{"smoke":"agentgateway-token","check":"realm-role-mapper","scope":"roles","claim":"realm_access.roles","access_token":true}\n'
}

token_realm_roles() {
  # stdin: decoded JWT claims. stdout: sorted comma list of realm_access roles
  # (empty when the claim is absent). Same sed as agentgateway-read-grants.sh.
  sed -n 's/.*"realm_access"[[:space:]]*:[[:space:]]*{[^}]*"roles"[[:space:]]*:[[:space:]]*\(\[[^]]*\]\).*/\1/p' \
    | tr -d '[]"' | tr ',' '\n' | sorted_comma
}

mint_claims() {
  # $1 = client uuid, $2 = clientId. Decodes like mint_claims of
  # agentgateway-read-grants.sh (sed + base64, the image ships no jq).
  client_secret="$(kget "clients/$1/client-secret" --fields value --format csv --noquotes | nonempty_lines)"
  [ -n "${client_secret}" ] || fail "client secret is empty for $2"
  KC_CLI_CLIENT_SECRET="${client_secret}" "${KCADM}" config credentials \
    --config "${CLIENT_CONFIG}" \
    --server "${KEYCLOAK_URL}" \
    --realm "${REALM}" \
    --client "$2" >/dev/null 2>&1 || fail "client_credentials token mint failed for $2"
  unset client_secret
  token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${CLIENT_CONFIG}" | head -n1)"
  rm -f "${CLIENT_CONFIG}"
  [ -n "${token}" ] || fail "kcadm did not persist an access token for $2"
  payload="$(printf '%s' "${token}" | cut -d. -f2)"
  unset token
  case $((${#payload} % 4)) in
    0) ;;
    2) payload="${payload}==" ;;
    3) payload="${payload}=" ;;
    *) fail "JWT payload has invalid base64url length for $2" ;;
  esac
  claims="$(printf '%s' "${payload}" | tr '_-' '/+' | base64 -d 2>/dev/null)" || fail "JWT decode failed for $2"
  unset payload
  printf '%s' "${claims}"
}

expected_token_roles() {
  # $1 = client uuid, $2 = service-account user id. stdout: sorted comma list
  # of effective SA realm roles that pass the client's effective realm scope.
  effective="$(kget "users/$2/role-mappings/realm/composite" --fields name --format csv --noquotes | nonempty_lines)"
  scope="$(kget "clients/$1/scope-mappings/realm/composite" --fields name --format csv --noquotes | nonempty_lines)"
  if [ -n "${effective}" ]; then
    printf '%s\n' "${effective}" | while IFS= read -r role; do
      if printf '%s\n' "${scope}" | grep -Fxq "${role}"; then
        printf '%s\n' "${role}"
      fi
    done | sorted_comma
  fi
}

smoke_minted_client() {
  # $1 = clientId, $2 = kind (positive|negative).
  client_id="$1" kind="$2"
  resolved="$(resolve_client "${client_id}")"
  set -- ${resolved}
  uuid="$1" fullscope="$2" public="$3"
  [ "${public}" = "false" ] || fail "${client_id} must be confidential to mint a service-account token"
  assert_roles_default_scope "${uuid}" "${client_id}"
  sa_rows="$(kget "clients/${uuid}/service-account-user" --fields id,username --format csv --noquotes | nonempty_lines)"
  sa_id="$(printf '%s' "${sa_rows}" | cut -d, -f1)"
  sa_user="$(printf '%s' "${sa_rows}" | cut -d, -f2)"
  [ -n "${sa_id}" ] || fail "service account id is empty for ${client_id}"
  [ "${sa_user}" = "service-account-${client_id}" ] || fail "unexpected service account username for ${client_id}"
  expected="$(expected_token_roles "${uuid}" "${sa_id}")"
  claims="$(mint_claims "${uuid}" "${client_id}")"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${client_id}"'"' || \
    fail "minted ${client_id} token has wrong azp"
  actual="$(printf '%s' "${claims}" | token_realm_roles)"
  unset claims
  gateway="$(printf '%s' "${actual}" | gateway_count)"
  printf '{"smoke":"agentgateway-token","client":"%s","kind":"%s","fullScopeAllowed":%s,"roles_default_scope":true,"token_realm_roles":%s,"expected_realm_roles":%s,"agentgateway_roles":%s}\n' \
    "${client_id}" "${kind}" "${fullscope}" "$(printf '%s' "${actual}" | json_array)" \
    "$(printf '%s' "${expected}" | json_array)" "${gateway}"
  [ "${actual}" = "${expected}" ] || \
    fail "${client_id} token realm_access.roles differs from its granted roles within the client scope (roles do not travel uniformly)"
  case "${kind}" in
    positive)
      [ -n "${actual}" ] || fail "${client_id} token carries no realm_access.roles"
      ;;
    negative)
      [ "${gateway}" = "0" ] || fail "negative subject ${client_id} carries ${gateway} agentgateway-* roles in its token"
      sa_gateway="$(kget "users/${sa_id}/role-mappings/realm/composite" --fields name --format csv --noquotes \
        | sorted_comma | gateway_count)"
      [ "${sa_gateway}" = "0" ] || fail "negative subject ${client_id} is no longer role-less: its service account holds agentgateway-* roles"
      ;;
  esac
}

smoke_config_client() {
  # $1 = clientId. Config only (no token): see the header for why.
  client_id="$1"
  resolved="$(resolve_client "${client_id}")"
  set -- ${resolved}
  uuid="$1" fullscope="$2" public="$3"
  assert_roles_default_scope "${uuid}" "${client_id}"
  scope="$(kget "clients/${uuid}/scope-mappings/realm" --fields name --format csv --noquotes | sorted_comma)"
  printf '{"smoke":"agentgateway-token","client":"%s","kind":"config","publicClient":%s,"fullScopeAllowed":%s,"roles_default_scope":true,"realm_scope_mappings":%s,"agentgateway_scope_roles":%s}\n' \
    "${client_id}" "${public}" "${fullscope}" "$(printf '%s' "${scope}" | json_array)" \
    "$(printf '%s' "${scope}" | gateway_count)"
  [ "${fullscope}" = "true" ] || [ -n "${scope}" ] || \
    fail "${client_id} has fullScopeAllowed=false and an empty realm scope: no realm role can travel"
}

login_admin
assert_realm_role_mapper
for client in ${MINTED_CLIENT_IDS}; do
  smoke_minted_client "${client}" positive
done
smoke_minted_client "${NEGATIVE_CLIENT_ID}" negative
for client in ${CONFIG_CLIENT_IDS}; do
  smoke_config_client "${client}"
done
printf '{"smoke":"agentgateway-token","result":"PASS","minted":3,"config_checked":3,"realm_mutations":0}\n'
