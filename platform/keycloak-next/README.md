# Keycloak SSO

This stack is the active SSO entry point for e-dani services.
`auth-next.e-dani.com` serves Keycloak and oauth2-proxy; `auth.e-dani.com`
redirects here for old bookmarks.

## Target shape

- `auth-next.e-dani.com` serves Keycloak.
- Keycloak stores its dedicated `keycloak` database and owner role in the
  shared CNPG cluster `databases/postgres-shared`; credentials remain sourced
  from 1Password item `keycloak-next-postgres` (vault `k8s-pocharlies`).
- `auth-next.e-dani.com/oauth2/*` serves oauth2-proxy.
- Apps that do not support OIDC use the Traefik middlewares in the `keycloak`
  namespace:
  - `sso-forward-auth`
  - `sso-errors`
  - `sso-chain`
- Apps with native OIDC should use Keycloak directly.
- Traefik Edge must watch the `keycloak` namespace. This is configured in
  `/home/dibanez/k8s/k8s-infra-pocharlies/networking/traefik-edge/values.yaml`.

## 1Password prerequisites

Create these 1Password items (vault `k8s-pocharlies`) before adding this stack
to the root `kustomization.yaml`:

- `keycloak-next-bootstrap`
  - `admin_username`
  - `admin_password`
- `keycloak-next-postgres`
  - `username`
  - `password`
- `keycloak-next-oauth2-proxy`
  - `client_id`
  - `client_secret`
  - `cookie_secret`
- `keycloak-next-openclaw-readonly`
  - `ui_client_secret`
  - `cookie_secret`
  - `agentgateway_client_secret`
- `keycloak-next-dgx-messages`
  - `client_secret`
  - `cookie_secret` (32 bytes, base64url)

The `onepassword` ClusterSecretStore resolves every ExternalSecret
`remoteRef.key` as `<item>/<field label>`, e.g.
`keycloak-next-openclaw-readonly/ui_client_secret`. Seeding recipes with the
`op` CLI are in `RUNBOOK.md`.

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

This directory is referenced from the root kustomization. After the 1Password
items and Google OAuth client exist:

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

`agentgateway-domain-roles-job.yaml` creates the twelve reviewed domain roles
without assigning them (`agentgateway-write:dgx-control` joined inert in
INFRA-249: no allowlist entry, so its three gated tools stay denied). The hook fails if one is composite, mapped to a group,
or held by any user other than the single reviewed service account in its
immutable `ALLOWED_SERVICE_ACCOUNTS` map (today the six chat pairs:
`:media`, `:social`, `:workspace`, `:gsc`, `:synapse` and `:hermes`, all of them
`=service-account-chat-agentgateway`). Every other domain role stays unassigned
until a dedicated client and a new map entry are reviewed together; the global
`agentgateway-mcp` client is never granted these roles by this hook.

## Chat identity (`chat-agentgateway`)

`chat-agentgateway-client.yaml` reconciles the confidential client the chat
surface (Open WebUI at `chat.e-dani.com`) uses, through its
`agentgateway-auth-proxy` sidecar, to reach AgentGateway. The client has client
credentials only, the exact `mcp.lan.e-dani.com` audience,
`fullScopeAllowed=false`, and the REVIEWED SET of realm roles in its scope and
on its service account: `agentgateway-write:` `gsc`, `hermes`, `media`,
`social`, `synapse`, `workspace` (contract v2, 2026-09-17 — it was `:media`
alone while only `/studio` went through the sidecar). Those six are exactly the
domains the chat already reached with the hand-pasted umbrella token its MCP
tool servers used until that date, so moving every server onto the sidecar loses
no capability and drops the umbrella's reach over shopify, picqer,
skirmshop-plugins, offers and sauvage. The roles are owned by the domain-roles
hook above; this reconciler refuses to run if one is missing and never creates
or deletes them. It fails if the service account holds ANY `agentgateway-write*`
role outside the set, if a human or group holds one of them, or if the minted
token carries the umbrella `agentgateway-write`. The client secret is the single
field `chat_agentgateway_client_secret` of the 1Password item
`agentgateway-prod`; see `RUNBOOK.md` §12 for seeding and rollback.

oauth2-proxy deliberately uses public URLs for browser redirects and internal
Keycloak service URLs for token/JWKS/userinfo calls. This avoids pod egress to
Cloudflare and IPv6 resolution issues while preserving the public OIDC issuer.

## OpenClaw read-only operator identity

`openclaw-readonly-clients.yaml` and its PostSync reconciler create two
dedicated clients for the independent `info@e-dani.com` plane:

