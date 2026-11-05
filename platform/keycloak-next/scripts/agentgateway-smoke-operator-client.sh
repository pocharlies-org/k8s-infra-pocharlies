#!/bin/sh
set -eu

umask 077

# The read-only fixture of the AgentGateway write-role smoke (INFRA-1189, for
# the C7 validation of epic INFRA-218): `scripts/smoke-write-role.sh` in
# k8s-agentgateway-pocharlies proves the write boundary by holding two tokens —
# an ADMIN one carrying the realm role `agentgateway-write` (the shared
# service-account-agentgateway-mcp already is that) and an OPERATOR one that is
# NOT: exactly the read roles the script's route gates demand
# (agentgateway-read:social for /social, agentgateway-read:workspace for
# /workspace) and nothing from the agentgateway-write family. No principal of
# the realm had that shape (every holder of both reads also holds a write), so
# the smoke had no operator to run with. This is that fixture: a confidential
# client, service account only, whose minted token is the OPERATOR_TOKEN.
#
# Same shape and guarantees as correo-agente-lectura (DGX-1218): the reviewed
# role set is fixed below, the roles are owned by agentgateway-read-grants
# (wave 20, whose holder allowlist reviews this service account), and this hook
# only verifies the roles, creates/updates the client, maps them into the
# client role scope, grants them to the service account, converges
# fullScopeAllowed=false and verifies the minted token. It never creates or
# deletes a role.
#
# The client SECRET is not managed here: Keycloak generates it on creation.
# Its consumers (the qa session running the smoke, and CI when the smoke lands
# in the gateway's pipeline) read it through the admin API
# (`clients/<uuid>/client-secret`, netrc 0600, never argv, never echoed) — the
# fixture grants two reviewed read roles, so no 1Password item is warranted.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-smoke-operator-admin.config
CLIENT_CONFIG=/tmp/kcadm-smoke-operator-client.config

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
# empty: the operator must hold NO write role — that absence is what the smoke
# proves (the moderation tool absent from its tools/list, its tools/call denied).
case "${CLIENT_ID}" in
  agentgateway-smoke-operator)
    REVIEWED_ROLES="agentgateway-read:social agentgateway-read:workspace"
    WRITE_ROLE_NAME=""
    ;;
  *) fail "unsupported immutable client" ;;
esac
validate_scoped_client_guards

login_admin
progress authenticated
run_scoped_client
