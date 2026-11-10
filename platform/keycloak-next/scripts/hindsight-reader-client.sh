#!/bin/sh
set -eu

umask 077

# Dedicated confidential client for the READ-ONLY Hindsight routes of
# AgentGateway (SC-4304 S6, security's provisioning of 02-11-2026, narrowed on
# 05-11-2026, widened for Nova on 10-11-2026). One script, the reviewed role
# set fixed per CLIENT_ID from the immutable table below; the table has six
# entries:
#   - socialmedia-hindsight: agentgateway-read:hindsight-personal — the
#     whatsappmcp mcp-server (ns whatsapp-mcp) semantic search over the
#     conversation memory it already retains into bank `personal`.
#   - the five read-only identities of Nova (the voice agent, ns `nova`), each
#     with ONLY its own read role, granted by security's verdict INFRA-1248
#     (INFRA-1245, 10-11-2026):
#       nova-hindsight-tienda          agentgateway-read:hindsight-tienda
#       nova-hindsight-claude-personal agentgateway-read:hindsight-claude-personal
#       nova-hindsight-personal        agentgateway-read:hindsight-personal
#       nova-hindsight-cloudblue       agentgateway-read:hindsight-cloudblue
#       nova-atlassian                 agentgateway-read:atlassian
#     C1 of that verdict is binding and lives in Nova, not here: while a
#     session carries a bank profile, no model outside the cluster runs the
#     turn (the race drops alibaba-q38-flash; k8s-nova-pocharlies#40). The
#     cloudblue grant also satisfies the role's declared provider restriction
#     (CloudBlue content only to Anthropic/local identities — C1 is exactly
#     that, local while the bank is loaded).
# Two identities this script first carried are deliberately absent. Security's
# re-ruling of 05-11-2026: jarvis-hindsight (voice plane, bank `tienda`) is
# refused — `tienda` holds customer orders and customer email with personal
# data, which a voice surface would speak through Amazon and which a hostile
# customer email could use to steer the voice agent — and
# synapse-hindsight-tienda is dropped because lookup_supplier_history reads
# Skirmbooks now. That ruling STILL STANDS for jarvis/Alexa: what INFRA-1248
# changed is the case, not the precedent — Nova's TTS and STT are local
# (omnivoice-tts / stt-turbo, no Amazon leg) and C1 keeps the bank content
# inside the cluster, so Nova holds `tienda` and jarvis does not. A new reader
# is a new table entry plus its own security verdict, never a looser one here.
#
# One principal per (service, bank): a leaked credential must open exactly one
# bank. The service account holds exactly ONE realm role, the shared route role
# of its bank (for nova-atlassian, the route role of its Jira/Confluence reads),
# and NOTHING from the agentgateway-write family — the routes are read-only by
# design (no write plane exists on any hindsight route; see the retain analysis
# on /hindsight-cloudblue in the live gateway config).
#
# Ownership of each grant (which reconciler owns it, so drift cannot revoke
# it — INFRA-1248 C4): this hook's ensure flow grants the reviewed role to the
# service account, and the holder-set owners accept the new SAs:
#   - agentgateway-read:hindsight-personal is created by security (SC-4051)
#     and its COMPLETE direct holder set is owned by
#     agentgateway-hindsight-personal-grants (wave 25), whose reviewed set
#     includes service-account-socialmedia-hindsight and, since INFRA-1245,
#     service-account-nova-hindsight-personal (neither is in the read-grants
#     matrix);
#   - agentgateway-read:hindsight-tienda, :hindsight-claude-personal and
#     :atlassian are shared route roles owned by agentgateway-read-grants
#     (wave 20): the grants ride this hook and the wave-20 hook only widens
#     the HOLDER ALLOWLIST of each role (NOVA_TIENDA / NOVA_CLAUDE_PERSONAL /
#     NOVA_ATLASSIAN entries, SC-699/INFRA-477 precedent) so the exclusivity
#     assertion accepts them on the next sync;
#   - agentgateway-read:hindsight-cloudblue has no holder-set reconciler at
#     all (it stays OUT of the read-grants matrix on purpose, INFRA-974; its
#     first holder service-account-agentgateway-mac-cb was manual): this hook
#     grants it to service-account-nova-hindsight-cloudblue and nothing
#     revokes it; the grant is declared in ROLES.yaml.
# This hook only verifies the role, creates/updates the client, maps its role
# into the client role scope, grants it to the service account, converges
# fullScopeAllowed=false and verifies the minted token. It never creates or
# deletes a role.
#
# The client SECRET is not managed here: Keycloak generates it on creation and
# security copies it to the 1Password item agentgateway-prod (vault
# k8s-pocharlies), field socialmedia_hindsight_client_secret and, for the five
# Nova identities, nova_hindsight_tienda_client_secret,
# nova_hindsight_claude_personal_client_secret,
# nova_hindsight_personal_client_secret, nova_hindsight_cloudblue_client_secret
# and nova_atlassian_client_secret (RUNBOOK section 22). The consumer reads it
# from 1Password through its own ExternalSecret, never from this Job. The
# token-mint verification reads it through the admin API and never prints it.

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
  nova-hindsight-tienda)
    REVIEWED_ROLES="agentgateway-read:hindsight-tienda"
    ;;
  nova-hindsight-claude-personal)
    REVIEWED_ROLES="agentgateway-read:hindsight-claude-personal"
    ;;
  nova-hindsight-personal)
    REVIEWED_ROLES="agentgateway-read:hindsight-personal"
    ;;
  nova-hindsight-cloudblue)
    REVIEWED_ROLES="agentgateway-read:hindsight-cloudblue"
    ;;
  nova-atlassian)
    REVIEWED_ROLES="agentgateway-read:atlassian"
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
