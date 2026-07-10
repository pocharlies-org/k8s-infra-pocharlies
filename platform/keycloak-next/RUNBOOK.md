# Keycloak SSO runbook

Keycloak is the active SSO stack. `auth-next.e-dani.com` is canonical and
`auth.e-dani.com` redirects here for old bookmarks.

## 1. Seed Vault secrets

The `vault-backend` ClusterSecretStore is mounted at Vault KV path `secret` and
the ExternalSecret keys below intentionally match the existing repo convention.

Required ExternalSecret remoteRef keys:

```text
secret/keycloak-next/bootstrap
secret/keycloak-next/postgres
secret/keycloak-next/oauth2-proxy
```

If using the Vault CLI against the `secret` mount, that means commands use
paths like:

```bash
vault kv put secret/secret/keycloak-next/bootstrap \
  admin_username=admin \
  admin_password="$(openssl rand -base64 36)"

vault kv put secret/secret/keycloak-next/postgres \
  username=keycloak \
  password="$(openssl rand -base64 36)"
```

Do not write `secret/keycloak-next/oauth2-proxy` until Keycloak has been
bootstrapped and the confidential client exists.

Temporary Kubernetes secrets can be used if Vault write access is unavailable,
but replace them with Vault-backed secrets when Vault access is restored.

## 2. Activate the stack

Add this resource to the root `/home/dibanez/k8s/k8s-infra-pocharlies/kustomization.yaml`:

```yaml
  - platform/keycloak-next
```

Sync with Argo. During the first sync, it is acceptable for oauth2-proxy to be
unready until the Keycloak realm/client is created and its secret is written to
Vault.

Traefik Edge must watch the `keycloak` namespace. Keep
`/home/dibanez/k8s/k8s-infra-pocharlies/networking/traefik-edge/values.yaml`
and the Helm release aligned before expecting public routes to work.

## 3. Bootstrap Keycloak

Open:

```text
https://auth-next.e-dani.com
```

Create:

- Realm: `edani`
- Groups:
  - `/edani-admins`
  - `/edani-operators`
- Google identity provider with callback:

```text
https://auth-next.e-dani.com/realms/edani/broker/google/endpoint
```

The live canary currently uses the 1Password item
`Grafana Google OAuth - monitor.e-dani.com` as the Google OAuth credential
source. That OAuth client originally had `https://monitor.e-dani.com/login/google`
as its redirect URI, so Google Cloud must also authorize the Keycloak callback
above before Gmail login can complete.

Create a confidential OIDC client for oauth2-proxy:

- Client ID: `oauth2-proxy`
- Valid redirect URI:

```text
https://auth-next.e-dani.com/oauth2/callback
```

- Valid post logout redirect URI:

```text
https://auth-next.e-dani.com/*
```

Add a groups mapper so oauth2-proxy receives a `groups` claim.

## 4. Seed oauth2-proxy secret

After creating the Keycloak client:

```bash
vault kv put secret/secret/keycloak-next/oauth2-proxy \
  client_id=oauth2-proxy \
  client_secret="<client secret from Keycloak>" \
  cookie_secret="$(openssl rand -base64 32)"
```

Force-sync the ExternalSecret if needed:

```bash
kubectl annotate externalsecret -n keycloak oauth2-proxy-secrets \
  force-sync="$(date +%s)" --overwrite
```

## 5. Verify a protected route

Open a route that uses the `keycloak/sso-chain` middleware, for example
`https://dgx.e-dani.com/` or a non-bypassed public admin route.

Expected flow:

1. Redirect to Keycloak at `auth-next.e-dani.com/realms/edani/...`.
2. Login with Google, or with the local break-glass user before Google is wired.
3. User is accepted only if it belongs to `/edani-admins` or `/edani-operators`.
4. The original service receives oauth2-proxy auth headers such as
   `X-Auth-Request-Email`.

## 6. Protect services

For Traefik routes, attach:

```yaml
middlewares:
  - name: sso-chain
    namespace: keycloak
```

For external Nginx `auth_request` checks, use:

```text
https://auth-next.e-dani.com/oauth2/auth
```

## 7. Coordinated AgentGateway write-role cutover

The live `agentgateway-mcp` client is confidential, has service accounts enabled,
and currently has only Keycloak default roles. OpenClaw uses that one service
identity for every browser session, so the role must not be granted until the
privileged OpenClaw plane is restricted to admins.

Required changes:

- OpenClaw privileged-plane PR: <https://github.com/pocharlies-org/k8s-openclaw-qwen36-pocharlies/pull/24>
- AgentGateway CEL policy PR: <https://github.com/pocharlies-org/k8s-agentgateway-pocharlies/pull/2>
- this Keycloak bootstrap PR

Do not merge or sync any of the three independently. During the approved window:

1. pause new OpenClaw work and confirm the Telegram/social plane is unaffected;
2. sync the admin-only OpenClaw plane (PR 24); its MCP proxy fails closed until
   the service token has the role;
3. sync this infra revision. The PostSync hook creates/maps the role and emits
   only a sanitized JSON assertion such as:

   ```json
   {"client_id":"agentgateway-mcp","realm_role":"agentgateway-write","present":true,"exclusive_service_account":true}
   ```

4. inspect the hook result without printing a JWT or credential:

   ```bash
   kubectl -n keycloak logs job/keycloak-agentgateway-write-role -c reconcile-role
   ```

5. sync the AgentGateway CEL policy (PR 2);
6. run its list-only two-token smoke. The operator token must retain reads and
   see no write tools; the admin token must see representative write tools;
7. run the OpenClaw Workboard and strict Codex smokes.

The hook is idempotent. It refuses to proceed if `agentgateway-write` is
composite, mapped to a group, mapped to any user other than the exact service
account, or missing from a freshly minted service token.

### State rollback

Reverting Git alone does not remove a Keycloak database role. Roll back explicitly:

1. first set `GATEWAY_WRITE=false` and `SOCIAL_WRITE_RULE=false` in the
   AgentGateway production overlay and verify mutating tools are absent;
2. keep operators denied from the privileged OpenClaw plane;
3. apply the manual rollback Job (it is deliberately excluded from Kustomize):

   ```bash
   kubectl apply -f platform/keycloak-next/manual/agentgateway-write-role-rollback-job.yaml
   kubectl -n keycloak wait --for=condition=complete \
     job/keycloak-agentgateway-write-role-rollback --timeout=300s
   kubectl -n keycloak logs job/keycloak-agentgateway-write-role-rollback -c rollback-role
   kubectl -n keycloak delete job keycloak-agentgateway-write-role-rollback
   ```

4. expect sanitized output with `"present":false`; then revert the three Git
   changes as required. Never restore the former boolean-only write policy while
   an operator shares the privileged OpenClaw runtime.

The rollback Job fails before mutation if it finds any unexpected user or group
assignment, so it cannot silently remove authority that GitOps did not create.

Official references:

- Keycloak service accounts and role scope intersection:
  <https://www.keycloak.org/docs/latest/server_admin/index.html>
- Keycloak Admin REST role mappings:
  <https://www.keycloak.org/docs-api/latest/rest-api/index.html>
