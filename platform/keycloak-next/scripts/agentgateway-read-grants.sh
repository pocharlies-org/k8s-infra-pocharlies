#!/bin/sh
set -eu

umask 077

# INFRA-44 (INFRA-23 H2): reconcile the agentgateway-read:<route> realm roles,
# the individual grants to the two read principals, and the explicit client
# role-scope mappings that make the granted roles travel in minted tokens
# (SC-100 defect 6 family). Grants are individual only: any group mapping is a
# policy violation (SC-44 C6 precedent). The matrix below is the CTO ruling R2
# of 2026-09-12 and is immutable from inside this script.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-agentgateway-mcp}"
OPENCLAW_CLIENT_ID="${OPENCLAW_CLIENT_ID:-openclaw-readonly-agentgateway}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
WRITE_ROLE_NAME="${WRITE_ROLE_NAME:-agentgateway-write}"
OPENCLAW_BASE_ROLE="${OPENCLAW_BASE_ROLE:-cto-office-send}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-read-grants-admin.config
CLIENT_CONFIG=/tmp/kcadm-read-grants-client.config

READ_ROLE_NAMES="${READ_ROLE_NAMES:-agentgateway-read:analytics,agentgateway-read:atlassian,agentgateway-read:brain,agentgateway-read:dgx-control,agentgateway-read:gsc,agentgateway-read:image,agentgateway-read:merchant,agentgateway-read:offers,agentgateway-read:picqer,agentgateway-read:shopify,agentgateway-read:shopify-admin,agentgateway-read:skirmshop-plugins,agentgateway-read:social,agentgateway-read:stt,agentgateway-read:studio,agentgateway-read:synapse,agentgateway-read:synapse-sre,agentgateway-read:synapse-tools,agentgateway-read:tts,agentgateway-read:weight,agentgateway-read:workspace}"
OPENCLAW_READ_ROLE_NAMES="${OPENCLAW_READ_ROLE_NAMES:-agentgateway-read:gsc,agentgateway-read:offers,agentgateway-read:skirmshop-plugins,agentgateway-read:studio,agentgateway-read:synapse,agentgateway-read:synapse-tools}"
EXPECTED_READ_ROLE_NAMES="agentgateway-read:analytics,agentgateway-read:atlassian,agentgateway-read:brain,agentgateway-read:dgx-control,agentgateway-read:gsc,agentgateway-read:image,agentgateway-read:merchant,agentgateway-read:offers,agentgateway-read:picqer,agentgateway-read:shopify,agentgateway-read:shopify-admin,agentgateway-read:skirmshop-plugins,agentgateway-read:social,agentgateway-read:stt,agentgateway-read:studio,agentgateway-read:synapse,agentgateway-read:synapse-sre,agentgateway-read:synapse-tools,agentgateway-read:tts,agentgateway-read:weight,agentgateway-read:workspace"
EXPECTED_OPENCLAW_READ_ROLE_NAMES="agentgateway-read:gsc,agentgateway-read:offers,agentgateway-read:skirmshop-plugins,agentgateway-read:studio,agentgateway-read:synapse,agentgateway-read:synapse-tools"

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[ "${CLIENT_ID}" = "agentgateway-mcp" ] || fail "CLIENT_ID is immutable"
[ "${OPENCLAW_CLIENT_ID}" = "openclaw-readonly-agentgateway" ] || fail "OPENCLAW_CLIENT_ID is immutable"
[ "${WRITE_ROLE_NAME}" = "agentgateway-write" ] || fail "WRITE_ROLE_NAME is immutable"
[ "${OPENCLAW_BASE_ROLE}" = "cto-office-send" ] || fail "OPENCLAW_BASE_ROLE is immutable"
[ "${READ_ROLE_NAMES}" = "${EXPECTED_READ_ROLE_NAMES}" ] || \
  fail "READ_ROLE_NAMES is immutable; update the reviewed matrix and the AgentGateway enforce stories together"
