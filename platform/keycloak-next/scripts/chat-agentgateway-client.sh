#!/bin/sh
set -eu

umask 077

# Dedicated confidential client for the chat surface (Open WebUI at
# chat.e-dani.com) to reach AgentGateway through its auth-proxy sidecar.
# It holds the REVIEWED SET of domain roles below and nothing else from the
# agentgateway-write family — never the legacy umbrella role — plus the one
# shared route role agentgateway-read:studio. Every role is CREATED elsewhere
# (agentgateway-domain-roles.sh, sync-wave 19, for the write domains;
# agentgateway-read-grants.sh, sync-wave 20, for the read role) and only
# VERIFIED here: this reconciler never creates, deletes or widens a realm role.
#
# 2026-09-17 (contract v2): the set grew from one role to six. The chat moved
# ALL its MCP tool servers onto the sidecar (they used to carry a hand-pasted,
# 30-day token of the umbrella client agentgateway-mcp, which expires
# 2026-09-27 and would have taken every tool down at once). The set is exactly
# the domains the chat already reaches today — media, social, workspace, gsc,
# synapse and the new hermes — so the move loses no capability while dropping
# the umbrella's reach over shopify, picqer, skirmshop-plugins and sauvage.
#
# 2026-09-26 (SC-699): the set grew to seven with agentgateway-read:studio,
# the ROUTE role /studio has required since INFRA-143 (2026-09-19, measured by
# qa: the sidecar's client-credentials token carried only the six write roles
# and initialize on /studio answered 403 authorization failed while /grok
# answered 200). Unlike the six write roles this one is SHARED: the same role
# is held by the agentgateway-mcp and openclaw service accounts, so the
# exclusive-service-account invariant applies to the agentgateway-write family
# only; the holder allowlist of the shared read role is owned by
# agentgateway-read-grants.sh (sync-wave 20), which runs before this hook.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-chat-agentgateway}"
# Space-separated and ORDER-INSENSITIVE for the guard below; keep it sorted.
ROLE_NAMES="${ROLE_NAMES:-agentgateway-read:studio agentgateway-write:gsc agentgateway-write:hermes agentgateway-write:media agentgateway-write:social agentgateway-write:synapse agentgateway-write:workspace}"
EXPECTED_ROLE_NAMES="agentgateway-read:studio agentgateway-write:gsc agentgateway-write:hermes agentgateway-write:media agentgateway-write:social agentgateway-write:synapse agentgateway-write:workspace"
# SC-2029 (2026-10-07): the four general Hermes secretaria service accounts
# (INFRA-494, epic INFRA-479: per-profile secretaria identities that write
# social and workspace through AgentGateway) are reviewed EXTRA holders of
# agentgateway-write:social and agentgateway-write:workspace. Their grants
# are created by the devops identity process in k8s-openclaw-qwen36-pocharlies
# and their holder matrix is owned by agentgateway-domain-roles.sh (widened
# by SC-2005); this hook tolerates exactly these pairs and nothing else.
# tests/test_keycloak_rbac_parity_contract.py keeps this list equal to the
# non-chat pairs of that allowlist — one source of truth.
REVIEWED_EXTRA_HOLDERS="${REVIEWED_EXTRA_HOLDERS:-agentgateway-write:social=service-account-hermes-secretaria,agentgateway-write:social=service-account-hermes-secretaria-casa,agentgateway-write:social=service-account-hermes-secretaria-dani,agentgateway-write:social=service-account-hermes-secretaria-leila,agentgateway-write:workspace=service-account-hermes-secretaria,agentgateway-write:workspace=service-account-hermes-secretaria-casa,agentgateway-write:workspace=service-account-hermes-secretaria-dani,agentgateway-write:workspace=service-account-hermes-secretaria-leila}"
EXPECTED_REVIEWED_EXTRA_HOLDERS="agentgateway-write:social=service-account-hermes-secretaria,agentgateway-write:social=service-account-hermes-secretaria-casa,agentgateway-write:social=service-account-hermes-secretaria-dani,agentgateway-write:social=service-account-hermes-secretaria-leila,agentgateway-write:workspace=service-account-hermes-secretaria,agentgateway-write:workspace=service-account-hermes-secretaria-casa,agentgateway-write:workspace=service-account-hermes-secretaria-dani,agentgateway-write:workspace=service-account-hermes-secretaria-leila"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
FORBIDDEN_REALM_ROLE="${FORBIDDEN_REALM_ROLE:-agentgateway-write}"
RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-2}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-chat-agentgateway-admin.config
CLIENT_CONFIG=/tmp/kcadm-chat-agentgateway-client.config

