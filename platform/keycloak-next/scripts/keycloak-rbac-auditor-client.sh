#!/bin/sh
# INFRA-250 (INFRA-219 P4): reconciler of the keycloak-rbac-auditor client.
#
# The keycloak-role-drift CronJob reads the realm with this client, never with
# the bootstrap admin nor with keycloak-automation. Its service account holds
# EXACTLY the realm-management client roles below and nothing else: no
# view-clients (it would read client secrets) and no manage-* (it would change
# the realm). This PostSync fixes the client and its secret, grants those
# roles, and then proves the exact set fail-closed: direct grants, effective
# grants, client role scope, the minted token, and two live denials made with
# the auditor's own token (client-secret read and a role-mapping POST).
# An extra role anywhere is a failure, never something this job removes.
#
# Secrets never reach argv (visible in /proc to anyone on the node): the admin
# password and the auditor secret reach kcadm through KC_CLI_PASSWORD and
# KC_CLI_CLIENT_SECRET (documented by `kcadm.sh config credentials --help` of
# the pinned image), and the client secret travels in the JSON body on stdin.
set -eu

umask 077

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-keycloak-rbac-auditor}"
MANAGEMENT_CLIENT_ID="${MANAGEMENT_CLIENT_ID:-realm-management}"
EXPECTED_MANAGEMENT_ROLES="${EXPECTED_MANAGEMENT_ROLES:-query-groups,query-users,view-realm,view-users}"
EXPECTED_REALM_ROLES="${EXPECTED_REALM_ROLES:-default-roles-edani}"
RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-rbac-auditor-admin.config
CLIENT_CONFIG=/tmp/kcadm-rbac-auditor-client.config
PROBE_ERR=/tmp/kcadm-rbac-auditor-probe.err

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_CONFIG}" "${PROBE_ERR}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${CLIENT_ID}" "$1"
}

# The identity and its privilege are immutable: an env override cannot widen
# them. The set is sorted, comma-separated, and never names view-clients or
# any manage-* role.
[ "${RECONCILE_CONTRACT_VERSION}" = "1" ] || fail "unsupported reconcile contract version"
[ "${CLIENT_ID}" = "keycloak-rbac-auditor" ] || fail "CLIENT_ID is immutable"
[ "${MANAGEMENT_CLIENT_ID}" = "realm-management" ] || fail "MANAGEMENT_CLIENT_ID is immutable"
[ "${EXPECTED_MANAGEMENT_ROLES}" = "query-groups,query-users,view-realm,view-users" ] || \
  fail "EXPECTED_MANAGEMENT_ROLES is immutable"
[ "${EXPECTED_REALM_ROLES}" = "default-roles-edani" ] || fail "EXPECTED_REALM_ROLES is immutable"
CLIENT_SECRET="${KEYCLOAK_RBAC_AUDITOR_CLIENT_SECRET:-}"
case "${MODE}" in
  ensure|audit) [ -n "${CLIENT_SECRET}" ] || fail "client secret is empty" ;;
  *) fail "unsupported MODE=${MODE}" ;;
esac

nonempty_lines() {
  sed '/^[[:space:]]*$/d'
}

line_count() {
  nonempty_lines | wc -l | tr -d '[:space:]'
}

as_set() {
  nonempty_lines | sort -u | tr '\n' ',' | sed 's/,$//'
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

resolve_client_optional() {
  rows="$(kget clients -q "clientId=$1" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate client $1"
  printf '%s' "${rows}"
}

require_client() {
  uuid="$(resolve_client_optional "$1")"
  [ -n "${uuid}" ] || fail "client $1 is missing"
  printf '%s' "${uuid}"
}

client_field() {
  kget "clients/$1" --fields "$2" --format csv --noquotes | nonempty_lines
}

assert_client_boolean() {
  actual="$(client_field "$1" "$2")"
  [ "${actual}" = "$3" ] || fail "client field $2 expected $3"
}

# The client secret as a JSON string: backslash and double quote escaped, and
# a control character refused (it cannot be written safely without jq).
secret_json_body() {
  # Counted, not captured: $(...) would strip a trailing newline.
  controls="$(printf '%s' "${CLIENT_SECRET}" | tr -d '[:print:]' | wc -c | tr -d '[:space:]')"
  [ "${controls}" = "0" ] || fail "client secret carries a control character"
  unset controls
  escaped="$(printf '%s' "${CLIENT_SECRET}" | sed 's/[\\"]/\\&/g')"
  printf '{"secret":"%s"}' "${escaped}"
  unset escaped
}

upsert_client() {
  uuid="$(resolve_client_optional "${CLIENT_ID}")"
  endpoint=clients
  action=create
  merge=""
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
    # -f turns kcadm's default merge off; keep it, as the -s-only update did.
    merge=--merge
  fi
  body="$(secret_json_body)"
  # shellcheck disable=SC2086 # merge is empty or one flag
  printf '%s' "${body}" | "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -f - ${merge} \
    -s "clientId=${CLIENT_ID}" \
    -s 'description=Read-only auditor of the realm RBAC (keycloak-role-drift CronJob, INFRA-250)' \
    -s enabled=true \
    -s publicClient=false \
    -s bearerOnly=false \
    -s standardFlowEnabled=false \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=true \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect >/dev/null 2>&1 || \
    fail "failed to reconcile ${CLIENT_ID}"
  unset body
  CLIENT_UUID="$(require_client "${CLIENT_ID}")"
}

