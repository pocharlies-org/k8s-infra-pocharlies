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

The inventory contained 46 distinct legacy LAN hostnames. Together with the
canonical-only `multichamber.e-dani.com` endpoint, the split-DNS inventory has
47 endpoints. The routing contract test checks that every legacy name has both
a LAN and an Edge destination, using existing routes where the canonical side
already existed.

## Naming

The normal mapping removes `.lan`, for example
`grafana.lan.e-dani.com` becomes `grafana.e-dani.com`. Three existing public
names had different owners, so the collision-free names are:

| Legacy hostname | Canonical hostname | Reason |
| --- | --- | --- |
| `openclaw.lan.e-dani.com` | `openclaw-sauvage.e-dani.com` | `openclaw.e-dani.com` is the K8s instance |
| `openclaw-webhooks.lan.e-dani.com` | `openclaw-k8s-webhooks.e-dani.com` | the existing public name targets Sauvage |
| `s3.lan.e-dani.com` | `minio-s3.e-dani.com` | `s3.e-dani.com` is already a path router for other buckets |

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
trusted-network bypasses. MultiChamber is the deliberate exception: both
LAN and Edge require Keycloak because it can resume sessions and execute as
the x86 user. The `/api` and `/auth` paths retain `sso-forward-auth`; the UI
uses `sso-chain`. There is no `ClientIP` bypass.

The design was checked against Claude session
`8647ab8d-1bdb-4afd-9c08-ec1644a5bed4` (2026-08-21). That session implemented
MultiChamber as Edge-only and explicitly omitted an AdGuard override. This
change adds the missing LAN half while preserving its Keycloak boundary.

## Ownership

- `networking/traefik-lan/canonical-hosts-lan.yaml`: added canonical LAN
  routes where the service owner did not already provide one.
- `networking/traefik-edge/canonical-hosts-public.yaml`: canonical public UI
  and machine routes, excluded from per-host ExternalDNS publication.
- `networking/traefik-edge/canonical-hosts-networkpolicy.yaml`: permits the
  four host-network Edge nodes to reach only port 8791 of OpenClaw Synapse.
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
