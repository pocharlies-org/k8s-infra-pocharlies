#!/bin/sh
set -eu

umask 077

# SC-4304 S6 (security ruling of 03-11-2026): owns the COMPLETE direct holder
# set of the realm role agentgateway-read:hindsight-personal (realm edani) —
# the gate of /hindsight-personal and /chat-hindsight-personal (Hindsight bank
# `personal`). Decision of Dani of 03-11-2026: the personal memory is read by
# me@e-dani.com and lays84.mv@gmail.com, those two and nobody else; the other
# seven Open WebUI users do not hold it.
#
# The reviewed holder set (the four grantees of ROLES.yaml):
#   * service-account-hermes-secretaria and service-account-hermes-secretaria-
#     casa — the Hermes secretarias read the personal bank (granted by the
#     SC-4051 ruling; asserted here and re-granted if drift removed them);
#   * the two humans, pinned by their immutable Keycloak subject (the `sub`
#     every consumer binds on, OWU-80 precedent) with the username, the
#     enabled flag and human-ness cross-checked before any write.
# Every other direct holder is revoked on ensure (fail-closed exclusivity,
# SC-44 C6: group mappings are a policy violation). This is what closes the
# sidecar bypass measured on 03-11: the agentgateway-auth-proxy of the chat
# pod forwards ANY route to the gateway with the token of
# service-account-chat-agentgateway, and that SA held this role since SC-4051
# without a single consumer (measured: the only Open WebUI connection through
# the sidecar is /studio, and the gateway logs show no authorized
# /hindsight-personal traffic from the chat pod). The manual scope mapping of
# the role in the chat-agentgateway client (SC-4051) is revoked with it, so
# neither the grant nor its emission path survives.
#
# This hook never creates, edits or deletes the role (owned by the catalog,
# created by security in SC-4051 and asserted present here), never creates
# users, and never touches any other role. MODE rollback removes ONLY the two
# human grants this hook introduced; the reviewed SA holders and the closed
# chat-SA bypass are left as they are (a rollback of the feature must not
# reopen the security closure).
#
# Runs INSIDE the pinned Keycloak image, which ships no awk/jq/python
# (SC-1215): only kcadm via kget plus sed/grep/tr are invoked. No secret is
# ever printed: the output is a sanitized JSON verdict.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
ROLE_NAME="${ROLE_NAME:-agentgateway-read:hindsight-personal}"
EXPECTED_ROLE_NAME="agentgateway-read:hindsight-personal"
# The two humans: subject=id=username pairs (space-separated). The subject is
# the primary pin (measured read-only against the live realm 03-11-2026:
# e51253a7-c137-4c6c-9fb9-af9cecd3b147 = me@e-dani.com, the OWU-80 subject, and
# 66ec6f4f-5f2c-44f6-a3db-0dccba6e1748 = lays84.mv@gmail.com).
HUMAN_GRANTEE_IDS="e51253a7-c137-4c6c-9fb9-af9cecd3b147=me@e-dani.com 66ec6f4f-5f2c-44f6-a3db-0dccba6e1748=lays84.mv@gmail.com"
# The reviewed service-account holders (SC-4051): asserted present, re-granted
# if missing, never revoked by this hook.
REVIEWED_SERVICE_ACCOUNTS="service-account-hermes-secretaria,service-account-hermes-secretaria-casa"
# The chat service account lost the grant in SC-4304 S6 (sidecar bypass,
# header above). Its client's manual scope mapping is revoked with it.
REVOKED_SERVICE_ACCOUNTS="service-account-chat-agentgateway"
CHAT_CLIENT_ID="${CHAT_CLIENT_ID:-chat-agentgateway}"
EXPECTED_CHAT_CLIENT_ID="chat-agentgateway"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-hindsight-personal-grants-admin.config
KCADM_OUT=/tmp/kcadm-hindsight-personal-grants-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"

# Identity of this reconciler; the environment cannot move the pins.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${ROLE_NAME}" = "${EXPECTED_ROLE_NAME}" ] || \
  fail "ROLE_NAME is immutable for this reconciler"
[ "${CHAT_CLIENT_ID}" = "${EXPECTED_CHAT_CLIENT_ID}" ] || \
  fail "CHAT_CLIENT_ID is immutable for this reconciler"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac


assert_role_present() {
  # The role is owned by the catalog (ROLES.yaml; created by security in
  # SC-4051). Missing here means the trunk moved out from under the grants:
  # fail loud, never create the role from this hook.
  kget "roles/${ROLE_NAME}" --fields id >/dev/null 2>&1 || \
    fail "${ROLE_NAME} is missing from realm ${REALM}: owned by the catalog, refusing to create it here"
}

user_field_by_id() {
  kget "users/$1" --fields "$2" --format csv --noquotes | nonempty_lines
}

