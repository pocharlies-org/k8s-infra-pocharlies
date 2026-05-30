# Edge HA — multi-A DNS over the 4 edge nodes

Status: **PARTIAL/LIVE since 2026-05-30** — see the split below. The edge *runs*
on all 4 nodes; whether each hostname is multi-A depends on who owns its DNS.

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

The goal: each customer-facing hostname is a **Cloudflare multi-A** record set
(all 4 edge IPs, CF-proxied). Cloudflare load-balances across the 4 origins and
retries another origin on a connection failure.

**Edge DaemonSet failover-tested 2026-05-30**: deleting a KS-5 edge pod while
hammering a multi-A hostname gave 30/30 HTTP 200.

## THE KEY GOTCHA — two classes of DNS record (verified 2026-05-30)

external-dns runs with **`--policy=upsert-only`**. This is widely misread. What
it actually means:

* It **never deletes** records.
* But for records external-dns **OWNS** (it planted the matching TXT registry
  entry, e.g. `a-litellm.e-dani.com`), it **DOES update them to match the
  desired state** derived from the Service/Ingress/IngressRoute `target`
  annotation, on every reconcile (~1 min).

So a hostname's behaviour depends on ownership:

| class | how to make it 4-IP multi-A | adding A-records by CF API |
|---|---|---|
| **external-dns-OWNED** (has `a-<host>` TXT) | set the `external-dns.alpha.kubernetes.io/target` annotation to the 4 IPs (comma-sep) | **REVERTED to 1 within ~1 min** |
| **MANUAL** (no external-dns TXT) | add the A-records (CF API / dashboard) | **persists** (external-dns doesn't own it) |

Verified 2026-05-30 (nonce `OWN-1780141452`): after adding 3 KS-5 A-records to
every edge hostname via the CF API, the 7 **owned** hostnames reverted to 1 A
within a minute; the 6 **manual** ones stayed at 4 A.

## Current live state (2026-05-30)

**Stable multi-A (MANUAL records, 4 IPs each) — the e-commerce/storefront set:**
`skirmshop.e-dani.com` (Shopify storefront proxy + ALL path-routed apps:
bundles-app, rag-app, sii-app, labels, picker, translations, chatbot, serial,
collections-tree…), `bundles`, `sii`, `firecrawl`, `cv-manu`, `whatsapp`
(e-dani.com) + `track`, `affiliate`, `go` (skirmshop.es).
→ **This is the HA that matters for the business; it is live and stable.**

**Still single-origin (external-dns-OWNED) — needs the annotation fix:**
`litellm`, `alexa`, `home-assistant`, `jarvis-alexa`, `n8n`, `n8n-stg`, `tm`
(all e-dani.com). These reverted to sauvage-only — **no regression vs before**,
just not yet HA.

## How to finish the owned set (the CORRECT, durable way)

Set the 4 edge IPs in the `external-dns.alpha.kubernetes.io/target` annotation of
each owning Service/IngressRoute and let external-dns publish them. This is what
the parallel session's commit `0bbb01b feat(edge): HA public ingress — repoint
traefik-edge targets to the 4 edge nodes` does — that approach is the right one
for owned records (and was previously mischaracterised here as a no-op; it is
not). Prefer routing that change through GitOps/deploy-prod (ArgoCD) rather than
racing external-dns with the CF API.

## scripts/edge_multiA_apply.py

Idempotent CF-API applier. Correct and useful **only for the MANUAL hostname
set** (it is what made the storefront 4-IP). Running it against owned hostnames
is pointless — external-dns reverts them. `--verify` audits current state;
`--dry-run` previews; default applies (adds only, never deletes).

## Deliberately NOT multi-A

* **Non-proxied (grey-cloud) admin hostnames**: `cortex`, `cv`, `fleet`,
  `monitor`, `skirmbooks`. Without the CF proxy, multi-A gives clients **no
  failover**. Left on sauvage only on purpose.
* **Infra hostnames targeting the *name* `sauvage.e-dani.com`** (CNAME-style):
  `brain`, `harbor`, `openclaw-webhooks`, `openclaw-images`. Out of scope.
* **External / non-edge A-records**: `claude-dgx`, `dgx`, `e-dani`, `server`,
  `webhooks`.

## Rollback

Multi-A is purely additive. To revert a MANUAL hostname to sauvage-only, delete
its 3 KS-5 A-records in Cloudflare. Pre-change DNS snapshots were taken under
`docs/dns-backups/` (gitignored, local to the machine that ran the rollout).

## Known cosmetic issue

`go.skirmshop.es` had a **pre-existing duplicate** sauvage A-record (2×
`57.129.17.172`) — harmless (CF dedups at the edge). Tidy-up: delete one.
