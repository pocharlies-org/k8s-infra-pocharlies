#!/bin/sh
set -eu

umask 077

# The two confidential clients of the Postia case agent (DGX-1218, PR-2 of epic
# DGX-1209; security condition 3), one Job each, this one script:
#   - correo-agente-lectura: the agent's read identity. Exactly the
#     agentgateway-read:<route> roles of its profiles (brain, picqer, shopify,
#     shopify-admin, skirmshop-plugins, workspace) and NO agentgateway-write*.
#   - correo-ejecutor: the executor of approved actions. Exactly
#     agentgateway-write:correo-ejecutor (the gateway CEL behind
#     order_shipping_line_replace, order_returnable_lines_get, return_create and
#     labels_pickup_create, k8s-agentgateway-pocharlies#221) plus
#     agentgateway-read:shopify-admin, which the /shopify-admin route requires.
#     Never the bare agentgateway-write.
# Same shape and guarantees as hermes-enviar-client.sh (INFRA-676), with the
# reviewed role set chosen by CLIENT_ID from the immutable table below.
#
# Ownership: agentgateway-write:correo-ejecutor is CREATED by
# agentgateway-domain-roles (wave 19), which fails the sync if anyone but
# service-account-correo-ejecutor holds it; the read roles are owned by
# agentgateway-read-grants (wave 20), whose holder allowlist reviews both
# service accounts. This hook only verifies the roles, creates/updates the
# client, maps its roles into the client role scope, grants them to the service
# account, converges fullScopeAllowed=false and verifies the minted token. It
# never creates or deletes a role.
#
# The client SECRET is not managed here: Keycloak generates it on creation and
# a devops step after the sync copies it to 1Password (RUNBOOK section 19). The
# token-mint verification reads it through the admin API and never prints it.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-correo-agente-admin.config
CLIENT_CONFIG=/tmp/kcadm-correo-agente-client.config

# The bootstrap (cleanup trap, fail, login_admin, kget) is kc-admin-common.sh.
# CLIENT_CONFIG holds a bearer token, so the shared trap must remove it too.
KCADM_TMP_FILES="${CLIENT_CONFIG}"
. "${0%/*}/kc-admin-common.sh"

# Pure helpers (progress, client/mapper/SA lookups, mint, token_realm_roles)
# come from the shared reconcile library; policy — the guards below, the
# reviewed roles, the scope bounds — stays here.
. "$(dirname "$0")/keycloak-reconcile-lib.sh"

# Space-separated reviewed set, already sorted, so its comma form is the shape
# token_realm_roles prints for the exact token comparison. WRITE_ROLE_NAME is
# empty for the read identity: it holds no write role at all.
case "${CLIENT_ID}" in
  correo-agente-lectura)
    REVIEWED_ROLES="agentgateway-read:brain agentgateway-read:picqer agentgateway-read:shopify agentgateway-read:shopify-admin agentgateway-read:skirmshop-plugins agentgateway-read:workspace"
    WRITE_ROLE_NAME=""
    ;;
  correo-ejecutor)
    REVIEWED_ROLES="agentgateway-read:shopify-admin agentgateway-write:correo-ejecutor"
    WRITE_ROLE_NAME="agentgateway-write:correo-ejecutor"
    ;;
  *) fail "unsupported immutable client" ;;
esac
EXPECTED_TOKEN_ROLES="$(printf '%s' "${REVIEWED_ROLES}" | tr ' ' ',')"
[ "${MAPPER_NAME}" = "aud-mcp" ] || fail "MAPPER_NAME is immutable"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit or rollback" ;;
esac

upsert_client() {
  # Neither branch carries a secret: create lets Keycloak generate one, and
  # update must never overwrite the secret the case agent authenticates with. The create path sets fullScopeAllowed=false from the start; the
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
  # Every role is owned by an earlier hook; a missing one means that hook has
  # not run for this commit, never a reason to create it here.
  for role in ${REVIEWED_ROLES}; do
    case "${role}" in
      agentgateway-write:*) owner="agentgateway-domain-roles" ;;
      *) owner="agentgateway-read-grants" ;;
    esac
    kget "roles/${role}" --fields id >/dev/null 2>&1 || \
      fail "${role} is missing; the ${owner} hook owns it"
    composite="$(kget "roles/${role}" --fields composite --format csv --noquotes | nonempty_lines)"
    [ "${composite}" = "false" ] || fail "${role} must remain non-composite"
  done
}

assert_write_role_exclusive() {
  # agentgateway-write:correo-ejecutor changes orders and books pickups: before
  # this hook grants it, its only holder may be our own service account (the
  # domain-roles hook asserts the same on every sync). Bounded listing: the one
  # reviewed holder plus two rows exposes any violation. The read identity has
  # no write role, so there is nothing to assert for it.
  [ -n "${WRITE_ROLE_NAME}" ] || return 0
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
    ensure_role_in_client_scope "${role}"
  done
}

assert_reviewed_roles() {
  # The service account may hold exactly its reviewed set from the
  # agentgateway-read/write families. The bare umbrella role, any other write
  # domain and any sibling read route all fail closed.
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
  # The reviewed set travels through the client role scope ALONE (flag off):
  # EXACT, never a subset, so a role someone added to the service account
  # fails here even if every reviewed role is present. The bare
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
  # Every role is already in the client role scope and granted (the caller's
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
  # Deleting the client removes its service account and with it every grant.
  # The roles are retained: the domain-roles and read-grants hooks own them
  # and the gateway CEL references them.
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
    assert_write_role_exclusive
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
