#!/bin/sh
set -eu

umask 077

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-agentgateway-mcp}"
ROLE_NAME="${ROLE_NAME:-agentgateway-write}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-admin.config
CLIENT_CONFIG=/tmp/kcadm-client.config

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[ "${CLIENT_ID}" = "agentgateway-mcp" ] || fail "CLIENT_ID is immutable for this reconciler"
[ "${ROLE_NAME}" = "agentgateway-write" ] || fail "ROLE_NAME is immutable for this reconciler"

nonempty_lines() {
  sed '/^[[:space:]]*$/d'
}

line_count() {
  nonempty_lines | wc -l | tr -d '[:space:]'
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

resolve_client_and_service_account() {
  client_rows="$(kget clients -q "clientId=${CLIENT_ID}" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${client_rows}" | line_count)" = "1" ] || \
    fail "expected exactly one enabled client ${CLIENT_ID}"
  CLIENT_UUID="${client_rows}"

  client_enabled="$(kget "clients/${CLIENT_UUID}" --fields enabled --format csv --noquotes | nonempty_lines)"
  [ "${client_enabled}" = "true" ] || fail "client ${CLIENT_ID} is disabled"
  service_enabled="$(kget "clients/${CLIENT_UUID}" --fields serviceAccountsEnabled --format csv --noquotes | nonempty_lines)"
  [ "${service_enabled}" = "true" ] || fail "client ${CLIENT_ID} has no enabled service account"

  SERVICE_ACCOUNT_ID="$(kget "clients/${CLIENT_UUID}/service-account-user" --fields id --format csv --noquotes | nonempty_lines)"
  SERVICE_ACCOUNT_USERNAME="$(kget "clients/${CLIENT_UUID}/service-account-user" --fields username --format csv --noquotes | nonempty_lines)"
  [ -n "${SERVICE_ACCOUNT_ID}" ] || fail "service account id is empty"
  [ "${SERVICE_ACCOUNT_USERNAME}" = "service-account-${CLIENT_ID}" ] || \
    fail "resolved service account username does not match the privileged client"
}

role_exists() {
  kget "roles/${ROLE_NAME}" --fields id >/dev/null 2>&1
}

direct_role_users() {
  kget "roles/${ROLE_NAME}/users" --fields username --format csv --noquotes | nonempty_lines
}

role_groups() {
  kget "roles/${ROLE_NAME}/groups" --fields path --format csv --noquotes | nonempty_lines
}

assert_exclusive_role_mapping() {
  expected_count="$1"
  users="$(direct_role_users)"
  groups="$(role_groups)"

  [ -z "${groups}" ] || fail "${ROLE_NAME} is mapped to a group; refusing to continue"
  if [ -n "${users}" ]; then
    while IFS= read -r username; do
      [ "${username}" = "${SERVICE_ACCOUNT_USERNAME}" ] || \
        fail "${ROLE_NAME} is mapped to an unauthorized user; refusing to continue"
    done <<EOF
${users}
EOF
  fi
  [ "$(printf '%s\n' "${users}" | line_count)" = "${expected_count}" ] || \
    fail "${ROLE_NAME} direct user assignment count is not ${expected_count}"
}

target_has_direct_role() {
  kget "users/${SERVICE_ACCOUNT_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${ROLE_NAME}"
}

user_has_effective_role() {
  user_id="$1"
  kget "users/${user_id}/role-mappings/realm/composite" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${ROLE_NAME}"
}

assert_effective_role_exclusivity() {
  expected_target="$1"

  # `GET users` excludes service-account users. Any effective mapping here is
  # therefore a human/operator grant, including grants inherited via groups or
  # composite roles.
  regular_user_ids="$(kget users -q max=1000 --fields id --format csv --noquotes | nonempty_lines)"
  if [ -n "${regular_user_ids}" ]; then
    while IFS= read -r user_id; do
      if user_has_effective_role "${user_id}"; then
        fail "${ROLE_NAME} is effective for a non-service user; refusing to continue"
      fi
    done <<EOF
${regular_user_ids}
EOF
  fi

  # Audit every service-account-enabled client. A composite or group-based
  # grant to any service identity other than the privileged client fails too.
  client_rows="$(kget clients --fields id,clientId,serviceAccountsEnabled --format csv --noquotes | nonempty_lines)"
  while IFS=, read -r client_uuid candidate_client service_accounts_enabled; do
    [ "${service_accounts_enabled}" = "true" ] || continue
    candidate_user_id="$(kget "clients/${client_uuid}/service-account-user" --fields id --format csv --noquotes | nonempty_lines)"
    if [ "${candidate_client}" = "${CLIENT_ID}" ]; then
      if [ "${expected_target}" = "1" ]; then
        user_has_effective_role "${candidate_user_id}" || \
          fail "${ROLE_NAME} is not effective for the privileged service account"
      elif user_has_effective_role "${candidate_user_id}"; then
        fail "${ROLE_NAME} remains effective for the privileged service account"
      fi
    elif user_has_effective_role "${candidate_user_id}"; then
      fail "${ROLE_NAME} is effective for another service account; refusing to continue"
    fi
  done <<EOF
${client_rows}
EOF
}

