#!/bin/sh
set -eu

umask 077

# Dedicated confidential client of the Hermes `enviar` plugin (INFRA-676, P4b
# of INFRA-480): the ONLY identity that may send or delete a Gmail draft
# through AgentGateway /workspace. Its service account holds exactly TWO realm
# roles: the shared route role agentgateway-read:workspace (the shim needs it
# to reach the route) and agentgateway-write:workspace-envio (the gateway CEL
# rule behind gmail_send, gmail_forward, gmail_send_draft and
# gmail_delete_draft, k8s-agentgateway-pocharlies#186). Nothing else from the
# agentgateway-read/write families, and never the bare agentgateway-write.
#
# Ownership of the pieces this hook depends on, all earlier in the sync:
#   - agentgateway-write:workspace-envio is CREATED by agentgateway-domain-roles
#     (wave 19), which also fails the sync if anyone but
#     service-account-hermes-enviar holds it;
#   - agentgateway-read:workspace is owned by agentgateway-read-grants (wave
#     20), whose holder allowlist reviews service-account-hermes-enviar.
# This hook only VERIFIES both roles, creates/updates the client, maps the two
# roles into the client role scope, grants them to the service account,
# converges fullScopeAllowed=false and verifies the minted token. It never
# creates or deletes a role.
#
# The client SECRET is deliberately not managed here (same rule as
# jarvis-echo-client.sh): Keycloak generates it on creation, and a devops step
# AFTER the sync reads it through the admin API and writes it to the
# 1Password item hermes-kc-enviar (field client_secret), from where the
# ExternalSecret hermes-kc-secretarias carries it to Hermes (RUNBOOK section
# 13). The token-mint verification reads the current secret through the admin
# API (GET, never rotated) and never prints it.
#
# fullScopeAllowed=false is the owned steady state (INFRA-45 pattern; the
# measured behavior is that with the flag off the token carries exactly the
# roles in the client role scope). Unlike jarvis-echo (a live client adopted
# with the flag true, whose Alexa skill must never lose its token), this
# client is born here and has no consumer until the Hermes chart lands, so
# there is no auto-restore path: the create path sets the flag false from the
# start, a drifted true is converged to false only AFTER both roles are in the
# client scope, and an off-matrix token fails closed with the flag left false.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-hermes-enviar}"
READ_ROLE_NAME="${READ_ROLE_NAME:-agentgateway-read:workspace}"
WRITE_ROLE_NAME="${WRITE_ROLE_NAME:-agentgateway-write:workspace-envio}"
EXPECTED_READ_ROLE_NAME="agentgateway-read:workspace"
EXPECTED_WRITE_ROLE_NAME="agentgateway-write:workspace-envio"
# Space-separated reviewed set, and its sorted comma form (the shape
# token_realm_roles prints) for the exact token comparison.
REVIEWED_ROLES="${EXPECTED_READ_ROLE_NAME} ${EXPECTED_WRITE_ROLE_NAME}"
EXPECTED_TOKEN_ROLES="agentgateway-read:workspace,agentgateway-write:workspace-envio"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-hermes-enviar-admin.config
CLIENT_CONFIG=/tmp/kcadm-hermes-enviar-client.config

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

# Pure helpers (fail, progress, login_admin, kget, client/mapper/SA lookups,
# mint, token_realm_roles) come from the shared reconcile library; policy —
# the guards below, the reviewed roles, the scope bounds — stays here.
. "$(dirname "$0")/keycloak-reconcile-lib.sh"

[ "${CLIENT_ID}" = "hermes-enviar" ] || fail "unsupported immutable client"
[ "${READ_ROLE_NAME}" = "${EXPECTED_READ_ROLE_NAME}" ] || \
  fail "READ_ROLE_NAME is immutable; review this reconciler, the read-grants holder allowlist and the gateway CEL together"
[ "${WRITE_ROLE_NAME}" = "${EXPECTED_WRITE_ROLE_NAME}" ] || \
  fail "WRITE_ROLE_NAME is immutable; review this reconciler, the domain-roles allowlist and the gateway CEL together"
[ "${MAPPER_NAME}" = "aud-mcp" ] || fail "MAPPER_NAME is immutable"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit or rollback" ;;
esac

upsert_client() {
  # Neither branch carries a secret: create lets Keycloak generate one, and
  # update must never overwrite the secret the Hermes plugin authenticates
  # with. The create path sets fullScopeAllowed=false from the start; the
  # update path leaves the flag to ensure_fullscope_off. Service account only:
  # no standard, implicit or password flow, and no redirect URI is ever set.
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    "${KCADM}" update "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "clientId=${CLIENT_ID}" \
      -s enabled=true \
      -s publicClient=false \
      -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false \
      -s implicitFlowEnabled=false \
      -s serviceAccountsEnabled=true \
      -s protocol=openid-connect >/dev/null 2>&1 || \
      fail "failed to reconcile ${CLIENT_ID}"
  else
    "${KCADM}" create clients --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "clientId=${CLIENT_ID}" \
      -s enabled=true \
      -s publicClient=false \
      -s standardFlowEnabled=false \
      -s directAccessGrantsEnabled=false \
      -s implicitFlowEnabled=false \
      -s serviceAccountsEnabled=true \
      -s fullScopeAllowed=false \
      -s protocol=openid-connect >/dev/null 2>&1 || \
      fail "failed to reconcile ${CLIENT_ID}"
  fi
  CLIENT_UUID="$(require_client)"
}

