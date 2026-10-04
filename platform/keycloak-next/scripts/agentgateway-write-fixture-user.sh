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
# MODE ensure is idempotent and drift-fixing: it creates the user only when
# missing, re-enables it if disabled, RE-APPLIES the password on every sync
# (the SC-1635/SC-1645 incident class was exactly a Keycloak-vs-1Password
# password drift), and grants the role only when missing, with a post-write
# read as the real assertion (SC-1215: kcadm can swallow server answers).
# MODE audit checks the facts without mutating (the password cannot be read
# back over the API — its application is the ensure path's job). MODE
# rollback removes the role mapping and DISABLES the user; it never deletes
# it — deleting a principal is the CTO's decision (PRINCIPALS.md rules).
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
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-write-fixture-admin.config
KCADM_OUT=/tmp/kcadm-write-fixture-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, role or user through the environment.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${ROLE_NAME}" = "agentgateway-write" ] || fail "ROLE_NAME is immutable for this reconciler"
[ "${USERNAME}" = "qa-write-sin-vinculo@e-dani.com" ] || fail "USERNAME is immutable for this reconciler"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

resolve_user_id() {
  # Exact-username search (users?username=...&exact=true): GET users excludes
  # service accounts, and exact=true rules out substring matches on other
  # names. Empty output = absent; more than one line = a realm the contract
  # does not describe, fail closed.
  ids="$(kget users -q "username=${USERNAME}" -q exact=true --fields id --format csv --noquotes 2>/dev/null | nonempty_lines)" || return 1
  case "$(printf '%s\n' "${ids}" | sed '/^[[:space:]]*$/d' | wc -l | tr -d '[:space:]')" in
    0) return 1 ;;
    1) printf '%s\n' "${ids}" | sed -n '1p' ;;
    # 2: a realm the contract does not describe. Callers fail closed on it;
    # it must never be mistaken for "absent" (which would create a user).
    *) return 2 ;;
  esac
}

user_field() {
  kget "users/${FIXTURE_USER_ID}" --fields "$1" --format csv --noquotes | nonempty_lines
}

assert_fixture_is_human_and_unaffiliated() {
  sa_client="$(user_field serviceAccountClientId)"
  case "${sa_client}" in
    ""|null) ;;
    *) fail "${USERNAME} is the service account of ${sa_client}: the fixture must be a human user" ;;
  esac
  groups="$(kget "users/${FIXTURE_USER_ID}/groups" --fields path --format csv --noquotes 2>/dev/null | nonempty_lines)" || \
    fail "the group memberships of ${USERNAME} could not be read"
  [ -z "${groups}" ] || fail "${USERNAME} belongs to a group; the reverse C2 fixture must have no groups"
}

