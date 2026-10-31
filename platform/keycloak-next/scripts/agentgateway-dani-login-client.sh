#!/bin/sh
set -eu

umask 077

# OWU-75 (OWU-28 P1; security ruling OWU-100): owns EXACTLY ONE IdP fact — the
# confidential ROPC test client "dani-login-test" (realm "edani"). It exists so
# QA can exchange Daniel's password for a short-lived access token and measure
# C1, C2 positive and C4 live (plan 10-plan.md, part P2). Nothing else: the
# client carries no redirect URIs, no standard/implicit flow, no service
# account and no refresh tokens, and this reconciler never creates the realm
# role it maps into the client scope (owned by agentgateway-write-role.sh,
# PostSync wave 20) and never grants a role to any user (owned by
# agentgateway-write-grant-daniel.sh / agentgateway-write-fixture-user.sh).
#
# OWU-100 conditions baked into the pins below:
#   * condition 3 (session cap): attributes."access.token.lifespan"=900 and
#     attributes."use.refresh.tokens"="false" — Keycloak emits refresh tokens
#     by default, so without the second pin a test session would silently
#     outlive its 15-minute cap.
#   * condition 4 (no privilege of its own): fullScopeAllowed=false and the
#     realm scope mapping EMITS exactly the reviewed agentgateway-write role —
#     the mapping grants nothing to anyone; it only makes the role emittable
#     for users who already hold it (house pattern #190, measured by security
#     in nota-security-c2-token.md).
#
# Credentials (architect ruling nota-architect-plan.md, hallazgo 2 — two
# ExternalSecrets, never one):
#   * the client secret arrives as DANI_LOGIN_CLIENT_SECRET through the Secret
#     of ExternalSecret A (1Password item keycloak-next-dani-login-test,
#     field client_secret, seeded by security BEFORE the merge). It is passed
#     to kcadm only as a -s flag of the create/update call and never printed:
#     the create reply is discarded because the created representation carries
#     the secret.
#   * Daniel's password lives in ExternalSecret B (item keycloak-next-dani-login,
#     field password) and is seeded only with his own gesture. This reconciler
#     does NOT reference that Secret: while the item is absent ES B stays in
#     error — expected state, not an incident — and the PostSync of the whole
#     k8s-infra app must not depend on it.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk/jq/python
# (SC-1215). Only kcadm plus sed/grep/tr/wc/rm/sleep are invoked; the contract
# test audits this. Neither the client secret nor any token is ever printed:
# the output is a sanitized JSON verdict.
#
# MODE rollback deletes ONLY the client (OWU-100 condition 4): the role, its
# other holders, every other client and both ExternalSecrets are untouched.
# A git revert of the commit owning this reconciler removes the client on the
# next PostSync; the manual rollback Job
# (manual/agentgateway-dani-login-client-rollback-job.yaml, RUNBOOK section
# 19) is applied by hand.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-dani-login-test}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
ROLE_NAME="${ROLE_NAME:-agentgateway-write}"
ACCESS_TOKEN_LIFESPAN="${ACCESS_TOKEN_LIFESPAN:-900}"
USE_REFRESH_TOKENS="${USE_REFRESH_TOKENS:-false}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-dani-login-admin.config
KCADM_OUT=/tmp/kcadm-dani-login-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"

# Shared mechanical helpers (INFRA-477): resolve_client_optional, require_client,
# client_field, assert_client_boolean, role_exists, mapper_uuid_optional,
# upsert_audience_mapper, role_scope_has_direct_role, ensure_role_in_client_scope.
. "$(dirname "$0")/keycloak-reconcile-lib.sh"

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, client, audience, mapper, role, TTL or refresh setting through the
# environment. Changing any of them is a reviewed change to OWU-100, not a
# sync-time knob.
[ "${CLIENT_ID}" = "dani-login-test" ] || fail "CLIENT_ID is immutable"
[ "${REALM}" = "edani" ] || fail "REALM is immutable"
[ "${AGENTGATEWAY_AUDIENCE}" = "mcp.lan.e-dani.com" ] || fail "AGENTGATEWAY_AUDIENCE is immutable"
[ "${MAPPER_NAME}" = "aud-mcp" ] || fail "MAPPER_NAME is immutable"
[ "${ROLE_NAME}" = "agentgateway-write" ] || fail "ROLE_NAME is immutable"
[ "${ACCESS_TOKEN_LIFESPAN}" = "900" ] || \
  fail "ACCESS_TOKEN_LIFESPAN is immutable (OWU-100 condition 3: session cap 15 min)"
[ "${USE_REFRESH_TOKENS}" = "false" ] || \
  fail "USE_REFRESH_TOKENS is immutable (OWU-100 condition 3: no refresh tokens)"
case "${MODE}" in
  ensure|audit)
    [ -n "${DANI_LOGIN_CLIENT_SECRET:-}" ] || fail "client secret is empty"
    ;;
  rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

