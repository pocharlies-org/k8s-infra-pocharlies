#!/bin/sh
set -eu

umask 077

# SKIRM-494 (Request de la sesión en vivo de SKIRM-484): owns EXACTLY ONE IdP
# fact — the QA fixture user of the skirmbooks SSO in realm "edani": the human
# user qa@e-dani.com exists, is enabled, holds the password of its 1Password
# item (vault k8s-pocharlies, item keycloak-next-qa, applied through the
# ExternalSecret skirmbooks-qa-fixture-user-credentials) and is a member of
# the group /skirmbooks-users — the ONLY group oauth2-proxy-skirmbooks lets
# through (allowed_groups). Without this membership the proxy answers 403 and
# the web of the fiscal software cannot be validated by QA (SKIRM-484 C3).
#
# Sister of agentgateway-write-fixture-user.sh (OWU-28-g): the fixture
# machinery (exact-username resolution, create, profile names, password
# re-application, the ensure/audit/rollback flows) is shared verbatim in
# fixture-user-common.sh; the difference is the fact granted: that hook gives
# a realm role, this one gives the group membership. No realm role beyond
# default-roles-edani (which Keycloak mints with the user itself).
#
# The group is NOT created here: /skirmbooks-users is owned by
# skirmbooks-sso.sh (PostSync wave 21, runs before this hook's wave 25).
# Missing here means the trunk moved out from under the fixture: fail loud,
# never create the group from this hook.
#
# The gestoria side needs no row from this hook: qa@e-dani.com is already
# nominal in gestoria_identity (skirmbooks-gestoria-src migration 0096,
# applied: status active, tenant skirmshop role owner — measured live
# 16-11-2026), so the SSO login passes requireTenantRole. If that row ever
# disappears the login answers no_principal/no_tenants: that is the gestoria
# repo's fact, not this hook's.
#
# The password never appears in argv, stdout or any file this hook writes:
# it reaches kcadm through the KC_CLI_PASSWORD environment of the single
# set-password invocation (kcadm 26 reads it as the default of
# --new-password), so neither the process list nor the kcadm reply capture
# can carry it. An empty FIXTURE_PASSWORD fails before any mutation.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk (SC-1215). Only
# kcadm plus sed/grep/tr/wc/rm/sleep/head are invoked; the contract test
# audits this. The verdict is a sanitized JSON line.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
USERNAME="${USERNAME:-qa@e-dani.com}"
USER_GROUP="${USER_GROUP:-/skirmbooks-users}"
# The profile names of the fixture: fixed, not secret, not switchable through
# the environment. They only have to be non-empty for the login to pass.
PROFILE_FIRST_NAME="QA"
PROFILE_LAST_NAME="Fixture"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-skirmbooks-qa-fixture-admin.config
KCADM_OUT=/tmp/kcadm-skirmbooks-qa-fixture-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"
. "${0%/*}/fixture-user-common.sh"

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, group or user through the environment.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${USERNAME}" = "qa@e-dani.com" ] || fail "USERNAME is immutable for this reconciler"
[ "${USER_GROUP}" = "/skirmbooks-users" ] || fail "USER_GROUP is immutable for this reconciler"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

assert_fixture_shape() {
  sa_client="$(user_field serviceAccountClientId)"
  case "${sa_client}" in
    ""|null) ;;
    *) fail "${USERNAME} is the service account of ${sa_client}: the fixture must be a human user" ;;
  esac
}

# The group is owned by skirmbooks-sso.sh (wave 21). GET /groups accepts no
# ?path=, so the list is matched by exact path: the path carries no commas,
# and the CSV `id,path` line is kept only where the substitution of the
# suffix fitted (sed t/d, POSIX — the image's sed included, SC-1215).
group_id_for() {
  kget groups --fields id,path --format csv --noquotes 2>/dev/null \
    | sed -e "s#,[[:space:]]*${1}[[:space:]]*\$##" -e t -e d \
    | sed -e 's/[[:space:]]*$//' | head -1
}

assert_fixture_preconditions() {
  GID="$(group_id_for "${USER_GROUP}")"
  [ -n "${GID}" ] || \
    fail "${USER_GROUP} is missing from realm ${REALM}: owned by skirmbooks-sso.sh, refusing to create it here"
}

user_is_member() {
  kget "users/${FIXTURE_USER_ID}/groups" --fields path --format csv --noquotes 2>/dev/null \
    | nonempty_lines | grep -qxF "${USER_GROUP}"
}

fixture_grant_extra() {
  if ! user_is_member; then
    # PUT, not POST: the Keycloak REST associates groups with
    # PUT /users/{uid}/groups/{gid}; kcadm `update` on that path sends the PUT
    # with an empty body, which is what fits (same as skirmbooks-sso.sh).
    if ! "${KCADM}" update "users/${FIXTURE_USER_ID}/groups/${GID}" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" > "${KCADM_OUT}" 2>&1; then
      fail "failed to put ${USERNAME} into ${USER_GROUP}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    user_is_member || \
      fail "post-ensure assertion failed: ${USERNAME} is not in ${USER_GROUP} after the membership write"
    FIXTURE_CHANGED=true
  fi
}

fixture_audit_extra() {
  assert_fixture_preconditions
  user_is_member || \
    fail "audit: ${USERNAME} is not a member of ${USER_GROUP}"
}

fixture_revoke_extra() {
  if user_is_member; then
    assert_fixture_preconditions
    if ! "${KCADM}" delete "users/${FIXTURE_USER_ID}/groups/${GID}" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" > "${KCADM_OUT}" 2>&1; then
      fail "failed to remove ${USERNAME} from ${USER_GROUP}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    if user_is_member; then
      fail "${USER_GROUP} still contains ${USERNAME} after rollback"
    fi
    FIXTURE_CHANGED=true
  fi
}

fixture_report() {
  printf '{"realm":"%s","group":"%s","username":"%s","user_id":"%s","present":%s,"created":%s,"changed":%s}\n' \
    "${REALM}" "${USER_GROUP}" "${USERNAME}" "$1" "$2" "$3" "$4"
}

login_admin

case "${MODE}" in
  ensure)   fixture_ensure ;;
  audit)    fixture_audit ;;
  rollback) fixture_rollback ;;
esac
