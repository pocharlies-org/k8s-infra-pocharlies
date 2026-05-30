# Edge HA — multi-A DNS over the 4 edge nodes

Status: **LIVE since 2026-05-30**.

After the KS-5-A HA rollout the public Traefik **edge** runs as a hostNetwork
DaemonSet on **4 nodes** (label `ingress=true`):

| node      | public edge IP   |
|-----------|------------------|
| sauvage   | `57.129.17.172`  |
| ks5-cp-1  | `141.94.73.52`   |
| ks5-cp-2  | `141.94.73.50`   |
| ks5-cp-3  | `145.239.194.168`|

Before this change every public hostname resolved to **sauvage only** → sauvage
was a single point of failure for *all* external traffic (storefront included).

Now each customer-facing / app hostname is a **Cloudflare multi-A** record set
(all 4 edge IPs, CF-proxied). Cloudflare load-balances across the 4 origins and
retries another origin on a connection failure, so one edge node down only
degrades a fraction of requests instead of taking the whole edge offline.

**Failover-tested 2026-05-30**: deleting a KS-5 edge pod while hammering
litellm.e-dani.com gave 30/30 HTTP 200 (CF retried healthy origins).

## Hostnames under multi-A (16)

`e-dani.com` (13): skirmshop, bundles, sii, firecrawl, cv-manu, litellm,
whatsapp, alexa, jarvis-alexa, home-assistant, tm, n8n, n8n-stg
`skirmshop.es` (3): track, affiliate, go

`skirmshop.e-dani.com` is the Shopify storefront proxy and also the host for all
the path-routed Shopify apps (bundles-app, rag-app, sii-app, labels, picker,
translations, chatbot, serial, collections-tree…), so the one record covers them.

## Why direct Cloudflare API, not external-dns annotations  (GOTCHA)

external-dns runs with **`--policy=upsert-only`**. It will create new records and
never delete, but it does **not** rewrite the target SET of an *existing*
A-record when the source `external-dns.alpha.kubernetes.io/target` annotation
changes — it logs *"all records are already up to date"* and does nothing.
So bumping the annotation to 4 IPs is a **no-op** for records that already exist.

The flip side is what makes the direct approach safe: because upsert-only
**never deletes**, A-records we add via the Cloudflare API are left untouched by
external-dns. The CF API is therefore the source of truth for the multi-A set,
and `scripts/edge_multiA_apply.py` is the reproducible, idempotent applier.

> NOTE (parallel-session overlap, 2026-05-30): a concurrent session committed
> `feat(edge): HA public ingress — repoint traefik-edge targets to the 4 edge
> nodes` (the external-dns annotation approach) to main. Because external-dns is
> upsert-only, that commit is a no-op on the already-existing records; the LIVE
> multi-A is the CF-API set from this script. Pick one canonical approach.

## Apply / re-apply (reproducible)

```bash
export CLOUDFLARE_API_TOKEN=...          # zone IDs resolved by name
python3 scripts/edge_multiA_apply.py --verify     # audit
python3 scripts/edge_multiA_apply.py --dry-run    # preview
python3 scripts/edge_multiA_apply.py              # apply (idempotent)
```

Idempotent: only ADDS missing KS-5 IPs, never deletes, no duplicates, and only
touches hostnames whose record set still includes sauvage.

## Deliberately NOT multi-A

* **Non-proxied (grey-cloud) admin hostnames**: `cortex`, `cv`, `fleet`,
  `monitor`, `skirmbooks`. Without the CF proxy, multi-A gives the client **no
  failover** (the resolver picks one A at random; if that node is down the client
  just fails). Left on sauvage only on purpose. To make them HA, first turn on
  the CF proxy (orange cloud), then add them to `ZONES` in the script.
* **Infra hostnames targeting the *name* `sauvage.e-dani.com`** (CNAME-style):
  `brain`, `harbor`, `openclaw-webhooks`, `openclaw-images`. Out of scope for
  storefront HA.
* **External / non-edge A-records**: `claude-dgx`, `dgx`, `e-dani`, `server`,
  `webhooks` (not served by the edge).

## Rollback

Multi-A is purely additive. To revert a hostname to sauvage-only, delete its 3
KS-5 A-records in Cloudflare (the sauvage record is never touched). Pre-change
DNS snapshots were taken under `docs/dns-backups/` (gitignored, local on the
machine that ran the rollout).

## Known cosmetic issue

`go.skirmshop.es` had a **pre-existing duplicate** sauvage A-record (2×
`57.129.17.172`) before this change — left as-is (harmless; CF dedups at the
edge). Tidy-up: delete one of the two identical records.