verify_realm_roles() {
  # The role is owned by agentgateway-write-role.sh (PostSync wave 20, which
  # runs before this hook's wave 25). Missing here means the trunk moved out
  # from under the mapping: fail loud, never create the role from this hook.
  role_exists "${ROLE_NAME}" || \
    fail "${ROLE_NAME} is missing from realm ${REALM}: owned by agentgateway-write-role.sh, refusing to create it here"
}

upsert_client() {
  uuid="$(resolve_client_optional)"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  # Confidential ROPC-only client: directAccessGrantsEnabled=true and every
  # other flow off, no redirect URIs, fullScopeAllowed=false (the reviewed
  # scope mapping below is the only emittable realm role). The secret is
  # re-applied from 1Password on every sync (Keycloak == vault, dgx-messages
  # pattern). The reply is DISCARDED: the created representation carries the
  # client secret and nothing here may print or keep it; the post-ensure read
  # below is the real assertion (SC-1215).
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=false \
    -s standardFlowEnabled=false \
    -s directAccessGrantsEnabled=true \
    -s implicitFlowEnabled=false \
    -s serviceAccountsEnabled=false \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s "redirectUris=[]" \
    -s "attributes.\"access.token.lifespan\"=${ACCESS_TOKEN_LIFESPAN}" \
    -s "attributes.\"use.refresh.tokens\"=${USE_REFRESH_TOKENS}" \
    -s "secret=${DANI_LOGIN_CLIENT_SECRET}" >/dev/null 2>&1 || \
    fail "failed to ${action} client ${CLIENT_ID}"
  CLIENT_UUID="$(require_client)"
}

verify_attributes() {
  # kcadm serializes map fields like `attributes` EMPTY when they are selected
  # through the field filter (measured 2026-09-21, INFRA-197), so the TTL and
  # refresh pins are checked against the FULL JSON document, matching key and
  # value paired (agentgateway-mcp-token-ttl.sh pattern). The same full read
  # asserts the redirect list is empty: a ROPC-only client with a redirect URI
  # would be a browser-capable client, which OWU-100 forbids.
  doc="$(kget "clients/${CLIENT_UUID}" --format json)"
  printf '%s' "${doc}" | grep -Eq \
    "\"access\.token\.lifespan\"[[:space:]]*:[[:space:]]*\"${ACCESS_TOKEN_LIFESPAN}\"" || \
    fail "client access.token.lifespan is not ${ACCESS_TOKEN_LIFESPAN} (OWU-100 condition 3)"
  printf '%s' "${doc}" | grep -Eq \
    "\"use\.refresh\.tokens\"[[:space:]]*:[[:space:]]*\"${USE_REFRESH_TOKENS}\"" || \
    fail "client use.refresh.tokens is not ${USE_REFRESH_TOKENS}: a refresh token would outlive the OWU-100 session cap"
  redirects="$(printf '%s' "${doc}" | tr -d '\n' | \
    sed -n 's/.*"redirectUris"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' | \
    tr -d '[:space:]')"
  [ -z "${redirects}" ] || \
    fail "client ${CLIENT_ID} carries redirect URIs: this ROPC-only client must have none"
}

verify_scope_mapping() {
  # The mapping must hold EXACTLY the reviewed role: role_scope_has_direct_role
  # pins presence (and ensure_role_in_client_scope re-reads after the write),
  # the line count pins that nothing else was added out of band.
  role_scope_has_direct_role "${ROLE_NAME}" || \
    fail "client realm scope mapping is missing ${ROLE_NAME}"
  count="$(kget "clients/${CLIENT_UUID}/scope-mappings/realm" \
    --fields name --format csv --noquotes | line_count)"
  [ "${count}" = "1" ] || \
    fail "client realm scope mapping holds ${count} roles, expected exactly ${ROLE_NAME}"
}

verify_client() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient false
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled true
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled false
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  verify_attributes
  [ -n "$(mapper_uuid_optional)" ] || fail "audience mapper ${MAPPER_NAME} is missing"
  verify_scope_mapping
}

rollback_client() {
  # Deletes ONLY the client. The role, its holders, every other client and both
  # ExternalSecrets stay exactly as they were (OWU-100 condition 4).
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    if ! "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      > "${KCADM_OUT}" 2>&1; then
      fail "failed to delete ${CLIENT_ID}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
    fi
    [ -z "$(resolve_client_optional)" ] || \
      fail "client ${CLIENT_ID} still exists after rollback"
  fi
  printf '{"client_id":"%s","present":false}\n' "${CLIENT_ID}"
}

report() {
  printf '{"client_id":"%s","present":true,"ropc":true,"lifespan":"%s","refresh_tokens":false,"scope_role":"%s"}\n' \
    "${CLIENT_ID}" "${ACCESS_TOKEN_LIFESPAN}" "${ROLE_NAME}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    verify_realm_roles
    upsert_client
    progress client-reconciled
    upsert_audience_mapper
    progress mapper-reconciled
    ensure_role_in_client_scope "${ROLE_NAME}"
    progress scope-reconciled
    verify_client
    report
    ;;
  audit)
    verify_realm_roles
    verify_client
    report
    ;;
  rollback)
    rollback_client
    ;;
esac
