#!/bin/sh
set -eu

umask 077

# SC-709 / SC-1215 (mandato del VP, progreso 14062): owns EXACTLY ONE IdP fact —
# the mapping of the client role "impersonation" of the "edani-realm"
# realm-client onto the service-account user of the "admin-keycloack-server"
# client. Both the client and the mapping live in the master realm. It grants
# that one client role to that one service identity and NOTHING else.
#
# Why "edani-realm" in master and not "realm-management" in edani (SC-1215 fix,
# measured 2026-09-24 against the live IdP): the automation client
# admin-keycloack-server and its service-account user live in the MASTER realm —
# the first apply failed because "kcadm get clients -r edani -q
# clientId=admin-keycloack-server" returns 0 rows — and a user of one realm
# cannot hold client roles of another realm's realm-management, so the
# edani-side mapping the first revision asserted was unaddressable. Keycloak
# exposes each realm's realm-management roles to master-realm identities
# through that realm's realm-client "<realm>-realm" (attribute
# realm_client=true): every edani power this SA already has (manage-users,
# manage-clients, manage-realm, ...) is a role it holds on "edani-realm", and
# the measured 403 on POST /admin/realms/edani/users/<id>/impersonation is
# exactly the one role missing there — "impersonation". Granting it is the same
# privilege the mandate asked for (impersonate edani users), placed where the
# IdP actually checks it.
#
# Scope is the narrowest in this platform, on purpose:
#   * It never creates, edits or deletes the "impersonation" role itself, nor
#     any other realm-client role: those are Keycloak built-ins. The role is
#     only READ to resolve its id; if it is missing the hook fails closed.
#   * It never asserts or enforces exclusivity. "impersonation" is a shared
#     role that other admin identities may legitimately hold, so the hook adds
#     the target mapping and leaves every other user's mappings exactly as it
#     found them (unlike agentgateway-write-role, which owns an exclusive realm
#     role).
#   * It touches no client attribute, no TTL, no secret, no other grant.
#
# Why raw REST collections with fully-resolved UUIDs instead of "kcadm add-roles
# --in-client": the --in-client flag's client selector (internal id vs clientId
# alias) is version-sensitive, and a wrong reading would silently map the wrong
# client. The hook therefore resolves both the edani-realm client uuid and the
# impersonation role id by explicit lookups and POSTs/DELETEs the canonical
# admin endpoint "users/<userId>/role-mappings/clients/<clientUuid>/roles", the
# same REST collection style the read-grants and synapse-sre reconcilers use.
#
# Rollback removes ONLY the target service account's impersonation mapping (the
# role and every other holder are untouched). A git revert of this file restores
# the grant on the next PostSync; the manual rollback Job is applied by hand.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-master}"
CLIENT_ID="${CLIENT_ID:-admin-keycloack-server}"
MAPPING_CLIENT="${MAPPING_CLIENT:-edani-realm}"
ROLE_NAME="${ROLE_NAME:-impersonation}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-impersonation-admin.config
ROLE_BODY=/tmp/kcadm-impersonation-role.json

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${ROLE_BODY}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, client, role or mapping-client through the environment.
[ "${REALM}" = "master" ] || fail "REALM is immutable for this reconciler"
[ "${CLIENT_ID}" = "admin-keycloack-server" ] || fail "CLIENT_ID is immutable for this reconciler"
[ "${MAPPING_CLIENT}" = "edani-realm" ] || fail "MAPPING_CLIENT is immutable for this reconciler"
[ "${ROLE_NAME}" = "impersonation" ] || fail "ROLE_NAME is immutable for this reconciler"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
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

client_field() {
  kget "clients/$1" --fields "$2" --format csv --noquotes | nonempty_lines
}

# Resolve a client by its clientId alias to exactly one internal uuid. The
# server-side "-q clientId=" filter is a SUBSTRING match, so the alias is
# additionally matched exactly client-side. A failed lookup reports both row
# counts and the clientIds involved (SC-1215: the first apply died on a bare
# "expected exactly one client" with no way to tell 0 rows from >1).
resolve_client() {
  fuzzy="$(kget clients -q "clientId=$1" --fields id,clientId --format csv --noquotes | nonempty_lines)"
  rows="$(printf '%s\n' "${fuzzy}" | awk -F, -v want="$1" '$2 == want')"
  exact_count="$(printf '%s\n' "${rows}" | line_count)"
  if [ "${exact_count}" != "1" ]; then
    fuzzy_count="$(printf '%s\n' "${fuzzy}" | line_count)"
    fail "expected exactly one client clientId=$1 in realm ${REALM}: exact=${exact_count} [$(printf '%s\n' "${rows}" | cut -d, -f2 | tr '\n' ' ')]; substring=${fuzzy_count} [$(printf '%s\n' "${fuzzy}" | cut -d, -f2 | tr '\n' ' ')]"
  fi
  printf '%s' "${rows}" | cut -d, -f1
}

