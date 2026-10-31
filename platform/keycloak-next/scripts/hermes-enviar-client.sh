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
# 17). The token-mint verification reads the current secret through the admin
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

# The bootstrap (cleanup trap, fail, login_admin, kget) is kc-admin-common.sh.
# CLIENT_CONFIG holds a bearer token, so the shared trap must remove it too.
KCADM_TMP_FILES="${CLIENT_CONFIG}"
. "${0%/*}/kc-admin-common.sh"

# Pure helpers (progress, client/mapper/SA lookups, mint, token_realm_roles)
# come from the shared reconcile library; policy — the guards below and the
# reviewed roles — stays here.
. "$(dirname "$0")/keycloak-reconcile-lib.sh"
# The reconcile flow (client, scope, grants, flag, exact token, rollback) is
# shared with the other dedicated scoped clients.
. "$(dirname "$0")/keycloak-scoped-client-lib.sh"

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

login_admin
progress authenticated
run_scoped_client