cleanup() {
  rm -f "${ADMIN_CONFIG}" "${CLIENT_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

# Mechanical helpers (fail, progress, login, kget, client/mapper/SA lookups,
# mint) live in the shared reconcile library; every policy — the reviewed
# role set, the guards below, exclusivity and the audience mapper — stays in
# this script, unchanged.
. "$(dirname "$0")/keycloak-reconcile-lib.sh"

[ "${FORBIDDEN_REALM_ROLE}" = "agentgateway-write" ] || fail "FORBIDDEN_REALM_ROLE is immutable"
[ "${RECONCILE_CONTRACT_VERSION}" = "2" ] || fail "unsupported reconcile contract version"
[ "${ROLE_NAMES}" = "${EXPECTED_ROLE_NAMES}" ] || \
  fail "ROLE_NAMES is immutable; review this reconciler, the domain-role allowlist and the gateway CEL together"
[ "${REVIEWED_EXTRA_HOLDERS}" = "${EXPECTED_REVIEWED_EXTRA_HOLDERS}" ] || \
  fail "REVIEWED_EXTRA_HOLDERS is immutable; review this reconciler, the domain-role allowlist and the gateway CEL together"
case "${CLIENT_ID}" in
  chat-agentgateway)
    CLIENT_SECRET="${CHAT_AGENTGATEWAY_CLIENT_SECRET:-}"
    MAPPER_NAME=chat-agentgateway-audience
    ;;
  *) fail "unsupported immutable client" ;;
esac
case "${MODE}" in
  ensure|audit)
    [ -n "${CLIENT_SECRET}" ] || fail "client secret is empty"
    ;;
  rollback) ;;
  *) fail "unsupported MODE=${MODE}" ;;
esac

upsert_client() {
  uuid="$(resolve_client_optional)"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=false \
    -s standardFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=true \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s "secret=${CLIENT_SECRET}" >/dev/null 2>&1 || \
    fail "failed to reconcile ${CLIENT_ID}"
  CLIENT_UUID="$(require_client)"
}

verify_role() {
  # Write-domain roles are owned by agentgateway-domain-roles.sh and the read
  # role by agentgateway-read-grants.sh; a missing role means that hook has
  # not run for this commit, never a reason to create it here.
  role_exists "$1" || fail "$1 is missing; the agentgateway-domain-roles or agentgateway-read-grants hook owns it"
  composite="$(kget "roles/$1" --fields composite --format csv --noquotes | nonempty_lines)"
  [ "${composite}" = "false" ] || fail "$1 must remain non-composite"
}

verify_roles() {
  for role in ${ROLE_NAMES}; do
    verify_role "${role}"
  done
}

ensure_role_scope_mapping() {
  for role in ${ROLE_NAMES}; do
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

assert_reviewed_write_roles() {
  # The chat identity may hold the reviewed domain roles and NOTHING else from
  # the agentgateway-write family: not the legacy umbrella role, not a sibling
  # domain such as agentgateway-write:shopify. Anything outside the set fails.
  held="$(service_account_realm_roles | grep -E '^agentgateway-write' || true)"
  for role in ${held}; do
    case " ${ROLE_NAMES} " in
      *" ${role} "*) ;;
      *) fail "service account holds an unreviewed AgentGateway write role: ${role}" ;;
    esac
  done
  # The completeness check is write-family only: the shared read role is
  # granted by ensure_role_mapping and its presence asserted there and in
  # verify_client, but it never appears in the write-family listing above.
  for role in ${ROLE_NAMES}; do
    case "${role}" in
      agentgateway-write*)
        printf '%s\n' "${held}" | grep -Fxq "${role}" || fail "service account is missing ${role}" ;;
    esac
  done
}

assert_exclusive_role_mapping() {
  # Bounded role-member endpoints: only the reviewed holders of this role —
  # our service account plus, since SC-2029, the extra holders declared for
  # it in REVIEWED_EXTRA_HOLDERS — and zero groups are allowed, so fetching
  # the reviewed count plus two rows detects every violation.
  reviewed="${SERVICE_ACCOUNT_USERNAME}"
  for pair in $(printf '%s' "${REVIEWED_EXTRA_HOLDERS}" | tr ',' ' '); do
    [ "${pair%%=*}" = "$1" ] && reviewed="${reviewed} ${pair#*=}"
  done
  bound=$(( $(printf '%s\n' ${reviewed} | wc -l) + 2 ))
  users="$(kget "roles/$1/users" -q first=0 -q max="${bound}" \
    --fields username --format csv --noquotes | nonempty_lines)"
  groups="$(kget "roles/$1/groups" -q first=0 -q max=2 \
    --fields path --format csv --noquotes | nonempty_lines)"
  [ -z "${groups}" ] || fail "$1 is mapped to a group"
  if [ -n "${users}" ]; then
    while IFS= read -r username; do
      case " ${reviewed} " in
        *" ${username} "*) ;;
        *) fail "$1 has an unauthorized user" ;;
      esac
    done <<EOF
${users}
EOF
  fi
}

