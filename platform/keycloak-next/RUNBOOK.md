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
