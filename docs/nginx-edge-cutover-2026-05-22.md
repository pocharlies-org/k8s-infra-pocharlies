# NGINX to Traefik Edge Cutover Prep - 2026-05-22

## Current state

- NGINX is still the public listener on Sauvage `:80` and `:443`.
- Traefik Edge is running in k8s on Sauvage with `hostNetwork`, currently on `:7080` and `:7443`.
- The desired final state is Traefik Edge on `:80` and `:443`, with NGINX stopped and retained for rollback.

## Backup

Readable NGINX config and host state were saved on Sauvage:

`/home/ubuntu/backups/k8s-legacy-decom/20260522-nginx-edge-cutover/`

Known backup limitation: the SSH user cannot read these root-only files without interactive sudo:

- `/etc/nginx/htpasswd-openclaw-images`
- `/etc/nginx/snippets/openclaw-gateway-authorization.conf`

## Routes Added To Traefik Edge

`networking/traefik-edge/legacy-public-routes.yaml` adds:

- standalone k8s public routes for `bundles.e-dani.com`, `sii.e-dani.com`, and `brain.e-dani.com/health`.
- k8s route for `skirmshop.e-dani.com/labels-cex` to `labels-correos-express-adapter`.
- temporary legacy host routes through `sauvage-localhost` for affiliate, SkirmBooks, Synapse webhooks/admin, OpenClaw webhooks, and selected SkirmShop legacy paths.
- `ExternalName: localhost` is intentional because Traefik Edge is pinned to Sauvage with `hostNetwork`.

The live DaemonSet was patched with:

`--providers.kubernetescrd.allowExternalNameServices=true`

The Helm release metadata is currently unhealthy/corrupt: `helm status traefik-edge -n traefik-edge` reports `superseded`, and `helm upgrade` fails with release storage errors. The running DaemonSet is healthy, but the Helm release must be repaired before relying on Helm for the final port cutover.

## Direct Traefik Checks

Checked from Sauvage against `https://127.0.0.1:7443` with Host headers:

- `firecrawl.e-dani.com /` without Authorization -> `401`
- `firecrawl.e-dani.com /` with the legacy Bearer -> `200`
- `firecrawl.e-dani.com /health` -> `200`
- `whatsapp.e-dani.com /` -> `302`
- `harbor.e-dani.com /` -> `200`
- `litellm.e-dani.com /health/readiness` -> `200`
- `skirmshop.e-dani.com /bundles/` -> `302`
- `skirmshop.e-dani.com /labels/health` -> `200`
- `skirmshop.e-dani.com /labels-ups/health` -> `200`
- `skirmshop.e-dani.com /picker/health` -> `200`
- `skirmshop.e-dani.com /sii/` -> `302`
- `skirmshop.e-dani.com /translations/` -> `302`
- `affiliate.skirmshop.es /health` -> `200`
- `go.skirmshop.es /health` -> `200`
- `openclaw.e-dani.com /gmail-pubsub` -> `405` on GET, expected for a push endpoint.
- `synapse.e-dani.com /webhooks/health` -> `404`, backend reachable but route does not expose a health endpoint.
- `skirmbooks.e-dani.com /` -> `302`

## Cutover Blockers

Do not stop NGINX until these are resolved or explicitly accepted:

- `firecrawl.e-dani.com`: resolved with `firecrawl-edge-auth`, a Traefik ForwardAuth shim that preserves the old Bearer check. The live Secret is intentionally not stored in Git and should be moved to Vault/ExternalSecret.
- `openclaw.e-dani.com /` and `/openclaw-mem/`: NGINX injects a root-only Authorization snippet that is not readable from this session.
- static file routes need a non-NGINX static service or object storage migration:
  - `skirmshop.e-dani.com/files/`
  - `cv.e-dani.com`
  - `cv-manu.e-dani.com`
  - `images.openclaw.e-dani.com`
  - `synapse.e-dani.com/attachments/`
- some NGINX routes point to legacy ports that are not currently listening, so Traefik correctly returns `502`:
  - `skirmshop.e-dani.com/sn`
  - `skirmshop.e-dani.com/collections-tree`
  - `skirmshop.e-dani.com/product-ai`
  - `skirmshop.e-dani.com/`
  - `sauvage.e-dani.com/healthz`
  - `qdrant.e-dani.com`
  - `rag.e-dani.com`
  - `webui.e-dani.com`

## Final Cutover Procedure

1. Repair the `traefik-edge` Helm release or replace it with a clean GitOps-managed release.
2. Provide equivalents for auth/static blockers above.
3. Stop NGINX on Sauvage.
4. Move Traefik Edge host ports from `7080/7443` to `80/443`.
5. Validate all public Host/path checks.
6. Keep `/etc/nginx` and the backup directory for 30 days.

Rollback is to restore Traefik Edge to `7080/7443` and start NGINX again.
