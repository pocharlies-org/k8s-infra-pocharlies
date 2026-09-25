# Keycloak SSO runbook

Keycloak is the active SSO stack. `auth-next.e-dani.com` is canonical and
`auth.e-dani.com` redirects here for old bookmarks.

## Current database location

Since 2026-08-11 Keycloak uses database `keycloak`, owned by role `keycloak`,
on `postgres-shared-rw.databases.svc.cluster.local`. Both namespaces project the
same 1Password credential from item `keycloak-next-postgres`; no password is
stored in Git. The former `keycloak/keycloak-postgres` cluster and its PVCs were
decommissioned on 2026-08-11 after the operator closed the rollback window.
Database recovery now follows the `postgres-shared` backup and restore runbook.

## 1. Seed 1Password items

The `onepassword` ClusterSecretStore resolves every `remoteRef.key` as
`<item>/<field label>` against the 1Password vault `k8s-pocharlies`, so the
item titles below are the ones the ExternalSecret manifests reference.

Required items (titles) and their fields:

```text
keycloak-next-bootstrap        admin_username, admin_password
keycloak-next-postgres         username, password
keycloak-next-oauth2-proxy     client_id, client_secret, cookie_secret
```

Using the 1Password CLI with a service account that has Read & Write on that
vault (`OP_SERVICE_ACCOUNT_TOKEN` set, never echoed):

```bash
op item create --vault k8s-pocharlies --category SECURE_NOTE \
  --title keycloak-next-bootstrap \
  admin_username=admin \
  admin_password="$(openssl rand -base64 36)"

op item create --vault k8s-pocharlies --category SECURE_NOTE \
  --title keycloak-next-postgres \
  username=keycloak \
  password="$(openssl rand -base64 36)"
```

Do not create `keycloak-next-oauth2-proxy` until Keycloak has been
bootstrapped and the confidential client exists.

Temporary Kubernetes secrets can be used if 1Password write access is
unavailable, but replace them with store-backed secrets when access is
restored.

## 2. Activate the stack

Add this resource to the root `/home/dibanez/k8s/k8s-infra-pocharlies/kustomization.yaml`:

```yaml
  - platform/keycloak-next
```

Sync with Argo. During the first sync, it is acceptable for oauth2-proxy to be
unready until the Keycloak realm/client is created and its secret is written to
1Password.

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
op item create --vault k8s-pocharlies --category SECURE_NOTE \
  --title keycloak-next-oauth2-proxy \
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

## 8. Independent OpenClaw read-only clients

Prerequisite fields on the 1Password item `keycloak-next-openclaw-readonly`
(vault `k8s-pocharlies`):

- `ui_client_secret` for `openclaw-readonly-ui`;
- `cookie_secret` for the dedicated oauth2-proxy;
- `agentgateway_client_secret` for `openclaw-readonly-agentgateway`.

The `onepassword` store resolves each `remoteRef.key` as `<item>/<field label>`,
so the manifests use keys such as
`keycloak-next-openclaw-readonly/ui_client_secret`.

Generate all three outside logs and shell history. Do not reuse the admin
oauth2-proxy secret, its cookie secret, or `agentgateway-mcp` credentials.

After the AgentGateway signed write-role policy is live, sync infra and require:

```bash
kubectl -n keycloak wait --for=condition=complete \
  job/keycloak-openclaw-readonly-clients --timeout=300s
kubectl -n keycloak logs job/keycloak-openclaw-readonly-clients \
  -c reconcile-clients
kubectl -n keycloak rollout status \
  deployment/oauth2-proxy-openclaw-readonly --timeout=300s
```

The client Job log may contain client IDs, email and
`"write_role_present":false`; it must never contain a secret or JWT. Before
enabling the OpenClaw chart, mint an operator token through a protected helper
that does not print it and run the AgentGateway list-only smoke. Known write
tools must be absent, a synthetic direct write call must be denied and the
admin token must remain unchanged.