[ "${OPENCLAW_READ_ROLE_NAMES}" = "${EXPECTED_OPENCLAW_READ_ROLE_NAMES}" ] || \
  fail "OPENCLAW_READ_ROLE_NAMES is immutable; update the reviewed matrix and the AgentGateway enforce stories together"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

nonempty_lines() { sed '/^[[:space:]]*$/d'; }

line_count() { nonempty_lines | wc -l | tr -d '[:space:]'; }

comma_list_sorted() {
  tr ',' '\n' | sed '/^[[:space:]]*$/d' | sort | tr '\n' ',' | sed 's/,$//'
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

resolve_client() {
  client_id="$1"
  rows="$(kget clients -q "clientId=${client_id}" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" = "1" ] || fail "expected exactly one client ${client_id}"
  uuid="${rows}"
  [ "$(kget "clients/${uuid}" --fields enabled --format csv --noquotes | nonempty_lines)" = "true" ] || \
    fail "client ${client_id} is disabled"
  [ "$(kget "clients/${uuid}" --fields serviceAccountsEnabled --format csv --noquotes | nonempty_lines)" = "true" ] || \
    fail "client ${client_id} has no service account"
  sa_id="$(kget "clients/${uuid}/service-account-user" --fields id --format csv --noquotes | nonempty_lines)"
  sa_user="$(kget "clients/${uuid}/service-account-user" --fields username --format csv --noquotes | nonempty_lines)"
  [ -n "${sa_id}" ] || fail "service account id is empty for ${client_id}"
  [ "${sa_user}" = "service-account-${client_id}" ] || fail "unexpected service account username for ${client_id}"
  printf '%s %s %s' "${uuid}" "${sa_id}" "${sa_user}"
}

role_listing() {
  # Lines "name,composite" for every realm role, in one bounded call.
  kget roles -q max=500 --fields name,composite --format csv --noquotes | nonempty_lines
}

listing_has_role() {
  printf '%s\n' "$1" | grep -Fxq "${2},false"
}

listing_has_composite_role() {
  printf '%s\n' "$1" | grep -Fxq "${2},true"
}

ensure_roles_exist() {
  listing="$(role_listing)"
  created=0
  old_ifs="${IFS}"
  IFS=,
  for role in ${READ_ROLE_NAMES}; do
    IFS="${old_ifs}"
    if ! printf '%s\n' "${listing}" | grep -Fq "${role},"; then
      "${KCADM}" create roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s "name=${role}" \
        -s "description=Allows reads of the AgentGateway /${role#agentgateway-read:} route (INFRA-23 read authorization)" \
        -s composite=false >/dev/null 2>&1 || fail "failed to create ${role}"
      created=$((created + 1))
    fi
    IFS=,
  done
  IFS="${old_ifs}"
  CREATED_ROLES="${created}"
  verify_roles_present
}

verify_roles_present() {
  listing="$(role_listing)"
  old_ifs="${IFS}"
  IFS=,
  for role in ${READ_ROLE_NAMES}; do
    IFS="${old_ifs}"
    if listing_has_composite_role "${listing}" "${role}"; then
      fail "${role} must remain non-composite"
    fi
    listing_has_role "${listing}" "${role}" || fail "${role} is missing from the realm"
    IFS=,
  done
  IFS="${old_ifs}"
}

role_allowed_users() {
  role="$1"
  if printf '%s\n' "${OPENCLAW_READ_ROLE_NAMES}" | tr ',' '\n' | grep -Fxq "${role}"; then
    printf '%s\n%s\n' "${MCP_SA_USERNAME}" "${OC_SA_USERNAME}"
  else
    printf '%s\n' "${MCP_SA_USERNAME}"
  fi
}

