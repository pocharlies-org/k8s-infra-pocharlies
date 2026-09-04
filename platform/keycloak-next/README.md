# Keycloak SSO

This stack is the active SSO entry point for e-dani services.
`auth-next.e-dani.com` serves Keycloak and oauth2-proxy; `auth.e-dani.com`
redirects here for old bookmarks.

## Target shape

- `auth-next.e-dani.com` serves Keycloak.
- Keycloak stores its dedicated `keycloak` database and owner role in the
  shared CNPG cluster `databases/postgres-shared`; credentials remain sourced
  from Vault path `secret/keycloak-next/postgres`.
- `auth-next.e-dani.com/oauth2/*` serves oauth2-proxy.
- Apps that do not support OIDC use the Traefik middlewares in the `keycloak`
  namespace:
  - `sso-forward-auth`
  - `sso-errors`
  - `sso-chain`
- Apps with native OIDC should use Keycloak directly.
- Traefik Edge must watch the `keycloak` namespace. This is configured in
  `/home/dibanez/k8s/k8s-infra-pocharlies/networking/traefik-edge/values.yaml`.

## Vault prerequisites

Create these Vault paths before adding this stack to the root
`kustomization.yaml`:

- `secret/keycloak-next/bootstrap`
  - `admin_username`
  - `admin_password`
- `secret/keycloak-next/postgres`
  - `username`
  - `password`
- `secret/keycloak-next/oauth2-proxy`
  - `client_id`
  - `client_secret`
  - `cookie_secret`
- `secret/keycloak-next/openclaw-readonly`
  - `ui_client_secret`
  - `cookie_secret`
  - `agentgateway_client_secret`

The path above is Vault CLI notation. Because `vault-backend` already mounts
the KV-v2 engine at `secret/`, ExternalSecret `remoteRef.key` values must use the
relative key `keycloak-next/openclaw-readonly` and must not repeat `secret/`.

The oauth2-proxy client must be a confidential Keycloak client in the `edani`
realm. Use this callback:

```text
https://auth-next.e-dani.com/oauth2/callback
```

The Google identity provider callback in Keycloak will be:

```text
https://auth-next.e-dani.com/realms/edani/broker/google/endpoint
```

The live canary is configured with the Google OAuth client from the 1Password
item `Grafana Google OAuth - monitor.e-dani.com`. Add the callback above to
that Google Cloud OAuth client before expecting Gmail login to complete.

## Activation

This directory is referenced from the root kustomization. After the Vault
secrets and Google OAuth client exist:

1. Sync the Argo app.
2. Confirm the `keycloak` namespace is healthy.
3. Create the `edani` realm with groups:
   - `/edani-admins`
   - `/edani-operators`
4. Create a confidential client for oauth2-proxy and add a groups mapper.
5. Test a protected LAN or public route that references `keycloak/sso-chain`.

Protected services should reference the `keycloak/sso-chain` Traefik middleware
or the centralized `https://auth-next.e-dani.com/oauth2/auth` endpoint.

## PostgreSQL compartido

Keycloak moved from the dedicated `keycloak/keycloak-postgres` cluster to
`databases/postgres-shared/keycloak` on 2026-08-11. After the cutover and login
checks passed, the operator closed the rollback window the same day. The former
CNPG cluster, ScheduledBackup, four PVCs and obsolete one-shot migration Jobs
were removed. Recovery now uses the backups of `postgres-shared`.

## AgentGateway privileged write role

`agentgateway-write-role-job.yaml` is an idempotent Argo PostSync hook for the
existing confidential client `agentgateway-mcp`. It creates non-composite realm
role `agentgateway-write`, maps it directly to only
`service-account-agentgateway-mcp`, rejects any user or group mapping, and mints
a fresh client-credentials JWT to verify `realm_access.roles` without logging
the token or client secret.

This role must be cut over together with the OpenClaw privileged-plane allowlist
and the AgentGateway CEL policy. Do not sync this hook independently while the
shared OpenClaw gateway still admits operators. See `RUNBOOK.md` for the ordered
gate and explicit state rollback.

`agentgateway-domain-roles-job.yaml` creates the ten reviewed domain roles
without assigning them. The hook fails if one is composite, mapped to a group,
or held by any user other than the single reviewed service account in its
immutable `ALLOWED_SERVICE_ACCOUNTS` map (today only
`agentgateway-write:media=service-account-chat-agentgateway`). Every other
domain role stays unassigned until a dedicated client and a new map entry are
reviewed together; the global `agentgateway-mcp` client is never granted these
roles by this hook.

## Chat studio identity (`chat-agentgateway`)

`chat-agentgateway-client.yaml` reconciles the confidential client the chat
surface (Open WebUI at `chat.e-dani.com`) uses, through its
`agentgateway-auth-proxy` sidecar, to reach AgentGateway `/studio`. The client
has client credentials only, the exact `mcp.lan.e-dani.com` audience,
`fullScopeAllowed=false`, and exactly one realm role in its scope and on its
service account: `agentgateway-write:media`. The role itself is owned by the
domain-roles hook above; this reconciler refuses to run if it is missing and
never creates or deletes it. It fails if the service account holds any other
`agentgateway-write*` role, if a human or group holds `:media`, or if the minted
token carries the umbrella `agentgateway-write`. The client secret is the single
Vault property `secret/agentgateway/prod#chat_agentgateway_client_secret`; see
`RUNBOOK.md` §10 for seeding and rollback.

oauth2-proxy deliberately uses public URLs for browser redirects and internal
Keycloak service URLs for token/JWKS/userinfo calls. This avoids pod egress to
Cloudflare and IPv6 resolution issues while preserving the public OIDC issuer.

## OpenClaw read-only operator identity

`openclaw-readonly-clients.yaml` and its PostSync reconciler create two
dedicated clients for the independent `info@e-dani.com` plane:

- `openclaw-readonly-ui` has browser standard flow but no service account;
- `openclaw-readonly-agentgateway` has client credentials, the exact
  `mcp.lan.e-dani.com` audience and no effective `agentgateway-write` role.

The dedicated oauth2-proxy additionally accepts only the one email from its
mounted `authenticated_emails_file`; it forwards email/groups but no bearer to
Traefik. Both the proxy and reconciliation hook are fixed to the KS5 OVH pool,
tokenless and network-isolated from everything except Keycloak/DNS (plus
Traefik ingress for the proxy).

Do not sync these resources until the Vault path above is seeded and the
AgentGateway signed-role policy is live. The OpenClaw chart remains disabled
until the sanitized PostSync result reports `"write_role_present":false`.
State rollback is explicit and excluded from Argo. It authenticates only with
the Keycloak bootstrap administrator and deletes the two immutable dedicated
client IDs even if the operator was disabled, an application secret was lost,
or the service client accidentally acquired the forbidden write role:
`manual/openclaw-readonly-clients-rollback-job.yaml`.