For state rollback, first disable/prune the OpenClaw read-only plane. While this
revision's ConfigMap still exists, apply
`manual/openclaw-readonly-clients-rollback-job.yaml`, inspect its sanitized
`"present":false` output, and only then revert the oauth2-proxy/client manifests.
The rollback intentionally does not touch the retained OpenClaw PVC or its CSI
crypto key. It also does not require either dedicated client secret or a healthy
operator account: after authenticating with the bootstrap administrator it
deletes only the two immutable dedicated client IDs and verifies both are gone.
This is deliberate incident behavior, including when the service client has
accidentally acquired `agentgateway-write`. Already minted JWTs remain valid
until their short expiry, so keep the read-only Ingress/Deployment disabled
through at least that interval.

## 9. Synapse SRE service identity

The private SRE routes use one dedicated confidential service client,
`synapse-sre-orchestrator`, and one non-composite realm role,
`synapse-sre-m2m`. Neither the general `agentgateway-mcp` client nor a human
operator receives this role. The client has only the explicit
`mcp.lan.e-dani.com` audience and `fullScopeAllowed=false`.

Seed a new random value in the 1Password item `agentgateway-prod`, field
`synapse_sre_orchestrator_client_secret` (rotate with
`op item edit agentgateway-prod --vault k8s-pocharlies synapse_sre_orchestrator_client_secret=...`;
inline `op item edit` updates only that field — the full-replacement caveat
applies to `--template` only); never reuse
an OpenClaw webhook, AgentGateway operator or oauth2-proxy secret. Keep
`SRE_M2M_ENABLED=false` while syncing this identity. The PostSync hook must
finish with sanitized output:

The first reconciliation must be a full Argo CD sync of the reviewed commit.
Argo CD deliberately skips hooks during a selective resource sync; do not
pre-apply the identity resources or create the reconciliation Job manually.

```bash
kubectl -n keycloak wait --for=condition=complete \
  job/keycloak-synapse-sre-client --timeout=300s
kubectl -n keycloak logs job/keycloak-synapse-sre-client -c reconcile-client
```

The reconciler verifies the minted token contains the exact `azp`, audience
and SRE realm role, rejects `agentgateway-write`, and fails if the SRE role is
effective for any other service account, user or group. Only after this check,
the private Synapse/OpenClaw backends and their negative authorization smokes
may the AgentGateway kill switch be enabled by a separate PR.

For rollback, first set the AgentGateway kill switch false and wait one token
lifetime. The emergency rollback Job is deliberately excluded from Kustomize;
it deletes only the immutable client and its now-unmapped realm role. Run it
only during an authorized incident while the versioned ConfigMap still exists,
then verify its sanitized `"present":false` result and remove the Job.

## 10. AgentGateway read roles and grants (INFRA-23 H2 / INFRA-44)

The gateway's read routes are enforced one route at a time (H4..H24), each
requiring its own realm role `agentgateway-read:<route>`. This section is the
grant phase: it must be live and verified before any route gains its
`require:` (grant first, enforce second — no legitimate client loses access).

The PostSync reconciler `agentgateway-read-grants-job.yaml` (sync wave 20, so
it lands before the openclaw-readonly reconciler in wave 21) owns the full
read matrix:

- Creates the 21 `agentgateway-read:<route>` realm roles (non-composite).
- Grants them individually — never via groups (SC-44 C6): the
  `agentgateway-mcp` service account receives all 21; the
  `openclaw-readonly-agentgateway` service account receives its six reviewed
  routes (`synapse`, `synapse-tools`, `studio`, `gsc`, `offers`,
  `skirmshop-plugins`). `synapse-sre-orchestrator`,
  `synapse-draft-orchestrator` and `company-metrics-agentgateway` receive
  none.
- Maps the same roles into each client's role scope so the grants travel in
  minted tokens without `fullScopeAllowed` (SC-100 defect 6 family). Since
  INFRA-45 (section 11) the `agentgateway-mcp` scope additionally carries
  `agentgateway-write` explicitly, and the client's `fullScopeAllowed` is
  owned as `false` by this reconciler.