ensure_role_mapping() {
  # TWO passes on purpose: with several roles, checking and granting in the
  # same loop would have already granted the first roles by the time an
  # unauthorized holder is found on a later one. Nothing is mutated until
  # every role is clean. Exclusivity is checked for the agentgateway-write
  # family only: agentgateway-read:studio is a SHARED route role also held by
  # the agentgateway-mcp and openclaw service accounts, and its holder
  # allowlist is owned by agentgateway-read-grants.sh.
  for role in ${ROLE_NAMES}; do
    case "${role}" in
      agentgateway-write*) assert_exclusive_role_mapping "${role}" ;;
    esac
  done
  for role in ${ROLE_NAMES}; do
    if ! target_has_direct_role "${role}"; then
      "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${SERVICE_ACCOUNT_ID}" --rolename "${role}" >/dev/null 2>&1 || \
        fail "failed to map ${role}"
    fi
    case "${role}" in
      agentgateway-write*) assert_exclusive_role_mapping "${role}" ;;
    esac
  done
  assert_reviewed_write_roles
}

verify_client() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient false
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled true
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  [ -n "$(mapper_uuid_optional)" ] || fail "audience mapper missing"
  resolve_service_account
  for role in ${ROLE_NAMES}; do
    role_scope_has_direct_role "${role}" || fail "client role scope is missing ${role}"
    target_has_direct_role "${role}" || fail "direct realm role missing: ${role}"
    # Exclusivity is a write-family invariant (shared read role: see
    # ensure_role_mapping).
    case "${role}" in
      agentgateway-write*) assert_exclusive_role_mapping "${role}" ;;
    esac
  done
  assert_reviewed_write_roles
}

mint_claims() {
  # The chat secret is pinned from 1Password by this Job's ExternalSecret and
  # passed in CHAT_AGENTGATEWAY_CLIENT_SECRET (guard above); the mint itself
  # is the library's, with the chat wording kept for the contract tests.
  mint_claims_with_secret "${CLIENT_SECRET}" "client token mint failed"
}

verify_minted_claims() {
  claims="$(mint_claims)"
  printf '%s' "${claims}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${CLIENT_ID}"'"' || \
    fail "minted token has wrong azp"
  printf '%s' "${claims}" | grep -Fq "${AGENTGATEWAY_AUDIENCE}" || fail "audience missing"
  for role in ${ROLE_NAMES}; do
    printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"'"${role}"'"' || \
      fail "dedicated realm role missing in the minted token: ${role}"
  done
  if printf '%s' "${claims}" | grep -Eq '"realm_access"[[:space:]]*:[[:space:]]*\{[^}]*"roles"[[:space:]]*:[[:space:]]*\[[^]]*"agentgateway-write"'; then
    fail "minted token contains forbidden realm role"
  fi
  unset claims
}

rollback_identity() {
  # Deleting the client removes its service account and therefore the only
  # reviewed grant of the domain role. The role itself is retained: it is
  # owned by agentgateway-domain-roles.sh and referenced by the gateway CEL.
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to delete ${CLIENT_ID}"
  fi
  [ -z "$(resolve_client_optional)" ] || fail "client ${CLIENT_ID} remains after rollback"
  # Write-family roles only: deleting the client removes its service account.
  # The shared read role stays in the realm WITH its other reviewed holders
  # (agentgateway-mcp, openclaw) — asserting emptiness there would fail by
  # design. Since SC-2029 the same is true, one level down, for the write
  # roles with reviewed extra holders (the INFRA-494 secretarias on
  # write:social/:workspace): after our deletion only those reviewed extras
  # may remain, never a stranger and never a group.
  for role in ${ROLE_NAMES}; do
    case "${role}" in
      agentgateway-write*)
        if role_exists "${role}"; then
          users="$(kget "roles/${role}/users" --fields username --format csv --noquotes | nonempty_lines)"
          groups="$(kget "roles/${role}/groups" --fields path --format csv --noquotes | nonempty_lines)"
          [ -z "${groups}" ] || fail "${role} still has group mappings after client deletion"
          if [ -n "${users}" ]; then
            while IFS= read -r username; do
              found=0
              for pair in $(printf '%s' "${REVIEWED_EXTRA_HOLDERS}" | tr ',' ' '); do
                [ "${pair}" = "${role}=${username}" ] && found=1
              done
              [ "${found}" = "1" ] || fail "${role} still has an unreviewed mapping after client deletion"
            done <<EOF
${users}
EOF
          fi
        fi ;;
    esac
  done
  printf '{"client_id":"%s","realm_roles":"%s","client_present":false,"roles_retained":true}\n' \
    "${CLIENT_ID}" "${ROLE_NAMES}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    verify_roles
    upsert_client
    progress client-reconciled
    upsert_audience_mapper
    ensure_role_scope_mapping
    progress role-scope-verified
    resolve_service_account
    ensure_role_mapping
    progress role-mapping-verified
    verify_client
    verify_minted_claims
    printf '{"client_id":"%s","realm_roles":"%s","present":true,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAMES}"
    ;;
  audit)
    verify_roles
    verify_client
    verify_minted_claims
    printf '{"client_id":"%s","realm_roles":"%s","present":true,"exclusive_service_account":true}\n' \
      "${CLIENT_ID}" "${ROLE_NAMES}"
    ;;
  rollback)
    rollback_identity
    ;;
esac