assert_role_exclusivity() {
  role="$1"
  # Bounded role-member endpoints (same idiom as the SRE reconciler): at most
  # the allowed service accounts, never a group, never a human.
  users="$(kget "roles/${role}/users" -q first=0 -q max=3 \
    --fields username --format csv --noquotes | nonempty_lines)"
  groups="$(kget "roles/${role}/groups" -q first=0 -q max=3 \
    --fields path --format csv --noquotes | nonempty_lines)"
  [ -z "${groups}" ] || fail "${role} is mapped to a group; group role-mapping is forbidden (SC-44 C6)"
  allowed="$(role_allowed_users "${role}")"
  if [ -n "${users}" ]; then
    while IFS= read -r username; do
      printf '%s\n' "${allowed}" | grep -Fxq "${username}" || \
        fail "${role} is mapped to an unauthorized user ${username}"
    done <<EOF
${users}
EOF
  fi
}

assert_all_roles_exclusive() {
  old_ifs="${IFS}"
  IFS=,
  for role in ${READ_ROLE_NAMES}; do
    IFS="${old_ifs}"
    assert_role_exclusivity "${role}"
    IFS=,
  done
  IFS="${old_ifs}"
}

scope_names() {
  kget "clients/$1/scope-mappings/realm" --fields name --format csv --noquotes | nonempty_lines | sort
}

grant_names() {
  kget "users/$1/role-mappings/realm" --fields name --format csv --noquotes | nonempty_lines | sort
}

grant_missing_roles() {
  # $1 = REST collection (users/<id>/role-mappings/realm or clients/<uuid>/scope-mappings/realm)
  # $2 = newline list of currently mapped names, $3 = comma list of wanted roles
  collection="$1"
  current="$2"
  wanted="$3"
  missing=""
  old_ifs="${IFS}"
  IFS=,
  for role in ${wanted}; do
    IFS="${old_ifs}"
    if ! printf '%s\n' "${current}" | grep -Fxq "${role}"; then
      role_id="$(kget "roles/${role}" --fields id --format csv --noquotes | nonempty_lines)"
      [ -n "${role_id}" ] || fail "${role} is missing from the realm"
      if [ -n "${missing}" ]; then
        missing="${missing},"
      fi
      missing="${missing}{\"id\":\"${role_id}\",\"name\":\"${role}\"}"
    fi
    IFS=,
  done
  IFS="${old_ifs}"
  if [ -n "${missing}" ]; then
    "${KCADM}" create "${collection}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -b "[${missing}]" >/dev/null 2>&1 || fail "failed to map roles into ${collection}"
  fi
}

assert_wanted_mapped() {
  # $1 = newline list of mapped names, $2 = comma list of wanted roles
  current="$1"
  wanted="$2"
  old_ifs="${IFS}"
  IFS=,
  for role in ${wanted}; do
    IFS="${old_ifs}"
    printf '%s\n' "${current}" | grep -Fxq "${role}" || fail "${role} is not mapped in the expected set"
    IFS=,
  done
  IFS="${old_ifs}"
}

assert_mapped_within() {
  # $1 = newline list of mapped names, $2 = newline list of allowed names
  current="$1"
  allowed="$2"
  if [ -n "${current}" ]; then
    while IFS= read -r name; do
      printf '%s\n' "${allowed}" | grep -Fxq "${name}" || \
        fail "unexpected mapped role ${name} widens the reviewed matrix"
    done <<EOF
${current}
EOF
  fi
}

resolve_clients() {
  set -- $(resolve_client "${CLIENT_ID}")
  MCP_UUID="$1" MCP_SA_ID="$2" MCP_SA_USERNAME="$3"
  set -- $(resolve_client "${OPENCLAW_CLIENT_ID}")
  OC_UUID="$1" OC_SA_ID="$2" OC_SA_USERNAME="$3"
  [ "$(kget "clients/${OC_UUID}" --fields fullScopeAllowed --format csv --noquotes | nonempty_lines)" = "false" ] || \
    fail "${OPENCLAW_CLIENT_ID} must keep fullScopeAllowed=false"
}

ensure_client_scopes() {
  grant_missing_roles "clients/${MCP_UUID}/scope-mappings/realm" "$(scope_names "${MCP_UUID}")" "${READ_ROLE_NAMES}"
  grant_missing_roles "clients/${OC_UUID}/scope-mappings/realm" "$(scope_names "${OC_UUID}")" "${OPENCLAW_READ_ROLE_NAMES}"
}

