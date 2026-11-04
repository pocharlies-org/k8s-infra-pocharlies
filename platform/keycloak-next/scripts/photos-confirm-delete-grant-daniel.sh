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
# Why the subject is the primary pin and not the username: the internal user
# id IS the `sub` claim every consumer binds on (dgx-messages-client.sh pins the
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
# The reconciler skeleton (identity guard, user resolution, post-ensure
# assertion, audit and rollback flow) is shared with
# agentgateway-write-grant-daniel.sh via human-role-grant-daniel-lib.sh
# (INFRA-402 duplicates check). This file keeps only its identity pins and its
# role-existence policy — the one place the two grants legitimately differ.
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
. "${0%/*}/human-role-grant-daniel-lib.sh"

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, role or user through the environment (guard_human_grant_identity
# compares against these literals).
REALM_PIN=edani
ROLE_PIN=photos-confirm-delete
USER_ID_PIN=e51253a7-c137-4c6c-9fb9-af9cecd3b147
USER_NAME_PIN=me@e-dani.com

assert_role_present() {
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

reconcile_human_grant
