#!/bin/sh
set -eu

umask 077

# OWU-28 historia g (plan del architect, nota-architect-plan.md, APROBADO):
# owns EXACTLY ONE IdP fact — the reverse C2 fixture user of realm "edani":
# the human user qa-write-sin-vinculo@e-dani.com exists, is enabled, holds
# the password of its 1Password item (vault k8s-pocharlies, item
# keycloak-next-qa-write-sin-vinculo, applied through the ExternalSecret
# agentgateway-write-fixture-user-credentials), and holds the realm role
# "agentgateway-write". It belongs to NO group and has NO entry in
# atlassian-identity-bindings (fail-closed by absence in the agentgateway
# shim): that is the negative fixture "write without an Atlassian link".
#
# Unlike agentgateway-write-grant-daniel.sh (OWU-80), which pins a subject
# and NEVER creates users, this hook owns the creation itself: the id is
# minted by Keycloak, so the user is resolved by EXACT username
# (users?username=<exact>&exact=true), never by prefix. The username is the
# immutable pin. agentgateway-write-role.sh (wave 20, runs before this hook's
# wave 25) owns the role and its exclusivity audit, extended in the same PR
# to tolerate exactly this second human holder by username; this hook
# REQUIRES the role to already exist and fails loud otherwise.
#
# The fixture machinery (exact-username resolution, create, profile names,
# password re-application, the ensure/audit/rollback flows) lives in
# fixture-user-common.sh — extracted verbatim by SKIRM-494 when the second
# fixture (skirmbooks-qa-fixture-user.sh) cloned this hook. The mode
# semantics are the ones that file documents: ensure is idempotent and
# drift-fixing, audit mutates nothing (the password cannot be read back),
# rollback removes the role mapping and DISABLES the user, never deletes it.
#
# The password never appears in argv, stdout or any file this hook writes:
# it reaches kcadm through the KC_CLI_PASSWORD environment of the single
# set-password invocation (kcadm 26 reads it as the default of
# --new-password), so neither the process list nor the kcadm reply capture
# can carry it. An empty FIXTURE_PASSWORD fails before any mutation.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk (SC-1215). Only
# kcadm plus sed/grep/tr/wc/rm/sleep are invoked; the contract test audits
# this. The verdict is a sanitized JSON line.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
ROLE_NAME="${ROLE_NAME:-agentgateway-write}"
USERNAME="${USERNAME:-qa-write-sin-vinculo@e-dani.com}"
# The profile names of the fixture: fixed, not secret, not switchable through
# the environment. They only have to be non-empty for the login to pass.
PROFILE_FIRST_NAME="QA"
PROFILE_LAST_NAME="Fixture"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-write-fixture-admin.config
KCADM_OUT=/tmp/kcadm-write-fixture-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"
. "${0%/*}/fixture-user-common.sh"

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, role or user through the environment.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${ROLE_NAME}" = "agentgateway-write" ] || fail "ROLE_NAME is immutable for this reconciler"
[ "${USERNAME}" = "qa-write-sin-vinculo@e-dani.com" ] || fail "USERNAME is immutable for this reconciler"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

# Hook of fixture-user-common.sh: the fixture must be human AND belong to no
# group (the reverse C2 fixture is defined by its lack of group bindings).
assert_fixture_shape() {
  sa_client="$(user_field serviceAccountClientId)"
  case "${sa_client}" in
    ""|null) ;;
    *) fail "${USERNAME} is the service account of ${sa_client}: the fixture must be a human user" ;;
  esac
  groups="$(kget "users/${FIXTURE_USER_ID}/groups" --fields path --format csv --noquotes 2>/dev/null | nonempty_lines)" || \
    fail "the group memberships of ${USERNAME} could not be read"
  [ -z "${groups}" ] || fail "${USERNAME} belongs to a group; the reverse C2 fixture must have no groups"
}

assert_fixture_preconditions() {
  # The role is owned by agentgateway-write-role.sh (PostSync wave 20, which
  # runs before this hook's wave 25). Missing here means the trunk moved out
  # from under the fixture: fail loud, never create the role from this hook.
  kget "roles/${ROLE_NAME}" --fields id >/dev/null 2>&1 || \
    fail "${ROLE_NAME} is missing from realm ${REALM}: owned by agentgateway-write-role.sh, refusing to create it here"
}

user_has_direct_role() {
  kget "users/${FIXTURE_USER_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${ROLE_NAME}"
}

fixture_grant_extra() {
  if ! user_has_direct_role; then
    if ! "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      --uid "${FIXTURE_USER_ID}" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
      fail "failed to map ${ROLE_NAME} to ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    user_has_direct_role || \
      fail "post-ensure assertion failed: ${ROLE_NAME} is not in the direct realm-role mappings of ${USERNAME} after add-roles"
    FIXTURE_CHANGED=true
  fi
}

fixture_audit_extra() {
  assert_fixture_preconditions
  user_has_direct_role || \
    fail "audit: ${USERNAME} is missing the direct mapping of ${ROLE_NAME}"
}

fixture_revoke_extra() {
  if user_has_direct_role; then
    if ! "${KCADM}" remove-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      --uid "${FIXTURE_USER_ID}" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
      fail "failed to remove ${ROLE_NAME} from ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    if user_has_direct_role; then
      fail "${ROLE_NAME} remains in the direct realm-role mappings of ${USERNAME} after rollback"
    fi
    FIXTURE_CHANGED=true
  fi
}

fixture_report() {
  printf '{"realm":"%s","role":"%s","username":"%s","user_id":"%s","present":%s,"created":%s,"changed":%s}\n' \
    "${REALM}" "${ROLE_NAME}" "${USERNAME}" "$1" "$2" "$3" "$4"
}

login_admin

case "${MODE}" in
  ensure)   fixture_ensure ;;
  audit)    fixture_audit ;;
  rollback) fixture_rollback ;;
esac
