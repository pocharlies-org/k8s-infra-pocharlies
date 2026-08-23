# Canonical hostnames on Traefik LAN and Edge

Date: 2026-08-22

## Outcome

Every service that had a `*.lan.e-dani.com` or `*.lan.skirmshop.es`
hostname also has one canonical hostname served by both ingress planes:

- AdGuard resolves the canonical name to the Traefik LAN VIP
  `192.168.50.240`.
- Public DNS uses the DNS-only `*.e-dani.com` wildcard, which aliases the
  existing four-address `images.openclaw.e-dani.com` edge record. Exact
  records continue to take precedence.
- The HTTP hostname is identical on both paths; DNS chooses the ingress.
- Legacy `.lan` names remain as compatibility aliases while consumers are
  migrated. This change does not delete or rename an active route contract.

The compatibility inventory contains 46 distinct legacy LAN hostnames. Of
those, 45 retain canonical split-DNS pairs and the active canonical inventory
has 45 endpoints. MultiChamber and the retired Sauvage webhook hostname are
not active canonical endpoints.

## Naming

The normal mapping removes `.lan`, for example
`grafana.lan.e-dani.com` becomes `grafana.e-dani.com`. Three existing public
names had different owners, so the collision-free active names are:

| Legacy hostname | Canonical hostname | Reason |
| --- | --- | --- |
| `openclaw-webhooks.lan.e-dani.com` | `openclaw-k8s-webhooks.e-dani.com` | the existing public name targets Sauvage |
| `s3.lan.e-dani.com` | `minio-s3.e-dani.com` | `s3.e-dani.com` is already a path router for other buckets |

`openclaw-sauvage.e-dani.com`, `multichamber.e-dani.com`, and
`openclaw-webhooks.e-dani.com` were retired after their Sauvage/x86 backends
were removed. Their LAN/Edge routes and AdGuard exact rewrites are deleted;
the public wildcard is intentionally not an exact per-host record. Producers
must use `openclaw-k8s-webhooks.e-dani.com` for the active Kubernetes webhook
endpoint; the retired webhook hostname is not redirected because replaying a
POST to a different consumer would be unsafe. The legacy
`openclaw.lan.e-dani.com` name now
returns a permanent redirect, preserving the request path, to the active K8s
instance at `https://openclaw.e-dani.com`; it is not counted as a canonical
Sauvage endpoint.

`admin.lan.skirmshop.es` maps to `admin.skirmshop.es` and has a dedicated
certificate because the `e-dani.com` wildcard cannot cover it.

## Authentication and exposure

Browser/admin routes on Edge use the shared Keycloak `sso-chain`. Existing
exact records retain their Cloudflare proxy setting; new wildcard-covered
names are DNS-only to stay compatible with machine endpoints. Keycloak and
oauth2-proxy need no per-host change: the
shared client returns through
`https://auth-next.e-dani.com/oauth2/callback`, and its cookie/whitelist
scope is `.e-dani.com`.

Machine endpoints that cannot follow an interactive SSO redirect are
DNS-only and retain their application authentication: AgentGateway,
DGX/Synapse MCP, social-media MCP, Picqer MCP, STT MCP, LiteLLM, and the MinIO
S3 API. Anonymous preflight requests reached those backends and were denied
by their bearer/API/S3 authentication. The typed AgentGateway tools,
allowlists, and mutation gates are unchanged; this is only an ingress
transport route, not a new API capability.

LAN routes retain the behavior of their legacy owner, including existing
trusted-network bypasses. Retired endpoints have no compatibility route when
their request semantics are unsafe to redirect.

## Ownership

- `networking/traefik-lan/canonical-hosts-lan.yaml`: added canonical LAN
  routes where the service owner did not already provide one.
- `networking/traefik-edge/canonical-hosts-public.yaml`: canonical public UI
  and machine routes, excluded from per-host ExternalDNS publication.
- `networking/traefik-edge/canonical-hosts-networkpolicy.yaml`: permits the
  four host-network Edge nodes to reach only port 8791 of OpenClaw Synapse.
- `networking/traefik-{lan,edge}/openchamber-*.yaml`: the stable route uses
  new `ExternalName` Services pointing to `x86.taile0ad27.ts.net:3000`.
  `networking/dns/coredns-custom.yaml` pins that name to `100.83.56.98` in
  its own `taile0ad27.ts.net:53` server block. The pin must not live in the
  `e-dani.com:53` block: CoreDNS only selects a server block that matches the
  queried suffix. This makes the route declarative across restores without
  Argo-excluded endpoint resources. The old selectorless Services and
  EndpointSlices are pruned by exact name after the new routes have converged.
- `k8s-adguard-pocharlies/k8s/adguard.yaml`: reconciles the canonical local
  rewrites into the persistent AdGuard configuration.
- `k8s-litellm-pocharlies/k8s/manifest.yaml`: leaves the old `.lan` alias
  app-owned and transfers the canonical hostname to central LAN/Edge routes.

## Verification and rollback

After GitOps convergence, verify that local DNS returns `192.168.50.240`,
public DNS returns the Edge targets, LAN requests hit Traefik LAN, browser
routes redirect to Keycloak when anonymous, and machine routes return their
backend authentication response rather than a Traefik 404/502.

Cloudflare's zone quota cannot hold four A records plus a TXT owner record for
every canonical host. The public wildcard is therefore manually owned, like
the existing LAN wildcard. Its rollback backup and invariants are documented
in `runbook-cloudflare-lan-record-budget.md`.

Rollback is the reverse deployment order: restore the LiteLLM canonical
host in its app route, remove the central canonical routes, then remove the
AdGuard rewrites. The legacy `.lan` aliases remain usable throughout.