# Directly-mapped client roles of ${MAPPING_CLIENT} for the target service account.
target_mapped_role_names() {
  kget "users/${SERVICE_ACCOUNT_ID}/role-mappings/clients/${MAPPING_CLIENT_UUID}" \
    --fields name --format csv --noquotes | nonempty_lines
}

target_has_direct_role() {
  target_mapped_role_names | grep -Fxq "${ROLE_NAME}"
}

# Minimal valid body for the client-role-mappings endpoint: the role is resolved
# by id server-side, so only its id is sent. This never carries any other field.
write_role_body() {
  printf '[{"id":"%s"}]' "${ROLE_ID}" > "${ROLE_BODY}"
}

login_admin

# Target service account: the SA of the privileged admin-keycloack-server
# client, which lives in the master realm.
SA_CLIENT_UUID="$(resolve_client "${CLIENT_ID}")"
[ "$(client_field "${SA_CLIENT_UUID}" enabled)" = "true" ] || \
  fail "client ${CLIENT_ID} is disabled"
[ "$(client_field "${SA_CLIENT_UUID}" serviceAccountsEnabled)" = "true" ] || \
  fail "client ${CLIENT_ID} has no enabled service account"
SERVICE_ACCOUNT_ID="$(kget "clients/${SA_CLIENT_UUID}/service-account-user" --fields id --format csv --noquotes | nonempty_lines)"
SERVICE_ACCOUNT_USERNAME="$(kget "clients/${SA_CLIENT_UUID}/service-account-user" --fields username --format csv --noquotes | nonempty_lines)"
[ -n "${SERVICE_ACCOUNT_ID}" ] || fail "service account id is empty"
[ "${SERVICE_ACCOUNT_USERNAME}" = "service-account-${CLIENT_ID}" ] || \
  fail "resolved service account username does not match the privileged client"

# The edani realm-client in master (the "edani-realm" mirror through which this
# master-realm SA exercises its edani permissions) and its built-in
# impersonation role (read-only).
MAPPING_CLIENT_UUID="$(resolve_client "${MAPPING_CLIENT}")"
ROLE_ID="$(kget "clients/${MAPPING_CLIENT_UUID}/roles/${ROLE_NAME}" --fields id --format csv --noquotes | nonempty_lines)"
[ -n "${ROLE_ID}" ] || \
  fail "built-in client role ${ROLE_NAME} of ${MAPPING_CLIENT} is missing: refusing to create an IdP built-in"

case "${MODE}" in
  ensure)
    if target_has_direct_role; then
      printf '{"client_id":"%s","mapping_client":"%s","role":"%s","present":true,"changed":false}\n' \
        "${CLIENT_ID}" "${MAPPING_CLIENT}" "${ROLE_NAME}"
      exit 0
    fi
    write_role_body
    "${KCADM}" create "users/${SERVICE_ACCOUNT_ID}/role-mappings/clients/${MAPPING_CLIENT_UUID}/roles" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" -f "${ROLE_BODY}" >/dev/null 2>&1 || \
      fail "failed to map ${ROLE_NAME} (${MAPPING_CLIENT}) to the ${CLIENT_ID} service account"
    target_has_direct_role || \
      fail "${ROLE_NAME} did not become a direct mapping of the ${CLIENT_ID} service account"
    printf '{"client_id":"%s","mapping_client":"%s","role":"%s","present":true,"changed":true}\n' \
      "${CLIENT_ID}" "${MAPPING_CLIENT}" "${ROLE_NAME}"
    ;;
  audit)
    target_has_direct_role || \
      fail "audit: ${CLIENT_ID} service account is missing ${ROLE_NAME} (${MAPPING_CLIENT})"
    printf '{"client_id":"%s","mapping_client":"%s","role":"%s","present":true}\n' \
      "${CLIENT_ID}" "${MAPPING_CLIENT}" "${ROLE_NAME}"
    ;;
  rollback)
    if target_has_direct_role; then
      write_role_body
      "${KCADM}" delete "users/${SERVICE_ACCOUNT_ID}/role-mappings/clients/${MAPPING_CLIENT_UUID}/roles" \
        --config "${ADMIN_CONFIG}" -r "${REALM}" -f "${ROLE_BODY}" >/dev/null 2>&1 || \
        fail "failed to remove ${ROLE_NAME} (${MAPPING_CLIENT}) from the ${CLIENT_ID} service account"
      if target_has_direct_role; then
        fail "${ROLE_NAME} remains mapped to the ${CLIENT_ID} service account after rollback"
      fi
    fi
    printf '{"client_id":"%s","mapping_client":"%s","role":"%s","present":false}\n' \
      "${CLIENT_ID}" "${MAPPING_CLIENT}" "${ROLE_NAME}"
    ;;
esac
