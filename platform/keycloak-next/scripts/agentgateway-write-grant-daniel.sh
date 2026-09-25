#!/bin/sh
set -eu

umask 077

# OWU-80 (OWU-28 P6; security ruling of 2026-09-25, nota-security-owu28.md
# sections (b) and «Observación de disponibilidad»): owns EXACTLY ONE IdP
# fact — the direct realm-role mapping of "agentgateway-write" (realm "edani")
# onto the human user of Daniel, identified by his immutable Keycloak
# subject/id "e51253a7-c137-4c6c-9fb9-af9cecd3b147" (username
# "me@e-dani.com", resolved read-only against the live realm 2026-09-25). It
# grants that one role to that one user and NOTHING else.
#
# Why the subject is the primary pin and not the username: the internal user
# id IS the `sub` claim every consumer binds on (identity-bindings.yaml
# `default: dani`; dgx-messages-client.sh already pins the same CHECK_USER_ID),
# while the username is a mutable email attribute. The hook resolves the user
# BY ID and then cross-checks the username, enabled flag and human-ness; any
# mismatch fails closed. It never creates, edits or enables users (OWU-80
# limit: if the subject is absent from the realm the job fails loud).
#
# Division of ownership with agentgateway-write-role.sh (SC-44):
#   * The role itself, its service-account grant and its client scope stay
#     owned there (PostSync wave 20). This hook REQUIRES the role to already
#     exist and fails loud otherwise — it never creates, edits or deletes it.
#   * That hook's exclusivity audit was extended in the same PR to tolerate
#     exactly this pinned human holder (HUMAN_GRANTEE_ID/USERNAME there). Any
#     other user, group or service account still fails both hooks.
#   * Merge gate (binding security condition): this grant must not reach prod
#     before the ProForma guard extension of OWU-77 is merged in
#     k8s-agentgateway-pocharlies and deployed (ArgoCD agentgateway-mcp
#     Synced). The CTO governs the merge order; see the PR body and the
#     README grants section.
#
# MODE rollback removes ONLY this user's mapping of the role; the role, the
# service-account grant and every other holder are untouched. A git revert of
# this file restores the grant on the next PostSync; the manual rollback Job
# (manual/agentgateway-write-grant-daniel-rollback-job.yaml, RUNBOOK section
# 16) is applied by hand.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk (SC-1215). Only
# kcadm plus sed/grep/tr/wc/rm/sleep are invoked; the contract test audits
# this. Neither the admin password nor any token is ever printed: the output
# is a sanitized JSON verdict.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
ROLE_NAME="${ROLE_NAME:-agentgateway-write}"
USER_ID="${USER_ID:-e51253a7-c137-4c6c-9fb9-af9cecd3b147}"
USER_NAME="${USER_NAME:-me@e-dani.com}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-write-grant-daniel-admin.config
KCADM_OUT=/tmp/kcadm-write-grant-daniel-reply.txt

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${KCADM_OUT}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, role or user through the environment.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${ROLE_NAME}" = "agentgateway-write" ] || fail "ROLE_NAME is immutable for this reconciler"
[ "${USER_ID}" = "e51253a7-c137-4c6c-9fb9-af9cecd3b147" ] || fail "USER_ID is immutable for this reconciler"
[ "${USER_NAME}" = "me@e-dani.com" ] || fail "USER_NAME is immutable for this reconciler"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

nonempty_lines() {
  sed '/^[[:space:]]*$/d'
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

user_field() {
  kget "users/${USER_ID}" --fields "$1" --format csv --noquotes | nonempty_lines
}

user_exists() {
  # GET users/<id> answers 404 (kcadm exit != 0) for an unknown id.
  kget "users/${USER_ID}" --fields id >/dev/null 2>&1
}

resolve_user() {
  # OWU-80 limit: if the subject is not in the realm, fail loud. This hook
  # never creates, edits or enables users.
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

assert_role_exists() {
  # The role is owned by agentgateway-write-role.sh (PostSync wave 20, which
  # runs before this hook's wave 25). Missing here means the trunk moved out
  # from under the grant: fail loud, never create the role from this hook.
  kget "roles/${ROLE_NAME}" --fields id >/dev/null 2>&1 || \
    fail "${ROLE_NAME} is missing from realm ${REALM}: owned by agentgateway-write-role.sh, refusing to create it here"
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
    assert_role_exists
    if user_has_direct_role; then
      report true false
      exit 0
    fi
    # kcadm add-roles is the realm-role path its sibling
    # agentgateway-write-role.sh uses. Its exit code alone is not trusted
    # (SC-1215 lesson: kcadm can swallow server answers), so the reply is
    # captured for the failure message and the post-ensure read below is the
    # real assertion.
    if ! "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      --uid "${USER_ID}" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
      fail "failed to map ${ROLE_NAME} to ${USER_NAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    # Post-ensure assertion (OWU-80 spec): re-read the user's direct realm-role
    # mappings and fail loud if the grant did not land.
    user_has_direct_role || \
      fail "post-ensure assertion failed: ${ROLE_NAME} is not in the direct realm-role mappings of ${USER_NAME} after add-roles"
    report true true
    ;;
  audit)
    resolve_user
    assert_role_exists
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
