#!/bin/sh
set -eu

umask 077

# Dedicated confidential client for the READ-ONLY Hindsight routes of
# AgentGateway (SC-4304 S6, security's provisioning of 02-11-2026, narrowed on
# 05-11-2026). One script, the reviewed role set fixed per CLIENT_ID from the
# immutable table below; today the table has one entry:
#   - socialmedia-hindsight: agentgateway-read:hindsight-personal — the
#     whatsappmcp mcp-server (ns whatsapp-mcp) semantic search over the
#     conversation memory it already retains into bank `personal`.
# Two identities this script first carried are deliberately absent. Security's
# re-ruling of 05-11-2026: jarvis-hindsight (voice plane, bank `tienda`) is
# refused — `tienda` holds customer orders and customer email with personal
# data, which a voice surface would speak through Amazon and which a hostile
# customer email could use to steer the voice agent — and
# synapse-hindsight-tienda is dropped because lookup_supplier_history reads
# Skirmbooks now. A new reader is a new table entry plus its own security
# verdict, never a looser one here.
#
# One principal per (service, bank): a leaked credential must open exactly one
# bank. The service account holds exactly ONE realm role, the shared route role
# of its bank, and NOTHING from the agentgateway-write family — the routes are
# read-only by design (no write plane exists on any hindsight route; see the
# retain analysis on /hindsight-cloudblue in the live gateway config).
#
# Ownership: the role agentgateway-read:hindsight-personal is created by
# security (SC-4051) and its COMPLETE direct holder set is owned by
# agentgateway-hindsight-personal-grants (wave 25), whose reviewed set includes
# service-account-socialmedia-hindsight (it is not in the read-grants matrix).
# This hook only verifies the role, creates/updates the client, maps its role
# into the client role scope, grants it to the service account, converges
# fullScopeAllowed=false and verifies the minted token. It never creates or
# deletes a role.
#
# The client SECRET is not managed here: Keycloak generates it on creation and
# security copies it to the 1Password item agentgateway-prod (vault
# k8s-pocharlies), field socialmedia_hindsight_client_secret (RUNBOOK section
# 22). The consumer reads it from 1Password through its own ExternalSecret,
# never from this Job. The token-mint verification reads it through the admin
# API and never prints it.

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
# empty: no identity here holds a write role at all.
case "${CLIENT_ID}" in
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
