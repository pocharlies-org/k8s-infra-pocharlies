#!/bin/sh
set -eu

umask 077

# INFRA-1522 (security Request de la sesión tech-lead de INFRA-379): owns EXACTLY
# ONE IdP fact — the direct mapping of the realm role "agentgateway-read:photos"
# (realm "edani") onto the human test user of QA, identified by its immutable
# Keycloak subject/id "469f01d4-dba3-47e9-857c-13e01be14522" (username
# "qa-sso-test", created outside this repo by INFRA-561, nominal in
# PRINCIPALS.md). It grants that user and NOTHING else, and never creates the
# role: the role is owned by the wave-20 read matrix
# (agentgateway-read-grants.sh, INFRA-402 alta) — same fail-closed policy as
# photos-app-client.sh, which asserts the role and never creates it.
#
# Why: qa must drive the native app photos-ios (client photos-app, INFRA-1180)
# as a second human user. The /photos route is gated at the gateway on
# agentgateway-read:photos (k8s-agentgateway-pocharlies#247, route-level
# authorization), so without this grant the app login succeeds and every
# photos call answers 403. qa-sso-test deliberately does NOT get
# photos-confirm-delete: the delete gate stays human-only on Dani (G1 of the
# architect) — the QA app can only PROPOSE deletions.
#
# The subject is pinned by id, not username, as in the sibling single-fact
# grant hooks: the internal user id IS the `sub` claim consumers bind on, while
# the username is a mutable attribute. The hook resolves the user BY ID and
# cross-checks username, enabled flag and human-ness; any mismatch fails closed.
# It never creates, edits or enables users.
#
# MODE rollback removes ONLY this user's mapping of the role; the role itself
# stays (ROLES.yaml: ninguna entrada se borra). A git revert of this file
# restores the grant on the next PostSync.
#
# The reconciler skeleton (identity guard, user resolution, post-ensure
# assertion, audit and rollback flow) is shared with
# photos-confirm-delete-grant-daniel.sh via human-role-grant-daniel-lib.sh.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk (SC-1215). Only
# kcadm plus sed/grep/tr/wc/rm/sleep are invoked. Neither the admin password
# nor any token is ever printed: the output is a sanitized JSON verdict.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
ROLE_NAME="${ROLE_NAME:-agentgateway-read:photos}"
USER_ID="${USER_ID:-469f01d4-dba3-47e9-857c-13e01be14522}"
USER_NAME="${USER_NAME:-qa-sso-test}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-photos-read-grant-qa-admin.config
KCADM_OUT=/tmp/kcadm-photos-read-grant-qa-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"
. "${0%/*}/human-role-grant-daniel-lib.sh"

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, role or user through the environment (guard_human_grant_identity
# compares against these literals).
REALM_PIN=edani
ROLE_PIN=agentgateway-read:photos
USER_ID_PIN=469f01d4-dba3-47e9-857c-13e01be14522
USER_NAME_PIN=qa-sso-test

assert_role_present() {
  # The role's only owners are the wave-20 read matrix (creation and the
  # shared-plane grants) and ROLES.yaml (declaration). This hook requires it
  # and fails closed if its owner has not run — it must never create a role
  # owned elsewhere (photos-app-client.sh precedent).
  kget "roles/${ROLE_NAME}" --fields id >/dev/null 2>&1 || \
    fail "${ROLE_NAME} is missing from the realm: its owner reconciler (agentgateway-read-grants.sh, wave 20) has not run; this hook never creates it"
  composite="$(kget "roles/${ROLE_NAME}" --fields composite --format csv --noquotes | nonempty_lines)"
  [ "${composite}" = "false" ] || fail "${ROLE_NAME} must remain non-composite"
}

reconcile_human_grant
