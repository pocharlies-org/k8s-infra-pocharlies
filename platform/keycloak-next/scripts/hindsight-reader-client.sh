#!/bin/sh
set -eu

umask 077

# Dedicated confidential clients for the READ-ONLY Hindsight routes of
# AgentGateway (SC-4304 S6, security's provisioning of 02-11-2026). One script,
# the reviewed role set fixed per CLIENT_ID from the immutable table below:
#   - jarvis-hindsight: agentgateway-read:hindsight-tienda — the voice plane
#     (jarvis-backend / jarvis-alexa, ns jarvis) reads bank `tienda` for
#     brain_search/brain_chat. Security's verdict (SC-4304 S6): tienda only,
#     never a personal bank; the voice surface must strip key-bearing URLs
#     (order_status_url and the like) from tool results before the LLM sees
#     them, and the cutover from Brain waits for the tienda<->skirmshop parity
#     check.
#   - synapse-hindsight-tienda: agentgateway-read:hindsight-tienda —
#     synapse-tools-mcp (ns synapse) lookup_supplier_history for tenant
#     skirmshop. Cutover waits for supplier invoices to actually land in the
#     bank (measured 02-11: tienda holds orders and products only).
#   - socialmedia-hindsight: agentgateway-read:hindsight-personal — the
#     whatsappmcp mcp-server (ns whatsapp-mcp) semantic search over the
#     conversation memory it already retains into bank `personal`.
#
# One principal per (service, bank): a leaked tienda credential must not open
# the personal bank, and vice versa. Each service account holds exactly ONE
# realm role, the shared route role of its bank, and NOTHING from the
# agentgateway-write family — the routes are read-only by design (no write
# plane exists on any hindsight route; see the retain analysis on
# /hindsight-cloudblue in the live gateway config).
#
# Ownership: the read roles are owned by agentgateway-read-grants (wave 20),
# whose holder allowlist reviews jarvis-hindsight and synapse-hindsight-tienda
# on agentgateway-read:hindsight-tienda (hindsight-personal is not in that
# matrix; socialmedia-hindsight is documented here and in PRINCIPALS.md). This
# hook only verifies the roles, creates/updates the client, maps its role into
# the client role scope, grants it to the service account, converges
# fullScopeAllowed=false and verifies the minted token. It never creates or
# deletes a role.
#
# The client SECRET is not managed here: Keycloak generates it on creation and
# security copies it to the 1Password item agentgateway-prod (vault
# k8s-pocharlies), fields jarvis_hindsight_client_secret,
# synapse_hindsight_tienda_client_secret and socialmedia_hindsight_client_secret
# (RUNBOOK section 22). Consumers read it from 1Password through their own
# ExternalSecret, never from this Job. The token-mint verification reads it
# through the admin API and never prints it.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-hindsight-reader-admin.config
CLIENT_CONFIG=/tmp/kcadm-hindsight-reader-client.config

# The bootstrap (cleanup trap, fail, login_admin, kget) is kc-admin-common.sh.
# CLIENT_CONFIG holds a bearer token, so the shared trap must remove it too.
KCADM_TMP_FILES="${CLIENT_CONFIG}"
. "${0%/*}/kc-admin-common.sh"

# Pure helpers (progress, client/mapper/SA lookups, mint, token_realm_roles)
# come from the shared reconcile library; policy — the guards below and the
# reviewed roles — stays here.
. "$(dirname "$0")/keycloak-reconcile-lib.sh"
# The reconcile flow (client, scope, grants, flag, exact token, rollback) is
# shared with the other dedicated scoped clients (hermes-enviar, correo-agente).
. "$(dirname "$0")/keycloak-scoped-client-lib.sh"

# Space-separated reviewed set, already sorted, so its comma form is the shape
# token_realm_roles prints for the exact token comparison. WRITE_ROLE_NAME is
# empty for all three: none of these identities holds a write role at all.
case "${CLIENT_ID}" in
  jarvis-hindsight)
    REVIEWED_ROLES="agentgateway-read:hindsight-tienda"
    ;;
  synapse-hindsight-tienda)
    REVIEWED_ROLES="agentgateway-read:hindsight-tienda"
    ;;
  socialmedia-hindsight)
    REVIEWED_ROLES="agentgateway-read:hindsight-personal"
    ;;
  *) fail "unsupported immutable client" ;;
esac
WRITE_ROLE_NAME=""
EXPECTED_TOKEN_ROLES="$(printf '%s' "${REVIEWED_ROLES}" | tr ' ' ',')"
[ "${MAPPER_NAME}" = "aud-mcp" ] || fail "MAPPER_NAME is immutable"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit or rollback" ;;
esac

login_admin
progress authenticated
run_scoped_client