verify_roles() {
  # Both roles are owned by earlier hooks; a missing one means that hook has
  # not run for this commit, never a reason to create it here.
  kget "roles/${READ_ROLE_NAME}" --fields id >/dev/null 2>&1 || \
    fail "${READ_ROLE_NAME} is missing; the agentgateway-read-grants hook owns it"
  kget "roles/${WRITE_ROLE_NAME}" --fields id >/dev/null 2>&1 || \
    fail "${WRITE_ROLE_NAME} is missing; the agentgateway-domain-roles hook owns it"
  for role in ${REVIEWED_ROLES}; do
    composite="$(kget "roles/${role}" --fields composite --format csv --noquotes | nonempty_lines)"
    [ "${composite}" = "false" ] || fail "${role} must remain non-composite"
  done
}

assert_send_role_exclusive() {
  # agentgateway-write:workspace-envio is the permission to send mail: before
  # this hook grants it, its holders may only be our own service account (the
  # domain-roles hook asserts the same on every sync; this is the check that
  # runs right before the grant). Bounded listing: the one reviewed holder
  # plus two rows exposes any violation. The shared read role is NOT asserted
  # here: it has other reviewed holders, owned by agentgateway-read-grants.
  users="$(kget "roles/${WRITE_ROLE_NAME}/users" -q first=0 -q max=3 \
    --fields username --format csv --noquotes | nonempty_lines)"
  groups="$(kget "roles/${WRITE_ROLE_NAME}/groups" -q first=0 -q max=2 \
    --fields path --format csv --noquotes | nonempty_lines)"
  [ -z "${groups}" ] || fail "${WRITE_ROLE_NAME} is mapped to a group"
  if [ -n "${users}" ]; then
    while IFS= read -r username; do
      [ "${username}" = "service-account-${CLIENT_ID}" ] || \
        fail "${WRITE_ROLE_NAME} has an unauthorized user"
    done <<EOF
${users}
EOF
  fi
}

assert_scope_within() {
  # The client role scope is EXACTLY the reviewed roles: an extra mapping
  # widens the matrix the moment the service account is granted that role
  # (SC-100 defect 6 family). Additive reconciliation never removes, so an
  # unexpected entry fails closed before anything else is mutated.
  current="$(kget "clients/${CLIENT_UUID}/scope-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines)"
  if [ -n "${current}" ]; then
    while IFS= read -r name; do
      case " ${REVIEWED_ROLES} " in
        *" ${name} "*) ;;
        *) fail "client role scope has unexpected role ${name}; it widens the reviewed matrix" ;;
      esac
    done <<EOF
${current}
EOF
  fi
}

ensure_role_scope_mapping() {
  assert_scope_within
  for role in ${REVIEWED_ROLES}; do
    if ! role_scope_has_direct_role "${role}"; then
      role_id="$(kget "roles/${role}" --fields id --format csv --noquotes | nonempty_lines)"
      [ -n "${role_id}" ] || fail "${role} id is empty"
      role_body="$(printf '[{"id":"%s","name":"%s"}]' "${role_id}" "${role}")"
      "${KCADM}" create "clients/${CLIENT_UUID}/scope-mappings/realm" \
        --config "${ADMIN_CONFIG}" -r "${REALM}" -b "${role_body}" >/dev/null 2>&1 || \
        fail "failed to map ${role} into the client role scope"
      unset role_body role_id
    fi
    role_scope_has_direct_role "${role}" || fail "client role scope is missing ${role}"
  done
}

assert_reviewed_roles() {
  # The service account may hold exactly the reviewed pair from the
  # agentgateway-read/write families. The bare umbrella role, any other write
  # domain (workspace-borrador included: that is another identity's role) and
  # any sibling read route all fail closed.
  held="$(service_account_realm_roles | grep -E '^agentgateway-(read|write)' || true)"
  for role in ${held}; do
    case " ${REVIEWED_ROLES} " in
      *" ${role} "*) ;;
      *) fail "service account holds an unreviewed AgentGateway role: ${role}" ;;
    esac
  done
  for role in ${REVIEWED_ROLES}; do
    printf '%s\n' "${held}" | grep -Fxq "${role}" || fail "service account is missing ${role}"
  done
}