- `openclaw-readonly-ui` has browser standard flow but no service account;
- `openclaw-readonly-agentgateway` has client credentials, the exact
  `mcp.lan.e-dani.com` audience, no effective `agentgateway-write` role, and
  a client-level role scope mapping that limits its tokens to exactly the
  `cto-office-send` realm role; `fullScopeAllowed` stays false so no other
  realm role — present or future — can ever be emitted by this client. The
  reconciler also guarantees the grant itself: it idempotently maps
  `cto-office-send` onto the client's service account (and fails closed if
  the role is absent from the realm rather than creating it). The grant is
  therefore not revocable operationally without a code change — `MODE=rollback`
  deletes both dedicated clients — and the control designed for the emergency
  is the AgentGateway `CTO_OFFICE_WRITE` kill-switch.

The dedicated oauth2-proxy additionally accepts only the one email from its
mounted `authenticated_emails_file`; it forwards email/groups but no bearer to
Traefik. Both the proxy and reconciliation hook are fixed to the KS5 OVH pool,
tokenless and network-isolated from everything except Keycloak/DNS (plus
Traefik ingress for the proxy).

Do not sync these resources until the 1Password item above is seeded and the
AgentGateway signed-role policy is live. The OpenClaw chart remains disabled
until the sanitized PostSync result reports `"write_role_present":false`.
State rollback is explicit and excluded from Argo. It authenticates only with
the Keycloak bootstrap administrator and deletes the two immutable dedicated
client IDs even if the operator was disabled, an application secret was lost,
or the service client accidentally acquired the forbidden write role:
`manual/openclaw-readonly-clients-rollback-job.yaml`.

## dgx-messages (`messages.lan.e-dani.com`, SC-1198)

LAN-only messages app behind its own proxy and its own client, because the
`/social` panel forwards the session access token to social-api, which only
accepts `azp=dgx-messages` with `social-api` in `aud`:

- `dgx-messages-client.yaml` + `scripts/dgx-messages-client.sh` (PostSync)
  reconcile the confidential client `dgx-messages`: standard flow only, no
  service account, `fullScopeAllowed=false`, exact redirect
  `https://messages.lan.e-dani.com/oauth2/callback`, PKCE S256, an Audience
  mapper `social-api` on the access token only and a full-path groups mapper.
  The Job fails if the registered redirect is not exactly that one, or if the
  example access token for Dani (Admin API `evaluate-scopes`) lacks
  `azp=dgx-messages`, `aud` with `social-api` or an `/edani-*` group.