- Fails closed on any group mapping, any member outside the matrix, any
  composite role, any scope or grant entry outside the matrix, and any
  freshly minted token whose `realm_access.roles` is not exactly the measured
  set for the client's `fullScopeAllowed` state: 25 roles for
  `agentgateway-mcp` while the flag is true (the reviewed 22 including
  `agentgateway-write` plus the flattened `default-roles-edani` composites
  `default-roles-edani`, `offline_access` and `uma_authorization`, which pass
  the scope filter — measured 2026-09-12, INFRA-46) and exactly the reviewed
  22 once INFRA-45 has turned the flag off (section 11; the defaults do not
  travel with the flag off); 7 for `openclaw-readonly-agentgateway` including
  `cto-office-send`, measured 2026-09-12: with `fullScopeAllowed=false` the
  scope mapping filters the defaults out, so they must never appear there.

Check the hook result without printing any JWT or credential:

```bash
kubectl -n keycloak wait --for=condition=complete \
  job/keycloak-agentgateway-read-grants --timeout=2700s
kubectl -n keycloak logs job/keycloak-agentgateway-read-grants -c reconcile-read-grants
```

Expected sanitized output:

```json
{"reconciler":"agentgateway-read-grants","roles":21,"created":0,"grants_agentgateway_mcp":21,"grants_openclaw_agentgateway":6,"fullscope_allowed":false,"tokens_verified":true}
```

For state rollback (authorized incidents only, while the versioned ConfigMap
still exists), apply `manual/agentgateway-read-grants-rollback-job.yaml`. It
verifies every role's members are inside the reviewed matrix, then deletes the
21 roles — deleting a realm role cascades its service-account grants and
client scope mappings — and verifies nothing remains. Reverting Git alone
does not remove Keycloak state; the PostSync hook re-creates the matrix on
the next sync of a revision that still contains the reconciler. The
`agentgateway-write` role, its grant and its client scope mapping are NOT
touched by this Job (they predate the reconciler and carry write traffic while
`fullScopeAllowed=false`); to also restore the pre-INFRA-45 flag run the Job
in section 11. The two Jobs are order-independent.

## 11. AgentGateway fullScopeAllowed off (INFRA-23 H3 / INFRA-45)

`fullScopeAllowed` on `agentgateway-mcp` is now owned as `false`: the 22
token roles (`agentgateway-write` plus the 21 `agentgateway-read:<route>`)
travel exclusively through the client's explicit realm role scope. The same
wave-20 PostSync reconciler performs the change fail-closed, in this order:

1. Maps `agentgateway-write` into the client role scope (the service account
   has held the grant since the write-role reconciler; only the mapping was
   missing).
2. Mints a `client_credentials` token (audience `mcp.lan.e-dani.com`) and
   requires `realm_access.roles` to be exactly the measured 25 — the reviewed
   22 plus the three flattened realm defaults (`default-roles-edani`,
   `offline_access`, `uma_authorization`), which pass the scope filter while
   `fullScopeAllowed` is still true (INFRA-46 measurement) — BEFORE touching
   the flag: this proves the grants are intact before anything is removed.
3. Only then sets `fullScopeAllowed=false` and reads the flag back.
4. Mints again and requires exactly the reviewed 22 with the flag off — the
   roles now demonstrably travel through the client role scope alone, and the
   measured defaults are gone (they do not travel with the flag off).
5. If that post-flip token is off-matrix, the reconciler AUTO-RESTORES
   `fullScopeAllowed=true` before aborting: set, read back, and trusted only
   after a confirmation mint of the exact 25 again — the flip is the live step
   and the service account moves ~9465 requests per 4 h (measured baseline
   2026-09-12), so an abort must not leave its token broken. Only after the
   confirmed restoration does the hook fail. (When the flag was already false
   and the token is off-matrix, nothing is restored — that is drift or an
   attack, and the run fails closed without mutation.)
6. Asserts the matrix on every later run (scope = write+21, flag = false,
   final token = exact 22); anything outside aborts the hook.

Check the hook result (sanitized, no JWT):

```bash
kubectl -n keycloak wait --for=condition=complete \
  job/keycloak-agentgateway-read-grants --timeout=2700s
kubectl -n keycloak logs job/keycloak-agentgateway-read-grants -c reconcile-read-grants
```

