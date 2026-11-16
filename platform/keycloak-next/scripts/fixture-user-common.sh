#!/bin/sh
# Shared fixture-user machinery of the platform/keycloak-next PostSync hooks
# that mint a human QA fixture (agentgateway-write-fixture-user.sh, OWU-28-g,
# and skirmbooks-qa-fixture-user.sh, SKIRM-494). Sourced, never executed,
# AFTER kc-admin-common.sh (it uses fail/nonempty_lines/kget). Extracted by
# SKIRM-494 when the second fixture cloned the first: the CI duplicados guard
# says extract the copy to a shared function, never fork it — the bodies here
# are the OWU-28-g originals, byte for byte.
#
# The sourcing hook must define BEFORE calling the flows:
#   MODE, REALM, USERNAME, PROFILE_FIRST_NAME, PROFILE_LAST_NAME,
#   KCADM, ADMIN_CONFIG, KCADM_OUT
# and the hook's own facts as functions:
#   assert_fixture_preconditions  ensure: the source of the grant exists
#                                 (the role / the group) — never created here
#   assert_fixture_shape          the user is a human and has the shape the
#                                 fixture contract demands
#   fixture_grant_extra           ensure: grant what is missing (post-read
#                                 included); sets FIXTURE_CHANGED=true on a write
#   fixture_audit_extra           audit: read-only checks of the grant
#   fixture_revoke_extra          rollback: remove the grant; sets
#                                 FIXTURE_CHANGED=true on a write
#   fixture_report <id> <present> <created> <changed>   the JSON verdict
#
# Invariants the flows keep (OWU-28-g lineage): the id is minted by Keycloak,
# so the user is resolved by EXACT username (users?username=<exact>&exact=true),
# never by prefix; an ambiguous exact username fails closed and never creates;
# the password is RE-APPLIED on every sync (SC-1635/SC-1645: Keycloak must
# never drift from 1Password) and reaches kcadm only as the KC_CLI_PASSWORD
# environment of one call — never argv, never stdout; every write is followed
# by a post-read as the real assertion (SC-1215); rollback never deletes the
# principal — deleting one is the CTO's decision (PRINCIPALS.md rules).
#
# Runs INSIDE the pinned Keycloak image, which ships no awk (SC-1215): only
# kcadm plus sed/grep/tr/wc/rm/sleep are invoked.

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

create_user() {
  # requiredActions=[] so the scripted PKCE login of the fixture never trips
  # UPDATE_PASSWORD / VERIFY_EMAIL prompts; emailVerified=true for the same
  # reason; the profile names keep it off UPDATE_PROFILE. The reply is
  # captured, never printed.
  if ! "${KCADM}" create users --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "username=${USERNAME}" -s "email=${USERNAME}" \
    -s enabled=true -s emailVerified=true -s 'requiredActions=[]' \
    -s "firstName=${PROFILE_FIRST_NAME}" -s "lastName=${PROFILE_LAST_NAME}" \
    > "${KCADM_OUT}" 2>&1; then
    fail "failed to create ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
}

profile_names_match() {
  [ "$(user_field firstName)" = "${PROFILE_FIRST_NAME}" ] && \
    [ "$(user_field lastName)" = "${PROFILE_LAST_NAME}" ]
}

apply_profile_names() {
  # Called by ensure only when the names differ, so a sync that finds them
  # set writes nothing. The post-write read is the assertion (SC-1215).
  if ! "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "firstName=${PROFILE_FIRST_NAME}" -s "lastName=${PROFILE_LAST_NAME}" \
    > "${KCADM_OUT}" 2>&1; then
    fail "failed to set the profile names of ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
  profile_names_match || \
    fail "post-update assertion failed: ${USERNAME} does not carry firstName=${PROFILE_FIRST_NAME} and lastName=${PROFILE_LAST_NAME}"
}

assert_profile_names_present() {
  # Audit reads presence only: a name Keycloak does not hold (empty, or the
  # null token of kcadm) sends the login to Update Account Information.
  for field in firstName lastName; do
    case "$(user_field "${field}")" in
      ""|null) fail "audit: ${USERNAME} has no ${field}: the login would stop at Update Account Information" ;;
    esac
  done
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

fixture_ensure() {
  # Fail before ANY mutation if the credential is missing: creating a
  # user without being able to set its password would leave a half fact.
  [ -n "${FIXTURE_PASSWORD:-}" ] || \
    fail "FIXTURE_PASSWORD is empty: refusing to reconcile the fixture without its credential"
  assert_fixture_preconditions
  FIXTURE_CHANGED=false
  if FIXTURE_USER_ID="$(resolve_user_id)"; then
    FIXTURE_CREATED=false
  else
    case $? in
      1)
        create_user
        FIXTURE_USER_ID="$(resolve_user_id)" || \
          fail "post-create assertion failed: ${USERNAME} is not resolvable by exact username after create"
        FIXTURE_CREATED=true
        FIXTURE_CHANGED=true
        ;;
      *)
        fail "the exact username ${USERNAME} does not resolve to at most one user: refusing to continue"
        ;;
    esac
  fi
  assert_fixture_shape
  if [ "$(user_field enabled)" != "true" ]; then
    if ! "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s enabled=true > "${KCADM_OUT}" 2>&1; then
      fail "failed to re-enable ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    [ "$(user_field enabled)" = "true" ] || \
      fail "post-update assertion failed: ${USERNAME} is still disabled after re-enable"
    FIXTURE_CHANGED=true
  fi
  if ! profile_names_match; then
    apply_profile_names
    FIXTURE_CHANGED=true
  fi
  apply_password
  fixture_grant_extra
  fixture_report "${FIXTURE_USER_ID}" true "${FIXTURE_CREATED}" "${FIXTURE_CHANGED}"
}

fixture_audit() {
  FIXTURE_USER_ID="$(resolve_user_id)" || \
    fail "audit: ${USERNAME} does not exist or does not resolve cleanly in realm ${REALM}"
  assert_fixture_shape
  [ "$(user_field enabled)" = "true" ] || \
    fail "audit: ${USERNAME} is disabled"
  assert_profile_names_present
  fixture_audit_extra
  fixture_report "${FIXTURE_USER_ID}" true false false
}

fixture_rollback() {
  # Rollback is idempotent on an absent user (nothing to undo), but every
  # other abnormal state fails loud. It removes the grant and DISABLES the
  # user; deleting a principal is the CTO's decision.
  if FIXTURE_USER_ID="$(resolve_user_id)"; then
    :
  else
    case $? in
      1)
        fixture_report absent false false false
        exit 0
        ;;
      *)
        fail "the exact username ${USERNAME} does not resolve to at most one user: refusing to continue"
        ;;
    esac
  fi
  FIXTURE_CHANGED=false
  fixture_revoke_extra
  if [ "$(user_field enabled)" = "true" ]; then
    if ! "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s enabled=false > "${KCADM_OUT}" 2>&1; then
      fail "failed to disable ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    [ "$(user_field enabled)" = "false" ] || \
      fail "post-rollback assertion failed: ${USERNAME} is still enabled after disable"
    FIXTURE_CHANGED=true
  fi
  fixture_report "${FIXTURE_USER_ID}" false false "${FIXTURE_CHANGED}"
}