verify_client_scopes() {
  mcp_scope="$(scope_names "${MCP_UUID}")"
  assert_wanted_mapped "${mcp_scope}" "${READ_ROLE_NAMES}"
  assert_mapped_within "${mcp_scope}" "$(printf '%s\n' "${READ_ROLE_NAMES}" | tr ',' '\n')"

  oc_scope="$(scope_names "${OC_UUID}")"
  assert_wanted_mapped "${oc_scope}" "${OPENCLAW_READ_ROLE_NAMES}"
  assert_mapped_within "${oc_scope}" "$(printf '%s\n%s\n' "${OPENCLAW_BASE_ROLE}" "${OPENCLAW_READ_ROLE_NAMES}" | tr ',' '\n')"
}

ensure_sa_grants() {
  grant_missing_roles "users/${MCP_SA_ID}/role-mappings/realm" "$(grant_names "${MCP_SA_ID}")" "${READ_ROLE_NAMES}"
  grant_missing_roles "users/${OC_SA_ID}/role-mappings/realm" "$(grant_names "${OC_SA_ID}")" "${OPENCLAW_READ_ROLE_NAMES}"
}

verify_sa_grants() {
  mcp_grants="$(grant_names "${MCP_SA_ID}")"
  assert_wanted_mapped "${mcp_grants}" "${READ_ROLE_NAMES}"
  assert_mapped_within "${mcp_grants}" "$(printf '%s\n%s\n%s\n' default-roles-edani "${WRITE_ROLE_NAME}" "${READ_ROLE_NAMES}" | tr ',' '\n')"

  oc_grants="$(grant_names "${OC_SA_ID}")"
  assert_wanted_mapped "${oc_grants}" "${OPENCLAW_READ_ROLE_NAMES}"
  assert_mapped_within "${oc_grants}" "$(printf '%s\n%s\n%s\n' default-roles-edani "${OPENCLAW_BASE_ROLE}" "${OPENCLAW_READ_ROLE_NAMES}" | tr ',' '\n')"
}

token_realm_roles() {
  # stdin: decoded JWT claims. stdout: sorted comma list of realm_access roles.
  sed -n 's/.*"realm_access"[[:space:]]*:[[:space:]]*{[^}]*"roles"[[:space:]]*:[[:space:]]*\(\[[^]]*\]\).*/\1/p' \
    | tr -d '[]"' | tr ',' '\n' | nonempty_lines | sort | tr '\n' ',' | sed 's/,$//'
}

mint_claims() {
  # $1 = client uuid, $2 = client id. Never prints the token or the secret.
  client_secret="$(kget "clients/$1/client-secret" --fields value --format csv --noquotes | nonempty_lines)"
  [ -n "${client_secret}" ] || fail "client secret is empty for $2"
  "${KCADM}" config credentials \
    --config "${CLIENT_CONFIG}" \
    --server "${KEYCLOAK_URL}" \
    --realm "${REALM}" \
    --client "$2" \
    --secret "${client_secret}" >/dev/null 2>&1 || fail "client_credentials token mint failed for $2"
  unset client_secret
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
  claims="$(printf '%s' "${payload}" | tr '_-' '/+' | base64 -d 2>/dev/null)" || fail "JWT decode failed"
  unset payload
  rm -f "${CLIENT_CONFIG}"
  printf '%s' "${claims}"
}