resolve_user_id_by_username() {
  # Exactly one user with this username (the SAs are singletons by convention
  # service-account-<clientId>; anything else fails closed).
  rows="$(kget users -q "username=$1" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" = "1" ] || \
    fail "expected exactly one user ${1}, found $(printf '%s\n' "${rows}" | line_count)"
  printf '%s' "${rows}"
}

allowed_holder_ids() {
  # The reviewed set: the two pinned humans (by subject) plus the two reviewed
  # SAs (resolved by username). One id per line.
  for pair in ${HUMAN_GRANTEE_IDS}; do
    printf '%s\n' "${pair%%=*}"
  done
  old_ifs="${IFS}"
  IFS=,
  for sa in ${REVIEWED_SERVICE_ACCOUNTS}; do
    IFS="${old_ifs}"
    resolve_user_id_by_username "${sa}"
    printf '\n'
    IFS=,
  done
  IFS="${old_ifs}"
}

grant_role_to_user() {
  # $1 = user id, $2 = display name for the failure message. add-roles exit
  # code alone is not trusted (SC-1215 lesson): the reply is captured for the
  # message and the post-write re-read below is the real assertion.
  if ! user_has_direct_role "$1"; then
    if ! "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      --uid "$1" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
      fail "failed to map ${ROLE_NAME} to $2: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    user_has_direct_role "$1" || \
      fail "post-ensure assertion failed: ${ROLE_NAME} is not in the direct realm-role mappings of $2 after add-roles"
    return 1
  fi
  return 0
}

user_has_direct_role() {
  kget "users/$1/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${ROLE_NAME}"
}

revoke_role_from_user() {
  if ! "${KCADM}" remove-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
    --uid "$1" --rolename "${ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
    fail "failed to remove ${ROLE_NAME} from $2: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
  if user_has_direct_role "$1"; then
    fail "${ROLE_NAME} remains in the direct realm-role mappings of $2 after revoke"
  fi
}

resolve_human() {
  # OWU-80 discipline: resolve BY SUBJECT, then cross-check username, enabled
  # and human-ness; any mismatch fails closed. Never creates users.
  id="$1"
  want="$2"
  kget "users/${id}" --fields id >/dev/null 2>&1 || \
    fail "user ${id} does not exist in realm ${REALM}: refusing to create a human user"
  username="$(user_field_by_id "${id}" username)"
  [ -n "${username}" ] || fail "user ${id} resolved with an empty username"
  [ "${username}" = "${want}" ] || \
    fail "user ${id} is ${username}, not the pinned ${want}: refusing to continue"
  [ "$(user_field_by_id "${id}" enabled)" = "true" ] || \
    fail "user ${want} is disabled: refusing to grant"
  sa_client="$(user_field_by_id "${id}" serviceAccountClientId)"
  case "${sa_client}" in
    ""|null) ;;
    *) fail "user ${id} is the service account of ${sa_client}: this hook grants to the human user only" ;;
  esac
}

assert_no_groups() {
  groups="$(kget "roles/${ROLE_NAME}/groups" --fields path --format csv --noquotes | nonempty_lines)"
  [ -z "${groups}" ] || fail "${ROLE_NAME} is mapped to a group; group role-mapping is forbidden (SC-44 C6)"
}

reconcile_holders() {
  # $1 = mutate ("1", ensure) or read-only ("", audit). Returns via global
  # `changed`: how many mappings this pass wrote (always 0 in audit).
  changed=0
  # 1. The two humans: resolve by subject, grant idempotently (audit: assert).
  for pair in ${HUMAN_GRANTEE_IDS}; do
    id="${pair%%=*}"
    name="${pair#*=}"
    resolve_human "${id}" "${name}"
    if [ "${1}" = "1" ]; then
      if ! grant_role_to_user "${id}" "${name}"; then
        changed=$((changed + 1))
      fi
    else
      user_has_direct_role "${id}" || \
        fail "audit: ${name} is missing the direct mapping of ${ROLE_NAME}"
    fi
  done
  # 2. The reviewed SAs: resolve by username, re-grant if drift removed them
  # (audit: assert).
  old_ifs="${IFS}"
  IFS=,
  for sa in ${REVIEWED_SERVICE_ACCOUNTS}; do
    IFS="${old_ifs}"
    sa_id="$(resolve_user_id_by_username "${sa}")"
    if [ "${1}" = "1" ]; then
      if ! grant_role_to_user "${sa_id}" "${sa}"; then
        changed=$((changed + 1))
      fi
    else
      user_has_direct_role "${sa_id}" || \
        fail "audit: ${sa} is missing the direct mapping of ${ROLE_NAME}"
    fi
    IFS=,
  done
  IFS="${old_ifs}"
  # 3. Exclusivity: every direct holder outside the reviewed set is revoked.
  # Bounded listing (same idiom as the read-grants hook): the reviewed set is
  # four, so max=10 makes an extra, unauthorized holder visible.
  holders="$(kget "roles/${ROLE_NAME}/users" -q first=0 -q max=10 \
    --fields id,username --format csv --noquotes | nonempty_lines)"
  allowed="$(allowed_holder_ids)"
  while IFS=, read -r hid hname; do
    [ -n "${hid}" ] || continue
    if ! printf '%s\n' "${allowed}" | grep -Fxq "${hid}"; then
      # audit mode must fail closed on an extra holder, not revoke it.
      [ "${1}" = "1" ] || \
        fail "audit: ${hname} holds ${ROLE_NAME} outside the reviewed holder set"
      revoke_role_from_user "${hid}" "${hname}"
      changed=$((changed + 1))
    fi
  done <<EOF
${holders}
EOF
  assert_no_groups
  # Post-condition of the bypass closure (SC-4304 S6, header above): the
  # revoked chat SA must not hold the role in either mode.
  old_ifs="${IFS}"
  IFS=,
  for sa in ${REVOKED_SERVICE_ACCOUNTS}; do
    IFS="${old_ifs}"
    sa_id="$(resolve_user_id_by_username "${sa}")"
    if user_has_direct_role "${sa_id}"; then
      fail "${sa} still holds ${ROLE_NAME}: the chat sidecar bypass is not closed"
    fi
    IFS=,
  done
  IFS="${old_ifs}"
}