- `oauth2-proxy-messages.yaml`: the proxy (`allowed_groups` edani
  admins/operators/users, host-only cookie `_messages_sso`,
  `cookie_refresh=4m` against the realm's 5 min `accessTokenLifespan`), ingress
  only from traefik-lan, and the middlewares `sso-messages-forward-auth`
  (the app's `/api`: 401 without session), `sso-messages-errors` and
  `sso-messages-chain` (the UI: 302 to Keycloak). The IngressRoute that uses
  them lives in the `dgx-messages` repo.
- Rollback: `manual/dgx-messages-client-rollback-job.yaml`, after taking the
  middlewares off the IngressRoute.

## Synapse SRE M2M identity

`synapse-sre-client.yaml` reconciles the `synapse-sre-orchestrator` client
and its sibling `synapse-draft-orchestrator`, both with
`fullScopeAllowed=false`. For `synapse-sre-orchestrator` the client
realm-role scope mapping must be exactly `synapse-sre-m2m` plus
`cto-office-send`: without the second entry the grant on the service account
is inert and its client_credentials token carries only `synapse-sre-m2m`
(the same "granted but inert" defect fixed for the OpenClaw clients in
#104/#105). The reconciler idempotently ensures both the client scope
mapping and the grant, asserts the minted token carries exactly those two
realm roles, and fails closed if `cto-office-send` disappears from the realm
rather than creating it. `synapse-draft-orchestrator` keeps exactly
`synapse-draft-m2m` and never gains `cto-office-send`. The emergency control
remains the AgentGateway `CTO_OFFICE_WRITE` kill-switch.

## AgentGateway social MCP public client

`agentgateway-social-mcp-client.yaml` reconciles the public client
`agentgateway-social-mcp` used by the AgentGateway `mcpAuthentication` policy
on the `/social` route (SC-552 Parte 1 / SC-600). It is the pre-registered
client the gateway short-circuits MCP Dynamic Client Registration to, so
Open WebUI can run the authorization-code + PKCE flow against the `edani`
realm without a client secret. The reconciler pins `publicClient=true` with no
secret, `standardFlowEnabled=true`, direct access / implicit / service accounts
off, `fullScopeAllowed=false`, PKCE `S256`, the exact redirect URI
`https://chat.e-dani.com/oauth/clients/mcp:social/callback` (no wildcards) and
the house `oidc-audience-mapper` `aud-mcp`
(`included.custom.audience=mcp.lan.e-dani.com`, access and introspection token
claims only). It changes no realm registration policy. Being public it carries
no secret, so there is no `ExternalSecret` and no minted-token check; the
reconciler asserts the flow flags, the redirect URI, the PKCE attribute and the
mapper and fails closed. State rollback deletes the client
(`manual/agentgateway-social-mcp-client-rollback-job.yaml`, excluded from Argo).

## AgentGateway MCP access token TTL (`agentgateway-mcp`)

`agentgateway-mcp-token-ttl-job.yaml` (INFRA-187) owns the single client
attribute `access.token.lifespan` of the confidential client
`agentgateway-mcp`, reconciled to 3600 s (was a 30-day override; a stale
pre-grant token of the local auth-proxy could then authenticate for days
against the gated AgentGateway routes — INFRA-138/INFRA-139). It is the
narrowest reconciler in this platform: it read-modify-writes exactly that
one value in the client document, never creates the client, touches no
role, scope mapping, secret or other attribute, and fails closed if the
identity flags move across its write. Rollback is a git revert (RUNBOOK
section 13).

## Realm role catalog (`ROLES.yaml`, INFRA-219 C1)

`ROLES.yaml` is the contract registry of every realm role of `edani`: per
role its `meaning`, the exact `grantees` (usernames holding it *directly*,
not through a composite), the `privilege` it allows and denies, its `origin`
(the reconciler or epic that creates it, or `keycloak-builtin`) and
`status`. It is JSON, which is valid YAML 1.2, read with `json.load` — no
PyYAML.

- **An entry is never deleted.** A retired role changes to
  `status: deprecated`; the verifier accepts a deprecated role whether it is
  still in the realm or gone. On every pull request CI fetches the trunk
  copy and runs `scripts/check-catalog-evolution.py`: a trunk role missing
  from the branch, or a trunk `deprecated` role back to `active`, fails the
  job (skipped, with a `SKIP:` line, while the trunk has no `ROLES.yaml`).
- A composite role lists in `composites` the exact realm roles it contains
  and in `client_composites` the exact client roles, by `clientId` (today
  `default-roles-edani` → `account`: `manage-account`, `view-profile`);
  absent = none. The verifier reads `roles/{name}/composites` for every
  catalogued role, so a realm or client role (e.g. `realm-management`
  `view-users`) added to or removed from a composite such as
  `default-roles-edani` is drift even though nobody holds it directly.
- A new role, grant or revoke lands in `ROLES.yaml` in the same PR as the
  reconciler change. The roles owned by `agentgateway-read-grants.sh` and
  `agentgateway-domain-roles.sh` must match those scripts' `EXPECTED_*`
  matrices (`tests/test_keycloak_rbac_parity_contract.py`).
- No catalogued role may be mapped to a group (R2).
- `default-roles-edani` lists every user and service account: Keycloak grants
  it on creation, so a new principal shows up as drift until it is added.

Check it against the live realm (read-only; local flow of the
`keycloak-admin` skill: `keycloak/keycloak-automation` is written to a 0600
netrc that is deleted once the token is minted, never passed through argv):

```bash
KUBECONFIG=~/.kube/config python3 platform/keycloak-next/scripts/verify-role-catalog.py
# OK: <N> roles en catálogo, 0 sin catalogar, 0 catalogados inexistentes  -> exit 0
# DRIFT: <finding>, one line each                                        -> exit 1
# ERROR: <auth/network/catalog>                                          -> exit 2
```

`--catalog <path>` checks another copy. In-cluster it authenticates with
client credentials read from mounted files: `KEYCLOAK_URL`,
`KC_CLIENT_ID_FILE`, `KC_CLIENT_SECRET_FILE` (optional `KC_REALM`,
`KC_TOKEN_REALM`). `scripts/kc_rbac.py` is the shared stdlib library of these
verifiers: auth, paginated admin reads, and `load_json_block`, the single
parser of the one json fenced block that markdown contracts
(`PRINCIPALS.md`, `ROUTE-ROLES.md`) carry. CI job `keycloak-rbac-contract`
runs `tests/test_keycloak_rbac_*.py` against a fake Keycloak on loopback.

## Route×role matrix (`ROUTE-ROLES.md`, INFRA-219 C3)

`ROUTE-ROLES.md` records which realm role each AgentGateway route requires,
measured against the **live** ConfigMap `agentgateway/agentgateway-config`
(route-level role and, per role, the exact gated tools), plus the gateway
roles no route requires and why they exist. Its single json block is what the
verifier reads. Check it (read-only):

```bash
KUBECONFIG=~/.kube/config python3 platform/keycloak-next/scripts/verify-route-roles.py
# OK: <N> gates coherentes, 0 roles referenciados inexistentes, 0 roles sin ruta documentada  -> exit 0
# DRIFT: <finding>, one line each                                                          -> exit 1
# ERROR: <kubectl/auth/network/parse/matrix>                                               -> exit 2
```

A gate change in `k8s-agentgateway-pocharlies` needs its row updated here.
