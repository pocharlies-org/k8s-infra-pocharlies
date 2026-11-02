#!/bin/sh
set -eu

umask 077

# INFRA-402 (epic INFRA-379, architect ruling G1): owns EXACTLY TWO IdP facts —
# the realm role "photos-confirm-delete" (realm "edani") and its direct mapping
# onto the human user of Daniel, identified by his immutable Keycloak
# subject/id "e51253a7-c137-4c6c-9fb9-af9cecd3b147" (username "me@e-dani.com",
# same pin as agentgateway-write-grant-daniel.sh, OWU-80). It creates the role
# if absent (this hook is its only owner — the read matrix must never carry it:
# the delete gate is human-only, granting it to the shared MCP plane would let
# agents delete) and grants it to that one user and NOTHING else.
#
# Why the subject is the primary pin and not the username: the internal user id
# IS the `sub` claim every consumer binds on (dgx-messages-client.sh pins the
# same CHECK_USER_ID), while the username is a mutable email attribute. The
# hook resolves the user BY ID and then cross-checks the username, enabled flag
# and human-ness; any mismatch fails closed. It never creates, edits or
# enables users: if the subject is absent from the realm the job fails loud.
#
# The role is the human half of the delete gate (G1): the AgentGateway stamps
# the verified JWT's realm roles into x-photos-roles
# (k8s-agentgateway-pocharlies#247) and the backend (k8s-photos-mcp-pocharlies,
# server.py) is fail-closed: without photos-confirm-delete in that header,
# photos_delete only PROPOSES (pending-confirmation) even with confirm:true.
# The route itself is gated by agentgateway-read:photos (owned by
# agentgateway-read-grants.sh, wave 20) — this hook does not touch it.
#
# MODE rollback removes ONLY this user's mapping of the role; the role itself
# stays (ROLES.yaml: ninguna entrada se borra). A git revert of this file
# restores the grant on the next PostSync.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk (SC-1215). Only
# kcadm plus sed/grep/tr/wc/rm/sleep are invoked. Neither the admin password
# nor any token is ever printed: the output is a sanitized JSON verdict.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
ROLE_NAME="${ROLE_NAME:-photos-confirm-delete}"
USER_ID="${USER_ID:-e51253a7-c137-4c6c-9fb9-af9cecd3b147}"
USER_NAME="${USER_NAME:-me@e-dani.com}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-photos-confirm-delete-grant-admin.config
KCADM_OUT=/tmp/kcadm-photos-confirm-delete-grant-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, role or user through the environment.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${ROLE_NAME}" = "photos-confirm-delete" ] || fail "ROLE_NAME is immutable for this reconciler"
[ "${USER_ID}" = "e51253a7-c137-4c6c-9fb9-af9cecd3b147" ] || fail "USER_ID is immutable for this reconciler"
[ "${USER_NAME}" = "me@e-dani.com" ] || fail "USER_NAME is immutable for this reconciler"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

user_field() {
  kget "users/${USER_ID}" --fields "$1" --format csv --noquotes | nonempty_lines
}

user_exists() {
  # GET users/<id> answers 404 (kcadm exit != 0) for an unknown id.
  kget "users/${USER_ID}" --fields id >/dev/null 2>&1
}

resolve_user() {
  # Fail loud if the subject is not in the realm: this hook never creates,
  # edits or enables users (OWU-80 precedent).
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

ensure_role_exists() {
  # This hook is the role's only owner (the read matrix must never carry a
  # human delete role). Creation is idempotent and non-composite; a composite
  # with this name is a conflict and fails loud.
  if ! kget "roles/${ROLE_NAME}" --fields id >/dev/null 2>&1; then
    "${KCADM}" create roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "name=${ROLE_NAME}" \
      -s "description=Human half of the photos delete gate (INFRA-402 G1): only this role executes a photos_delete proposal on the /photos route" \
      -s composite=false >/dev/null 2>&1 || fail "failed to create ${ROLE_NAME}"
  fi
  composite="$(kget "roles/${ROLE_NAME}" --fields composite --format csv --noquotes | nonempty_lines)"
  [ "${composite}" = "false" ] || fail "${ROLE_NAME} must remain non-composite"
}

user_has_direct_role() {
  kget "users/${USER_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${ROLE_NAME}"
}

report() {
  printf '{"realm":"%s","role":"%s","user_id":"%s","username":"%s","present":%s,"changed":%s}\n' \
    "${REALM}" "${ROLE_NAME}" "${USER_ID}" "${USER_NAME}" "$1" "$2"
}

login_admin

case "${MODE}" in
  ensure)
    resolve_user
    ensure_role_exists
    if user_has_direct_role; then
      report true false
      exit 0
    fi
    # kcadm add-roles is the realm-role path its siblings use. Its exit code
    # alone is not trusted (SC-1215 lesson: kcadm can swallow server
    # answers), so the reply is captured for the failure message and the
    # post-ensure read below is the real assertion.
    if ! "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      --uid "${USER_ID}" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
      fail "failed to map ${ROLE_NAME} to ${USER_NAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    # Post-ensure assertion: re-read the user's direct realm-role mappings and
    # fail loud if the grant did not land.
    user_has_direct_role || \
      fail "post-ensure assertion failed: ${ROLE_NAME} is not in the direct realm-role mappings of ${USER_NAME} after add-roles"
    report true true
    ;;
  audit)
    resolve_user
    ensure_role_exists
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
