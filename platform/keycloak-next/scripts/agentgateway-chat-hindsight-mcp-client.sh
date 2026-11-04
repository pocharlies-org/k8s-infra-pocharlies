#!/bin/sh
set -eu

umask 077

# SC-4304 S6 (security ruling of 03-11-2026): the dedicated PUBLIC PKCE client
# of the Open WebUI connection to /chat-hindsight-personal, the chat twin of
# /hindsight-personal (bank `personal`: Dani's and Leila's personal memory,
# and nobody else — decision of Dani of 03-11-2026).
#
# Why a dedicated client and not the shared agentgateway-chat-mcp (option B of
# the ruling): agentgateway-chat-mcp is shared by every /chat-* route and its
# realm scope is exactly `agentgateway-write`; mapping the personal role into
# it would widen the token surface of every chat route at once. This client is
# the shared public-PKCE engine (agentgateway-chat-mcp-client.sh, which it
# execs — the jscpd dedup of #452) configured as the agentgateway-social-mcp
# pattern plus the explicit single-role realm scope: the hindsight-personal
# callback, SCOPE_AUDIT=exact (the scope mapping is audited as EXACTLY one
# role, never a subset), fullScopeAllowed=false (asserted by the engine in
# exact mode), and the role owned by the catalog (ROLES.yaml, created by
# security in SC-4051). With fullScopeAllowed=false, Keycloak 26 can emit
# agentgateway-read:hindsight-personal in this client's tokens for no other
# role and for no user who does not already hold it
# (UserRealmRoleMappingMapper -> RoleResolveUtil; measured by security in
# nota-security-c2-token.md). This reconciler never creates a role and never
# grants one to anyone — a scope mapping grants nothing, it only makes the
# role emittable by this client.
#
# Division of ownership:
#   * the gateway route names this clientId (k8s-agentgateway-pocharlies,
#     route chat-hindsight-personal; the Open WebUI connection id
#     `hindsight-personal` derives the exact callback below);
#   * the holder set of the role is owned by
#     agentgateway-hindsight-personal-grants.sh (wave 25);
#   * the catalog declarations (ROLES.yaml grantees, PRINCIPALS.md,
#     ROUTE-ROLES.md row) travel in the same PR (SC-4414).

export CLIENT_ID="${CLIENT_ID:-agentgateway-chat-hindsight-mcp}"
export EXPECTED_CLIENT_ID="agentgateway-chat-hindsight-mcp"
export REDIRECT_URIS="${REDIRECT_URIS:-https://chat.e-dani.com/oauth/clients/mcp:hindsight-personal/callback}"
export REALM_SCOPE_ROLE_NAMES="${REALM_SCOPE_ROLE_NAMES:-agentgateway-read:hindsight-personal}"
export EXPECTED_REALM_SCOPE_ROLE_NAMES="agentgateway-read:hindsight-personal"
export ROLE_OWNER="the catalog"
export SCOPE_AUDIT="exact"
export ADMIN_CONFIG="${ADMIN_CONFIG:-/tmp/kcadm-agentgateway-chat-hindsight-admin.config}"

exec /bin/sh "${0%/*}/agentgateway-chat-mcp-client.sh"