assert_role_exists() {
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

create_user() {
  # requiredActions=[] so the scripted PKCE login of the fixture never trips
  # UPDATE_PASSWORD / VERIFY_EMAIL prompts; emailVerified=true for the same
  # reason. The reply is captured, never printed.
  if ! "${KCADM}" create users --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "username=${USERNAME}" -s "email=${USERNAME}" \
    -s enabled=true -s emailVerified=true -s 'requiredActions=[]' \
    > "${KCADM_OUT}" 2>&1; then
    fail "failed to create ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
}

apply_password() {
  # KC_CLI_PASSWORD is kcadm 26's environment default for --new-password:
  # the value reaches the server without ever entering argv. temporary is
  # left unset, which means NOT temporary (scriptable login).
  [ -n "${FIXTURE_PASSWORD:-}" ] || \
    fail "FIXTURE_PASSWORD is empty: refusing to apply or clear the fixture password"
  if ! KC_CLI_PASSWORD="${FIXTURE_PASSWORD}" "${KCADM}" set-password \
    --config "${ADMIN_CONFIG}" -r "${REALM}" --userid "${FIXTURE_USER_ID}" \
    > "${KCADM_OUT}" 2>&1; then
    fail "failed to apply the fixture password: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
}

report() {
  printf '{"realm":"%s","role":"%s","username":"%s","user_id":"%s","present":%s,"created":%s,"changed":%s}\n' \
    "${REALM}" "${ROLE_NAME}" "${USERNAME}" "$1" "$2" "$3" "$4"
}

login_admin

case "${MODE}" in
  ensure)
    # Fail before ANY mutation if the credential is missing: creating a
    # user without being able to set its password would leave a half fact.
    [ -n "${FIXTURE_PASSWORD:-}" ] || \
      fail "FIXTURE_PASSWORD is empty: refusing to reconcile the fixture without its credential"
    assert_role_exists
    changed=false
    if FIXTURE_USER_ID="$(resolve_user_id)"; then
      created=false
    else
      case $? in
        1)
          create_user
          FIXTURE_USER_ID="$(resolve_user_id)" || \
            fail "post-create assertion failed: ${USERNAME} is not resolvable by exact username after create"
          created=true
          changed=true
          ;;
        *)
          fail "the exact username ${USERNAME} does not resolve to at most one user: refusing to continue"
          ;;
      esac
    fi
    assert_fixture_is_human_and_unaffiliated
    if [ "$(user_field enabled)" != "true" ]; then
      if ! "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s enabled=true > "${KCADM_OUT}" 2>&1; then
        fail "failed to re-enable ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      fi
      [ "$(user_field enabled)" = "true" ] || \
        fail "post-update assertion failed: ${USERNAME} is still disabled after re-enable"
      changed=true
    fi
    apply_password
    if ! user_has_direct_role; then
      if ! "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${FIXTURE_USER_ID}" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
        fail "failed to map ${ROLE_NAME} to ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      fi
      user_has_direct_role || \
        fail "post-ensure assertion failed: ${ROLE_NAME} is not in the direct realm-role mappings of ${USERNAME} after add-roles"
      changed=true
    fi
    report "${FIXTURE_USER_ID}" true "${created}" "${changed}"
    ;;
  audit)
    FIXTURE_USER_ID="$(resolve_user_id)" || \
      fail "audit: ${USERNAME} does not exist or does not resolve cleanly in realm ${REALM}"
    assert_fixture_is_human_and_unaffiliated
    [ "$(user_field enabled)" = "true" ] || \
      fail "audit: ${USERNAME} is disabled"
    assert_role_exists
    user_has_direct_role || \
      fail "audit: ${USERNAME} is missing the direct mapping of ${ROLE_NAME}"
    report "${FIXTURE_USER_ID}" true false false
    ;;
  rollback)
    # Rollback is idempotent on an absent user (nothing to undo), but every
    # other abnormal state fails loud. It removes the role mapping and
    # DISABLES the user; deleting a principal is the CTO's decision.
    if FIXTURE_USER_ID="$(resolve_user_id)"; then
      :
    else
      case $? in
        1)
          report absent false false false
          exit 0
          ;;
        *)
          fail "the exact username ${USERNAME} does not resolve to at most one user: refusing to continue"
          ;;
      esac
    fi
    changed=false
    if user_has_direct_role; then
      if ! "${KCADM}" remove-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${FIXTURE_USER_ID}" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
        fail "failed to remove ${ROLE_NAME} from ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      fi
      if user_has_direct_role; then
        fail "${ROLE_NAME} remains in the direct realm-role mappings of ${USERNAME} after rollback"
      fi
      changed=true
    fi
    if [ "$(user_field enabled)" = "true" ]; then
      if ! "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s enabled=false > "${KCADM_OUT}" 2>&1; then
        fail "failed to disable ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      fi
      [ "$(user_field enabled)" = "false" ] || \
        fail "post-rollback assertion failed: ${USERNAME} is still enabled after disable"
      changed=true
    fi
    report "${FIXTURE_USER_ID}" false false "${changed}"
    ;;
esac