verify_minted_tokens() {
  claims="$(mint_claims "${MCP_UUID}" "${CLIENT_ID}")"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${CLIENT_ID}"'"' || \
    fail "minted token has wrong azp"
  printf '%s' "${claims}" | grep -Fq "${AGENTGATEWAY_AUDIENCE}" || fail "minted token is missing the gateway audience"
  expected="$(printf '%s\n%s\n' "${WRITE_ROLE_NAME}" "${READ_ROLE_NAMES}" | comma_list_sorted)"
  actual="$(printf '%s' "${claims}" | token_realm_roles)"
  [ -n "${actual}" ] || fail "minted token has no realm_access roles claim"
  [ "${actual}" = "${expected}" ] || fail "minted ${CLIENT_ID} token realm roles are not exactly the reviewed matrix"
  unset claims actual expected

  claims="$(mint_claims "${OC_UUID}" "${OPENCLAW_CLIENT_ID}")"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${OPENCLAW_CLIENT_ID}"'"' || \
    fail "minted openclaw token has wrong azp"
  printf '%s' "${claims}" | grep -Fq "${AGENTGATEWAY_AUDIENCE}" || fail "minted openclaw token is missing the gateway audience"
  if printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"'"${WRITE_ROLE_NAME}"'"'; then
    fail "minted read-only token contains ${WRITE_ROLE_NAME}"
  fi
  expected="$(printf '%s\n%s\n' "${OPENCLAW_BASE_ROLE}" "${OPENCLAW_READ_ROLE_NAMES}" | comma_list_sorted)"
  actual="$(printf '%s' "${claims}" | token_realm_roles)"
  [ -n "${actual}" ] || fail "minted openclaw token has no realm_access roles claim"
  [ "${actual}" = "${expected}" ] || fail "minted ${OPENCLAW_CLIENT_ID} token realm roles are not exactly the reviewed matrix"
  unset claims actual expected
}

rollback_roles() {
  # Deleting a realm role cascades its user and client-scope mappings, so the
  # whole additive surface of this reconciler is removed in one pass. Guarded:
  # any member outside the reviewed matrix aborts before the first deletion.
  old_ifs="${IFS}"
  IFS=,
  for role in ${READ_ROLE_NAMES}; do
    IFS="${old_ifs}"
    assert_role_exclusivity "${role}"
    IFS=,
  done
  IFS="${old_ifs}"
  old_ifs="${IFS}"
  IFS=,
  for role in ${READ_ROLE_NAMES}; do
    IFS="${old_ifs}"
    if kget "roles/${role}" --fields id >/dev/null 2>&1; then
      "${KCADM}" delete "roles/${role}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
        fail "failed to delete ${role}"
    fi
    IFS=,
  done
  IFS="${old_ifs}"
  mcp_grants="$(grant_names "${MCP_SA_ID}")"
  oc_grants="$(grant_names "${OC_SA_ID}")"
  mcp_scope="$(scope_names "${MCP_UUID}")"
  oc_scope="$(scope_names "${OC_UUID}")"
  listing="$(role_listing)"
  old_ifs="${IFS}"
  IFS=,
  for role in ${READ_ROLE_NAMES}; do
    IFS="${old_ifs}"
    if printf '%s\n' "${listing}" | grep -Fxq "${role},false"; then
      fail "${role} remains after rollback"
    fi
    if printf '%s\n%s\n%s\n%s\n' "${mcp_grants}" "${oc_grants}" "${mcp_scope}" "${oc_scope}" \
      | grep -Fxq "${role}"; then
      fail "${role} remains mapped after rollback"
    fi
    IFS=,
  done
  IFS="${old_ifs}"
  printf '{"reconciler":"agentgateway-read-grants","roles_deleted":21,"present":false}\n'
}

login_admin
resolve_clients

case "${MODE}" in
  ensure)
    ensure_roles_exist
    assert_all_roles_exclusive
    ensure_client_scopes
    verify_client_scopes
    ensure_sa_grants
    verify_sa_grants
    assert_all_roles_exclusive
    verify_minted_tokens
    printf '{"reconciler":"agentgateway-read-grants","roles":21,"created":%s,"grants_agentgateway_mcp":21,"grants_openclaw_agentgateway":6,"tokens_verified":true}\n' \
      "${CREATED_ROLES}"
    ;;
  audit)
    verify_roles_present
    assert_all_roles_exclusive
    verify_client_scopes
    verify_sa_grants
    verify_minted_tokens
    printf '{"reconciler":"agentgateway-read-grants","roles":21,"created":0,"grants_agentgateway_mcp":21,"grants_openclaw_agentgateway":6,"tokens_verified":true}\n'
    ;;
  rollback)
    rollback_roles
    ;;
esac
