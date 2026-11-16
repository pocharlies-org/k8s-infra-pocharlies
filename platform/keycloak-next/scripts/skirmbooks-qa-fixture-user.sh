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
# Sister of agentgateway-write-fixture-user.sh (OWU-28-g) and
# openwebui-ios-client.sh (OWU-116), which mint their fixture the same way;
# the difference is the fact granted: those give a realm role or the
# /edani-users group, this one gives /skirmbooks-users. No realm role beyond
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
# MODE ensure is idempotent and drift-fixing: creates the user only when
# missing, re-enables it if disabled, sets firstName/lastName when they differ
# (Keycloak 26's default profile requires both for the "user" role; without
# them the login is sent to "Update Account Information" and cannot finish —
# OWU-76), RE-APPLIES the password on every sync (SC-1635/SC-1645: Keycloak
# must never drift from 1Password), and grants the group membership only when
# missing, with a post-write read as the real assertion (SC-1215).
# MODE audit checks the facts without mutating (the password cannot be read
# back over the API — its application is the ensure path's job).
# MODE rollback removes the group membership and DISABLES the user; it never
# deletes it — deleting a principal is the CTO's decision (PRINCIPALS.md).
#
# The password never appears in argv, stdout or any file this hook writes: it
# reaches kcadm through the KC_CLI_PASSWORD environment of the single
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

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, group or user through the environment.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${USERNAME}" = "qa@e-dani.com" ] || fail "USERNAME is immutable for this reconciler"
[ "${USER_GROUP}" = "/skirmbooks-users" ] || fail "USER_GROUP is immutable for this reconciler"
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
  case "$(printf '%s\n' "${ids}" | line_count)" in
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

assert_fixture_is_human() {
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

assert_group_exists() {
  GID="$(group_id_for "${USER_GROUP}")"
  [ -n "${GID}" ] || \
    fail "${USER_GROUP} is missing from realm ${REALM}: owned by skirmbooks-sso.sh, refusing to create it here"
}

user_is_member() {
  kget "users/${FIXTURE_USER_ID}/groups" --fields path --format csv --noquotes 2>/dev/null \
    | nonempty_lines | grep -qxF "${USER_GROUP}"
}

create_user() {
  # requiredActions=[] so the scripted login of the fixture never trips
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

grant_membership() {
  # PUT, not POST: the Keycloak REST associates groups with
  # PUT /users/{uid}/groups/{gid}; kcadm `update` on that path sends the PUT
  # with an empty body, which is what fits (same as skirmbooks-sso.sh).
  if ! "${KCADM}" update "users/${FIXTURE_USER_ID}/groups/${GID}" \
    --config "${ADMIN_CONFIG}" -r "${REALM}" > "${KCADM_OUT}" 2>&1; then
    fail "failed to put ${USERNAME} into ${USER_GROUP}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
  user_is_member || \
    fail "post-ensure assertion failed: ${USERNAME} is not in ${USER_GROUP} after the membership write"
}

revoke_membership() {
  if ! "${KCADM}" delete "users/${FIXTURE_USER_ID}/groups/${GID}" \
    --config "${ADMIN_CONFIG}" -r "${REALM}" > "${KCADM_OUT}" 2>&1; then
    fail "failed to remove ${USERNAME} from ${USER_GROUP}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
  if user_is_member; then
    fail "${USER_GROUP} still contains ${USERNAME} after rollback"
  fi
}

report() {
  printf '{"realm":"%s","group":"%s","username":"%s","user_id":"%s","present":%s,"created":%s,"changed":%s}\n' \
    "${REALM}" "${USER_GROUP}" "${USERNAME}" "$1" "$2" "$3" "$4"
}

login_admin

case "${MODE}" in
  ensure)
    # Fail before ANY mutation if the credential is missing: creating a
    # user without being able to set its password would leave a half fact.
    [ -n "${FIXTURE_PASSWORD:-}" ] || \
      fail "FIXTURE_PASSWORD is empty: refusing to reconcile the fixture without its credential"
    assert_group_exists
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
    assert_fixture_is_human
    if [ "$(user_field enabled)" != "true" ]; then
      if ! "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s enabled=true > "${KCADM_OUT}" 2>&1; then
        fail "failed to re-enable ${USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      fi
      [ "$(user_field enabled)" = "true" ] || \
        fail "post-update assertion failed: ${USERNAME} is still disabled after re-enable"
      changed=true
    fi
    if ! profile_names_match; then
      apply_profile_names
      changed=true
    fi
    apply_password
    if ! user_is_member; then
      grant_membership
      changed=true
    fi
    report "${FIXTURE_USER_ID}" true "${created}" "${changed}"
    ;;
  audit)
    FIXTURE_USER_ID="$(resolve_user_id)" || \
      fail "audit: ${USERNAME} does not exist or does not resolve cleanly in realm ${REALM}"
    assert_fixture_is_human
    [ "$(user_field enabled)" = "true" ] || \
      fail "audit: ${USERNAME} is disabled"
    assert_profile_names_present
    assert_group_exists
    user_is_member || \
      fail "audit: ${USERNAME} is not a member of ${USER_GROUP}"
    report "${FIXTURE_USER_ID}" true false false
    ;;
  rollback)
    # Rollback is idempotent on an absent user (nothing to undo), but every
    # other abnormal state fails loud. It removes the group membership and
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
    if user_is_member; then
      assert_group_exists
      revoke_membership
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
