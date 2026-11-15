#!/bin/sh
# human-role-grant-daniel-lib.sh — shared reconciler skeleton of the pinned
# human-role grants onto Daniel's user: agentgateway-write-grant-daniel.sh
# (OWU-80) and photos-confirm-delete-grant-daniel.sh (INFRA-402 G1). Both
# grant EXACTLY ONE realm role to the same immutable subject and differ only
# in the role-existence policy, which stays in each script.
#
# Sourced, never executed; definitions only (same rule as
# keycloak-reconcile-lib.sh). kc-admin-common.sh must be sourced FIRST: this
# file builds on fail/nonempty_lines/login_admin/kget and must never copy them.
#
# The sourcing script defines BEFORE sourcing this file:
#   the kc-admin-common.sh requirements (KCADM, KEYCLOAK_URL, REALM,
#   ADMIN_CONFIG, optional KCADM_TMP_FILES) plus MODE, ROLE_NAME, USER_ID,
#   USER_NAME, KCADM_OUT and the literal pins REALM_PIN, ROLE_PIN, USER_ID_PIN,
#   USER_NAME_PIN — the identity this reconciler refuses to be pointed at
#   (plain assignments, never ${VAR:-default}: the environment cannot move
#   them, same guarantee the per-script literals gave before extraction).
# And the function assert_role_present(): the role-existence policy is NOT
# shared — agentgateway-write requires the role owned by
# agentgateway-write-role.sh; photos-confirm-delete creates its own. Its only
# contract is: return 0 when the role is usable, fail loud otherwise.
# Then it calls reconcile_human_grant.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk/jq/python
# (SC-1215): only kcadm via kget plus sed/grep/tr are invoked here.

guard_human_grant_identity() {
  [ "${REALM}" = "${REALM_PIN}" ] || fail "REALM is immutable for this reconciler"
  [ "${ROLE_NAME}" = "${ROLE_PIN}" ] || fail "ROLE_NAME is immutable for this reconciler"
  [ "${USER_ID}" = "${USER_ID_PIN}" ] || fail "USER_ID is immutable for this reconciler"
  [ "${USER_NAME}" = "${USER_NAME_PIN}" ] || fail "USER_NAME is immutable for this reconciler"
  case "${MODE}" in
    ensure|audit|rollback) ;;
    *) fail "MODE must be ensure, audit, or rollback" ;;
  esac
}

user_field() {
  kget "users/${USER_ID}" --fields "$1" --format csv --noquotes | nonempty_lines
}

user_exists() {
  # GET users/<id> answers 404 (kcadm exit != 0) for an unknown id.
  kget "users/${USER_ID}" --fields id >/dev/null 2>&1
}

resolve_user() {
  # OWU-80 limit: if the subject is not in the realm, fail loud. These hooks
  # never create, edit or enable users.
  user_exists || fail "user ${USER_ID} does not exist in realm ${REALM}: refusing to create a human user"
  username="$(user_field username)"
  [ -n "${username}" ] || fail "user ${USER_ID} resolved with an empty username"
  [ "${username}" = "${USER_NAME}" ] || \
    fail "user ${USER_ID} is ${username}, not the pinned ${USER_NAME}: refusing to continue"
  [ "$(user_field enabled)" = "true" ] || \
    fail "user ${USER_NAME} is disabled: refusing to grant"
  sa_client="$(user_field serviceAccountClientId)"
  case "${sa_client}" in
    ""|null) ;;
    *) fail "user ${USER_ID} is the service account of ${sa_client}: this hook grants to the human user only" ;;
  esac
}

user_has_direct_role() {
  kget "users/${USER_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${ROLE_NAME}"
}

report() {
  printf '{"realm":"%s","role":"%s","user_id":"%s","username":"%s","present":%s,"changed":%s}\n' \
    "${REALM}" "${ROLE_NAME}" "${USER_ID}" "${USER_NAME}" "$1" "$2"
}

reconcile_human_grant() {
  guard_human_grant_identity
  login_admin
  case "${MODE}" in
    ensure)
      resolve_user
      assert_role_present
      if user_has_direct_role; then
        report true false
        exit 0
      fi
      # kcadm add-roles is the realm-role path the sibling role hooks use. Its
      # exit code alone is not trusted (SC-1215 lesson: kcadm can swallow
      # server answers), so the reply is captured for the failure message and
      # the post-ensure read below is the real assertion.
      if ! "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${USER_ID}" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
        fail "failed to map ${ROLE_NAME} to ${USER_NAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      fi
      # Post-ensure assertion (OWU-80 spec): re-read the user's direct
      # realm-role mappings and fail loud if the grant did not land.
      user_has_direct_role || \
        fail "post-ensure assertion failed: ${ROLE_NAME} is not in the direct realm-role mappings of ${USER_NAME} after add-roles"
      report true true
      ;;
    audit)
      resolve_user
      assert_role_present
      user_has_direct_role || \
        fail "audit: ${USER_NAME} is missing the direct mapping of ${ROLE_NAME}"
      report true false
      ;;
    rollback)
      # Rollback is idempotent on a deleted user (nothing to remove), but every
      # other abnormal state fails loud.
      if ! user_exists; then
        report false false
        exit 0
      fi
      resolve_user
      if user_has_direct_role; then
        if ! "${KCADM}" remove-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
          --uid "${USER_ID}" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
          fail "failed to remove ${ROLE_NAME} from ${USER_NAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
        fi
        if user_has_direct_role; then
          fail "${ROLE_NAME} remains in the direct realm-role mappings of ${USER_NAME} after rollback"
        fi
        report false true
      else
        report false false
      fi
      ;;
  esac
}
