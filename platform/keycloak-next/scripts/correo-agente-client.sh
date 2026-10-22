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
# come from the shared reconcile library; policy — the guards below and the
# reviewed roles — stays here.
. "$(dirname "$0")/keycloak-reconcile-lib.sh"
# The reconcile flow (client, scope, grants, flag, exact token, rollback) is
# shared with the other dedicated scoped clients.
. "$(dirname "$0")/keycloak-scoped-client-lib.sh"

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

login_admin
progress authenticated
run_scoped_client