mint_client_claims() {
  client_secret="$(kget "clients/${CLIENT_UUID}/client-secret" --fields value --format csv --noquotes | nonempty_lines)"
  [ -n "${client_secret}" ] || fail "privileged client secret is empty"

  "${KCADM}" config credentials \
    --config "${CLIENT_CONFIG}" \
    --server "${KEYCLOAK_URL}" \
    --realm "${REALM}" \
    --client "${CLIENT_ID}" \
    --secret "${client_secret}" >/dev/null 2>&1 || fail "client_credentials token mint failed"
  unset client_secret

  token="$(sed -n 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "${CLIENT_CONFIG}" | head -n1)"
  [ -n "${token}" ] || fail "kcadm did not persist an access token"
  payload="$(printf '%s' "${token}" | cut -d. -f2)"
  unset token
  [ -n "${payload}" ] || fail "access token has no JWT payload"

  case $((${#payload} % 4)) in
    0) ;;
    2) payload="${payload}==" ;;
    3) payload="${payload}=" ;;
    *) fail "JWT payload has invalid base64url length" ;;
  esac
  claims="$(printf '%s' "${payload}" | tr '_-' '/+' | base64 -d 2>/dev/null)" || \
    fail "JWT payload decode failed"
  unset payload
  rm -f "${CLIENT_CONFIG}"
  printf '%s' "${claims}"
}

claims_have_role() {
  grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"agentgateway-write"'
}

verify_token_claim_present() {
  claims="$(mint_client_claims)"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"agentgateway-mcp"' || \
    fail "minted JWT azp is not the privileged client"
  printf '%s' "${claims}" | claims_have_role || \
    fail "minted privileged JWT is missing ${ROLE_NAME} in realm_access.roles"
  unset claims
}

verify_token_claim_absent() {
  claims="$(mint_client_claims)"
  if printf '%s' "${claims}" | claims_have_role; then
    fail "fresh JWT still contains ${ROLE_NAME} after rollback"
  fi
  unset claims
}

login_admin
resolve_client_and_service_account

case "${MODE}" in
  ensure)
    if ! role_exists; then
      "${KCADM}" create roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s "name=${ROLE_NAME}" \
        -s 'description=Allows explicitly gated AgentGateway MCP write tools' \
        -s composite=false >/dev/null 2>&1 || fail "failed to create ${ROLE_NAME}"
    fi

    composite="$(kget "roles/${ROLE_NAME}" --fields composite --format csv --noquotes | nonempty_lines)"
    [ "${composite}" = "false" ] || fail "${ROLE_NAME} must remain a non-composite realm role"

    if target_has_direct_role; then
      assert_exclusive_role_mapping 1
    else
      assert_exclusive_role_mapping 0
      assert_effective_role_exclusivity 0
      "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${SERVICE_ACCOUNT_ID}" --rolename "${ROLE_NAME}" >/dev/null 2>&1 || \
        fail "failed to map ${ROLE_NAME} to the privileged service account"
      assert_exclusive_role_mapping 1
    fi
    assert_effective_role_exclusivity 1
    verify_token_claim_present
    printf '{"client_id":"%s","realm_role":"%s","present":true,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAME}"
    ;;
  audit)
    if ! role_exists; then
      assert_effective_role_exclusivity 0
      verify_token_claim_absent
      printf '{"client_id":"%s","realm_role":"%s","present":false,"exclusive_service_account":true}\n' \
        "${CLIENT_ID}" "${ROLE_NAME}"
      exit 0
    fi
    assert_exclusive_role_mapping 1
    target_has_direct_role || fail "target service account is missing ${ROLE_NAME}"
    assert_effective_role_exclusivity 1
    verify_token_claim_present
    printf '{"client_id":"%s","realm_role":"%s","present":true,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAME}"
    ;;
  rollback)
    if ! role_exists; then
      assert_effective_role_exclusivity 0
      verify_token_claim_absent
      printf '{"client_id":"%s","realm_role":"%s","present":false,"exclusive_service_account":true}\n' \
        "${CLIENT_ID}" "${ROLE_NAME}"
      exit 0
    fi
    assert_exclusive_role_mapping 1
    target_has_direct_role || fail "target service account is missing ${ROLE_NAME}"
    "${KCADM}" remove-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      --uid "${SERVICE_ACCOUNT_ID}" --rolename "${ROLE_NAME}" >/dev/null 2>&1 || \
      fail "failed to remove ${ROLE_NAME} from the privileged service account"
    assert_exclusive_role_mapping 0
    assert_effective_role_exclusivity 0
    "${KCADM}" delete "roles/${ROLE_NAME}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      >/dev/null 2>&1 || fail "failed to delete ${ROLE_NAME}"
    verify_token_claim_absent
    printf '{"client_id":"%s","realm_role":"%s","present":false,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAME}"
    ;;
  *)
    fail "MODE must be ensure, audit, or rollback"
    ;;
esac