ensure_role_mapping() {
  for role in ${REVIEWED_ROLES}; do
    if ! target_has_direct_role "${role}"; then
      "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${SERVICE_ACCOUNT_ID}" --rolename "${role}" >/dev/null 2>&1 || \
        fail "failed to map ${role}"
    fi
    target_has_direct_role "${role}" || fail "direct realm role missing: ${role}"
  done
  assert_reviewed_roles
}

fullscope_value() {
  client_field "${CLIENT_UUID}" fullScopeAllowed
}

mint_claims() {
  # The secret is read through the admin API (GET, never rotated, never
  # printed) and handed to the library mint.
  client_secret="$(client_secret_via_admin "${CLIENT_UUID}")"
  [ -n "${client_secret}" ] || fail "client secret is empty for ${CLIENT_ID}"
  mint_claims_with_secret "${client_secret}" "client_credentials token mint failed for ${CLIENT_ID}"
  unset client_secret
}

verify_exact_token() {
  # The reviewed pair travels through the client role scope ALONE (flag off):
  # EXACT, never a subset, so a role someone added to the service account
  # fails here even if both reviewed roles are present. The bare
  # agentgateway-write gets its own message: it would open every write
  # domain, and it is the one role this client must never carry.
  claims="$(mint_claims)" || fail "minted ${CLIENT_ID} token could not be obtained"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${CLIENT_ID}"'"' || \
    fail "minted token has wrong azp"
  printf '%s' "${claims}" | grep -Fq "${AGENTGATEWAY_AUDIENCE}" || fail "minted token is missing the gateway audience"
  if printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"agentgateway-write"'; then
    fail "minted token contains a forbidden agentgateway-write role"
  fi
  actual="$(printf '%s' "${claims}" | token_realm_roles)"
  [ -n "${actual}" ] || fail "minted token has no realm_access roles claim"
  [ "${actual}" = "${EXPECTED_TOKEN_ROLES}" ] || \
    fail "minted ${CLIENT_ID} token realm roles are not exactly ${EXPECTED_TOKEN_ROLES}"
  unset claims actual
}

ensure_fullscope_off() {
  # Both roles are already in the client role scope and granted (the caller's
  # order), so turning the flag off cannot drop them from the token. In steady
  # state (flag already false) nothing is mutated.
  current="$(fullscope_value)"
  case "${current}" in
    false) ;;
    true)
      "${KCADM}" update "clients/${CLIENT_UUID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s fullScopeAllowed=false >/dev/null 2>&1 || \
        fail "failed to set fullScopeAllowed=false on ${CLIENT_ID}"
      [ "$(fullscope_value)" = "false" ] || \
        fail "fullScopeAllowed did not become false on ${CLIENT_ID}"
      ;;
    *) fail "unexpected fullScopeAllowed value for ${CLIENT_ID}" ;;
  esac
  verify_exact_token
}

verify_client() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient false
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled true
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  [ -n "$(mapper_uuid_optional)" ] || fail "audience mapper missing"
  for role in ${REVIEWED_ROLES}; do
    role_scope_has_direct_role "${role}" || fail "client role scope is missing ${role}"
  done
  assert_scope_within
  resolve_service_account
  for role in ${REVIEWED_ROLES}; do
    target_has_direct_role "${role}" || fail "direct realm role missing: ${role}"
  done
  assert_reviewed_roles
}

rollback_identity() {
  # Deleting the client removes its service account and with it both grants.
  # The roles themselves are retained: agentgateway-write:workspace-envio is
  # owned by the domain-roles hook and agentgateway-read:workspace by the
  # read-grants hook, and the gateway CEL references both.
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to delete ${CLIENT_ID}"
  fi
  [ -z "$(resolve_client_optional)" ] || fail "client ${CLIENT_ID} remains after rollback"
  printf '{"client_id":"%s","realm_roles":"%s","client_present":false,"roles_retained":true}\n' \
    "${CLIENT_ID}" "${REVIEWED_ROLES}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    verify_roles
    assert_send_role_exclusive
    upsert_client
    progress client-reconciled
    upsert_audience_mapper
    ensure_role_scope_mapping
    progress role-scope-verified
    resolve_service_account
    ensure_role_mapping
    progress role-mapping-verified
    ensure_fullscope_off
    verify_client
    progress token-verified
    printf '{"client_id":"%s","realm_roles":"%s","present":true,"fullscope_allowed":false,"token_verified":true}\n' \
      "${CLIENT_ID}" "${REVIEWED_ROLES}"
    ;;
  audit)
    verify_roles
    verify_client
    verify_exact_token
    printf '{"client_id":"%s","realm_roles":"%s","present":true,"fullscope_allowed":false,"token_verified":true}\n' \
      "${CLIENT_ID}" "${REVIEWED_ROLES}"
    ;;
  rollback)
    rollback_identity
    ;;
esac