resolve_management_client() {
  MANAGEMENT_UUID="$(require_client "${MANAGEMENT_CLIENT_ID}")"
}

management_role_id() {
  role_id="$(kget "clients/${MANAGEMENT_UUID}/roles/$1" --fields id --format csv --noquotes | nonempty_lines)"
  [ -n "${role_id}" ] || fail "${MANAGEMENT_CLIENT_ID} role $1 is missing"
  printf '%s' "${role_id}"
}

expected_roles_lines() {
  printf '%s\n' "${EXPECTED_MANAGEMENT_ROLES}" | tr ',' '\n'
}

# --- client role scope ------------------------------------------------------
# fullScopeAllowed stays false (least privilege): the token and the admin API
# only honour the realm-management roles that the client scope also carries.

scope_management_roles() {
  kget "clients/${CLIENT_UUID}/scope-mappings/clients/${MANAGEMENT_UUID}" \
    --fields name --format csv --noquotes | nonempty_lines
}

ensure_scope_mappings() {
  present="$(scope_management_roles)"
  for role in $(expected_roles_lines); do
    if ! printf '%s\n' "${present}" | grep -Fxq "${role}"; then
      role_id="$(management_role_id "${role}")"
      body="$(printf '[{"id":"%s","name":"%s"}]' "${role_id}" "${role}")"
      "${KCADM}" create "clients/${CLIENT_UUID}/scope-mappings/clients/${MANAGEMENT_UUID}" \
        --config "${ADMIN_CONFIG}" -r "${REALM}" -b "${body}" >/dev/null 2>&1 || \
        fail "failed to map ${role} into the client role scope"
      unset body role_id
    fi
  done
}

assert_exact_scope() {
  actual="$(scope_management_roles | as_set)"
  [ "${actual}" = "${EXPECTED_MANAGEMENT_ROLES}" ] || \
    fail "client ${MANAGEMENT_CLIENT_ID} role scope is not exactly ${EXPECTED_MANAGEMENT_ROLES}"
  # Emptiness checks read first and fail on a read error: an empty answer
  # from a failed call must never count as "nothing mapped".
  realm_scope="$(kget "clients/${CLIENT_UUID}/scope-mappings/realm" \
    --fields name --format csv --noquotes)" || fail "cannot read the client realm role scope"
  [ -z "$(printf '%s\n' "${realm_scope}" | as_set)" ] || fail "client realm role scope must be empty"
}

# --- service account grants -------------------------------------------------

resolve_service_account() {
  SERVICE_ACCOUNT_ID="$(kget "clients/${CLIENT_UUID}/service-account-user" \
    --fields id --format csv --noquotes | nonempty_lines)"
  SERVICE_ACCOUNT_USERNAME="$(kget "clients/${CLIENT_UUID}/service-account-user" \
    --fields username --format csv --noquotes | nonempty_lines)"
  [ -n "${SERVICE_ACCOUNT_ID}" ] || fail "service account id is empty"
  [ "${SERVICE_ACCOUNT_USERNAME}" = "service-account-${CLIENT_ID}" ] || \
    fail "unexpected service account username"
}

direct_management_roles() {
  kget "users/${SERVICE_ACCOUNT_ID}/role-mappings/clients/${MANAGEMENT_UUID}" \
    --fields name --format csv --noquotes | nonempty_lines
}

ensure_management_roles() {
  present="$(direct_management_roles)"
  for role in $(expected_roles_lines); do
    if ! printf '%s\n' "${present}" | grep -Fxq "${role}"; then
      "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${SERVICE_ACCOUNT_ID}" --cclientid "${MANAGEMENT_CLIENT_ID}" \
        --rolename "${role}" >/dev/null 2>&1 || fail "failed to grant ${role}"
    fi
  done
}