revoke_chat_client_scope_mapping() {
  # The manual SC-4051 mapping of the role into the chat-agentgateway client
  # scope (fullScope=false): with the grant gone it is inert, but it is the
  # emission path of the bypass and is removed with it (idempotent).
  rows="$(kget clients -q "clientId=${CHAT_CLIENT_ID}" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" = "1" ] || \
    fail "expected exactly one client ${CHAT_CLIENT_ID}"
  chat_uuid="${rows}"
  if kget "clients/${chat_uuid}/scope-mappings/realm" --fields name --format csv --noquotes | \
       nonempty_lines | grep -Fxq "${ROLE_NAME}"; then
    role_id="$(kget "roles/${ROLE_NAME}" --fields id --format csv --noquotes | nonempty_lines)"
    [ -n "${role_id}" ] || fail "${ROLE_NAME} id is empty"
    body="$(printf '[{"id":"%s","name":"%s"}]' "${role_id}" "${ROLE_NAME}")"
    "${KCADM}" delete "clients/${chat_uuid}/scope-mappings/realm" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" -b "${body}" >/dev/null 2>&1 || \
      fail "failed to remove ${ROLE_NAME} from the scope of ${CHAT_CLIENT_ID}"
    if kget "clients/${chat_uuid}/scope-mappings/realm" --fields name --format csv --noquotes | \
         nonempty_lines | grep -Fxq "${ROLE_NAME}"; then
      fail "${ROLE_NAME} remains in the scope of ${CHAT_CLIENT_ID} after revoke"
    fi
    unset body role_id
    return 1
  fi
  return 0
}

report() {
  printf '{"realm":"%s","role":"%s","holders_reviewed":4,"changed":%s}\n' \
    "${REALM}" "${ROLE_NAME}" "$1"
}

login_admin
assert_role_present
case "${MODE}" in
  ensure)
    reconcile_holders 1
    scope_changed=0
    revoke_chat_client_scope_mapping || scope_changed=1
    report $((changed + scope_changed))
    ;;
  audit)
    reconcile_holders ""
    rows="$(kget clients -q "clientId=${CHAT_CLIENT_ID}" --fields id --format csv --noquotes | nonempty_lines)"
    [ "$(printf '%s\n' "${rows}" | line_count)" = "1" ] || \
      fail "expected exactly one client ${CHAT_CLIENT_ID}"
    if kget "clients/${rows}/scope-mappings/realm" --fields name --format csv --noquotes | \
         nonempty_lines | grep -Fxq "${ROLE_NAME}"; then
      fail "audit: ${ROLE_NAME} is still in the scope of ${CHAT_CLIENT_ID}"
    fi
    report 0
    ;;
  rollback)
    # Removes ONLY the two human grants this hook introduced (see header).
    # Idempotent on absent users (nothing to remove); every other abnormal
    # state fails loud.
    changed=0
    for pair in ${HUMAN_GRANTEE_IDS}; do
      id="${pair%%=*}"
      name="${pair#*=}"
      if ! kget "users/${id}" --fields id >/dev/null 2>&1; then
        continue
      fi
      resolve_human "${id}" "${name}"
      if user_has_direct_role "${id}"; then
        revoke_role_from_user "${id}" "${name}"
        changed=$((changed + 1))
      fi
    done
    report "${changed}"
    ;;
esac