Positive traffic control (the point of the change is that nothing breaks):
the `agentgateway-mcp` service account must keep moving its usual volume
through the gateway. Via Loki (same pipeline as INFRA-43, retention 168h):

```bash
kubectl -n monitoring port-forward svc/loki-gateway 3100:80 &
curl -sG "http://127.0.0.1:3100/loki/api/v1/query" \
  --data-urlencode 'query=sum(count_over_time({namespace="agentgateway"} |= "jwt.sub=2379d025-dfb6-433e-bd02-0f2aa9a5ae75" [4h]))'
# per-status: append e.g. |= "http.status=200" before [4h]
```

Compare the 4 h count before and after the sync (baseline measured
2026-09-12: 9465/4 h) and the status histogram: a mass of 401/403 after the
flip means roles stopped travelling and the rollback below applies.

Rollback honesty: `git revert` of the INFRA-45 commit alone does NOT restore
`fullScopeAllowed=true` — Keycloak state is not versioned, and while the
reconciler is in the tree its PostSync hook re-asserts `false`. During an
authorized incident, apply `manual/agentgateway-fullscope-rollback-job.yaml`
(excluded from Kustomize, same pattern as the grants rollback): it sets the
flag back to `true`, reads it back, mints a token and fails closed if the
roles fall outside the reviewed 22 plus the three measured defaults — with
the flag restored the fully intact token is the exact 25; `agentgateway-write`
plus the defaults is the accepted floor if the read grants were already
rolled back. Pair it with the `git revert`; until the revert syncs, the next
PostSync flips the flag back to `false`. Expected sanitized output:

```json
{"reconciler":"agentgateway-read-grants","mode":"fullscope-rollback","fullscope_allowed_agentgateway_mcp":true,"tokens_verified":true}
```

## 12. Chat service identity (`chat-agentgateway`)

Open WebUI at `chat.e-dani.com` reaches AgentGateway through an
`agentgateway-auth-proxy` sidecar that mints client-credentials tokens as
`chat-agentgateway`. The token carries the six reviewed domain roles
`agentgateway-write:` `gsc`, `hermes`, `media`, `social`, `synapse` and
`workspace` (created by the domain-roles hook, sync-wave 19); the umbrella
`agentgateway-write` is forbidden. Contract v2 (2026-09-17): the set was
`:media` alone while only `/studio` went through the sidecar; it grew when every
MCP tool server of the chat moved onto the sidecar and stopped carrying a
hand-pasted umbrella token.

**Before merging** the commit that adds this identity, seed the client secret;
without it the ExternalSecret never materializes and the PostSync hook pod
sits in `CreateContainerConfigError` until the sync fails:

```bash
# SC-490 (Vault -> 1Password): the ExternalSecret reads the 1Password item
# agentgateway-prod (vault k8s-pocharlies) via ClusterSecretStore "onepassword".
# `op item edit` touches only the named field, so the sibling tokens on the
# item are untouched. The field does not exist in the item yet (verified read
# 17-09): this seeding is the prerequisite, and the ExternalSecret stays
# Ready=False until it lands.
op item edit agentgateway-prod \
  chat_agentgateway_client_secret="$(openssl rand -base64 36)" \
  --vault k8s-pocharlies
```

The first reconciliation must be a full Argo CD sync (hooks are skipped on a
selective resource sync). Expected sanitized output:

```bash
kubectl -n keycloak wait --for=condition=complete \
  job/keycloak-chat-agentgateway-client --timeout=300s
kubectl -n keycloak logs job/keycloak-chat-agentgateway-client -c reconcile-client
# {"client_id":"chat-agentgateway","realm_roles":"agentgateway-write:gsc agentgateway-write:hermes agentgateway-write:media agentgateway-write:social agentgateway-write:synapse agentgateway-write:workspace","present":true,"exclusive_service_account":true}
```

On the next sync the domain-roles hook reports `"human_assigned":false` with one
service-account grant per reviewed role; any other holder of one of the six, or
this service account on a domain role outside the set, fails that hook and
therefore the whole sync.