assert_exact_grants() {
  direct="$(direct_management_roles | as_set)"
  [ "${direct}" = "${EXPECTED_MANAGEMENT_ROLES}" ] || \
    fail "service account ${MANAGEMENT_CLIENT_ID} roles are not exactly ${EXPECTED_MANAGEMENT_ROLES}"
  # view-users is composite (query-users, query-groups): the effective set
  # must still be exactly the declared four, so no composite smuggles more.
  effective="$(kget "users/${SERVICE_ACCOUNT_ID}/role-mappings/clients/${MANAGEMENT_UUID}/composite" \
    --fields name --format csv --noquotes | as_set)"
  [ "${effective}" = "${EXPECTED_MANAGEMENT_ROLES}" ] || \
    fail "service account effective ${MANAGEMENT_CLIENT_ID} roles are not exactly ${EXPECTED_MANAGEMENT_ROLES}"
  # No direct role of any other client.
  mappings="$(kget "users/${SERVICE_ACCOUNT_ID}/role-mappings")" || \
    fail "cannot read the service account role mappings"
  clients="$(printf '%s\n' "${mappings}" | \
    sed -n 's/.*"client"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | as_set)"
  [ "${clients}" = "${MANAGEMENT_CLIENT_ID}" ] || \
    fail "service account holds roles of a client other than ${MANAGEMENT_CLIENT_ID}"
  realm_direct="$(kget "users/${SERVICE_ACCOUNT_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | as_set)"
  [ "${realm_direct}" = "${EXPECTED_REALM_ROLES}" ] || \
    fail "service account realm roles are not exactly ${EXPECTED_REALM_ROLES}"
  groups="$(kget "users/${SERVICE_ACCOUNT_ID}/groups" --fields id --format csv --noquotes)" || \
    fail "cannot read the service account groups"
  [ -z "$(printf '%s\n' "${groups}" | as_set)" ] || fail "service account must not belong to any group"
}

verify_client() {
  CLIENT_UUID="$(require_client "${CLIENT_ID}")"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient false
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled true
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  resolve_management_client
  assert_exact_scope
  resolve_service_account
  assert_exact_grants
}

# --- the auditor's own token ------------------------------------------------

mint_claims() {
  KC_CLI_CLIENT_SECRET="${CLIENT_SECRET}" "${KCADM}" config credentials \
    --config "${CLIENT_CONFIG}" \
    --server "${KEYCLOAK_URL}" \
    --realm "${REALM}" \
    --client "${CLIENT_ID}" >/dev/null 2>&1 || fail "auditor token mint failed"
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
  printf '%s' "${claims}"
}

verify_minted_claims() {
  claims="$(mint_claims)"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${CLIENT_ID}"'"' || \
    fail "minted token has wrong azp"
  if printf '%s' "${claims}" | grep -Eq '"realm_access"'; then
    fail "minted token carries realm roles"
  fi
  role_arrays="$(printf '%s' "${claims}" | grep -o '"roles"[[:space:]]*:' | line_count)"
  [ "${role_arrays}" = "1" ] || fail "minted token carries roles of more than one client"
  token_roles="$(printf '%s' "${claims}" | \
    sed -n 's/.*"'"${MANAGEMENT_CLIENT_ID}"'"[[:space:]]*:[[:space:]]*{[[:space:]]*"roles"[[:space:]]*:[[:space:]]*\(\[[^]]*\]\).*/\1/p' | \
    tr -d '[]" ' | tr ',' '\n' | as_set)"
  [ "${token_roles}" = "${EXPECTED_MANAGEMENT_ROLES}" ] || \
    fail "minted token ${MANAGEMENT_CLIENT_ID} roles are not exactly ${EXPECTED_MANAGEMENT_ROLES}"
  unset claims token_roles
}

# C-4 of the INFRA-219 architecture: the auditor can read the realm but can
# neither read a client secret nor write a role mapping. Both calls are made
# with the auditor's token; stdout is discarded (were the first to succeed it
# would only return this client's own secret) and the role-mapping body is an
# empty list, so even an unexpected success changes nothing in the realm.
probe_denied() {
  name="$1"
  shift
  if "$@" --config "${CLIENT_CONFIG}" -r "${REALM}" >/dev/null 2>"${PROBE_ERR}"; then
    fail "auditor token was allowed to ${name}"
  fi
  # Only a 403 proves the denial (C-4). A 401, a 5xx or a dead connection
  # proves nothing about the auditor's privilege, so it fails the job.
  if ! grep -Eq '(^|[^0-9])403([^0-9]|$)' "${PROBE_ERR}"; then
    : >"${PROBE_ERR}"
    fail "auditor probe ${name} was not denied with 403"
  fi
  : >"${PROBE_ERR}"
  printf '{"client_id":"%s","probe":"%s","denied":true,"status":"403"}\n' "${CLIENT_ID}" "${name}"
}

verify_auditor_access() {
  "${KCADM}" get roles -q first=0 -q max=1 --fields name \
    --config "${CLIENT_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
    fail "auditor token cannot read the realm roles"
  "${KCADM}" get users -q first=0 -q max=1 --fields username \
    --config "${CLIENT_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
    fail "auditor token cannot list users"
  probe_denied read-client-secret "${KCADM}" get "clients/${CLIENT_UUID}/client-secret"
  probe_denied post-role-mapping "${KCADM}" create "users/${SERVICE_ACCOUNT_ID}/role-mappings/realm" -b '[]'
  rm -f "${CLIENT_CONFIG}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    upsert_client
    progress client-reconciled
    resolve_management_client
    ensure_scope_mappings
    progress role-scope-reconciled
    resolve_service_account
    ensure_management_roles
    progress role-mapping-reconciled
    ;;
esac
verify_client
progress exact-roles-verified
verify_minted_claims
verify_auditor_access
printf '{"client_id":"%s","management_roles":"%s","present":true,"exact":true}\n' \
  "${CLIENT_ID}" "${EXPECTED_MANAGEMENT_ROLES}"
