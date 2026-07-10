# Keycloak SSO

This stack is the active SSO entry point for e-dani services.
`auth-next.e-dani.com` serves Keycloak and oauth2-proxy; `auth.e-dani.com`
redirects here for old bookmarks.

## Target shape

- `auth-next.e-dani.com` serves Keycloak.
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
State rollback is explicit and excluded from Argo:
`manual/openclaw-readonly-clients-rollback-job.yaml`.