The chat Deployment consumes the same Vault property through its own
ExternalSecret (in `dgx-infra`, `k8s/apps/chat`), so rotating the secret is one
`kv patch` followed by a sync here and a restart of the chat pod.

For rollback, apply `manual/chat-agentgateway-client-rollback-job.yaml` during
an authorized incident while the versioned ConfigMap still exists. It deletes
only the client (and with it the service account and its role grant) and
retains `agentgateway-write:media`; verify
`"client_present":false,"role_retained":true` and remove the Job.

## 13. AgentGateway MCP access token TTL (INFRA-187)

`agentgateway-mcp-token-ttl-job.yaml` (sync-wave 24, PostSync) owns exactly
one client attribute: `attributes."access.token.lifespan"` of
`agentgateway-mcp`, reconciled to **3600 s**. Before INFRA-187 the client
carried a 2592000 s (30 d) override (measured 2026-09-19), which let a stale
pre-grant token of the local `agentgateway-auth-proxy` keep authenticating
for days against the gated AgentGateway routes (INFRA-138/INFRA-139); with
1 h the proxy's own refresh (`expires_in − 60 s`) bounds how long any token
of this client can live. Roles, scope mappings, the secret and every other
attribute stay owned by the other reconcilers — this hook only verifies the
identity flags (`enabled`, `serviceAccountsEnabled`, `fullScopeAllowed`,
`standardFlowEnabled`) did not move across its write.

The attribute key contains dots, so `kcadm -s` cannot address it (it would
build nested paths); the hook read-modify-writes the full client document
with exactly the one value changed and fails closed if the override
attribute is absent (then the realm default applies — shorter, the safe
direction).

```bash
kubectl -n keycloak wait --for=condition=complete \
  job/keycloak-agentgateway-mcp-token-ttl --timeout=900s
kubectl -n keycloak logs job/keycloak-agentgateway-mcp-token-ttl -c reconcile-token-ttl
# {"client_id":"agentgateway-mcp","access_token_lifespan":"3600","previous":"2592000","in_sync":true}
# steady state: {"client_id":"agentgateway-mcp","access_token_lifespan":"3600","in_sync":true}
```

Rollback is a plain git revert: the target value lives in the script, so the
next PostSync restores the reverted TTL; no manual rollback Job is shipped.
Tokens minted before the change keep their old expiry — consumers that cache
tokens (the auth-proxy) must be restarted once to pick up the new lifespan.

## 14. AgentGateway roles→token smoke (INFRA-248)

`agentgateway-token-smoke-job.yaml` is a read-only PostSync hook in sync wave
26 — after every identity reconciler, so a failed smoke never holds one back.
It proves one rule for every gateway client without copying any role matrix:
the `realm_access.roles` of a freshly minted token equal the service
account's effective realm roles within the client's effective realm scope.

- Mints `chat-agentgateway`, `company-metrics-agentgateway` and the negative
  subject `cloudblue` (its service account holds only `default-roles-edani`;
  the smoke fails if it ever gains an `agentgateway-*` role, so the negative
  is re-chosen instead of passing silently).
- Does NOT mint `agentgateway-mcp` / `openclaw-readonly-agentgateway`: the
  section 10 reconciler mints and asserts them exactly in wave 20 (ruling
  C-5). Those two and the public `agentgateway-social-mcp` are checked by
  config: `fullScopeAllowed`, the `roles` default client scope and the realm
  scope mappings.
- Asserts the realm `roles` client scope maps realm roles to
  `realm_access.roles` in the access token.
- Secrets reach kcadm through `KC_CLI_PASSWORD` / `KC_CLI_CLIENT_SECRET`,
  never argv; only role names are logged. No realm mutation, so no rollback.

Evidence (one JSON line per client, then `"result":"PASS"`; the Job is kept
24 h):

```sh
kubectl logs -n keycloak job/keycloak-agentgateway-token-smoke
kubectl logs -n keycloak job/keycloak-agentgateway-read-grants   # agentgateway-mcp / openclaw tokens
```
