# Cloudflare LAN record budget

## Permanent ownership boundary

Cloudflare contains one intentional wildcard record:

```text
*.lan.e-dani.com  A  192.168.50.240
```

That record sends every normal LAN hostname to the Traefik LAN VIP. The
separate `k8s.lan.e-dani.com` record is also intentional and has a different
target. Neither record is owned by `external-dns`.

`external-dns` must therefore exclude the whole `lan.e-dani.com` suffix. If it
does not, every discovered LAN route consumes both an A record and a TXT
ownership record while returning the same address as the wildcard. This can
exhaust the Cloudflare zone record quota and prevent cert-manager from creating
temporary `_acme-challenge` TXT records.

Keep all of the following together:

- `domainFilters` still includes `e-dani.com` for public records;
- `excludeDomains` contains exactly `lan.e-dani.com`;
- policy remains `upsert-only` so an accidental source change cannot prune
  unrelated public DNS;
- the wildcard remains DNS-only and points to `192.168.50.240`;
- `k8s.lan.e-dani.com` remains outside external-dns ownership.

## Controlled stale-record cleanup

Deploy the exclusion before deleting anything. Then query Cloudflare and select
only pairs that meet every condition below:

1. the A name ends in `.lan.e-dani.com`;
2. its target is exactly `192.168.50.240`;
3. the wildcard resolves the same name to the same target;
4. the paired TXT value declares
   `external-dns/owner=k3s-x86-home`;
5. neither record is the wildcard nor `k8s.lan.e-dani.com`.

Back up the full JSON for every selected record before deletion. Re-read every
record by its exact Cloudflare ID immediately before deleting it; abort on any
name, type, target, owner, or modification mismatch.

After cleanup, require all of these postconditions:

- the zone has enough free entries for concurrent ACME challenges;
- representative LAN names still resolve to `192.168.50.240` through the
  wildcard;
- `k8s.lan.e-dani.com` still returns its intentional distinct target;
- cert-manager Challenges become `presented=true` and the affected
  Certificates leave `Issuing` while remaining `Ready`;
- Argo CD returns `k8s-infra` to `Synced/Healthy`;
- an external-dns reconciliation does not recreate the deleted LAN pairs.

Rollback is the reverse: restore the backed-up records with their original
type, name, content, TTL, and proxy flag, remove `excludeDomains`, and reconcile
external-dns. Do not use a wildcard TXT record as a replacement for ownership
records.

## Public canonical-host wildcard

Cloudflare's `e-dani.com` zone reached its record quota when the canonical
split-DNS migration tried to publish four Edge A records plus one TXT owner
record for every former LAN-only hostname. The permanent budget-safe public
fallback is:

```text
*.e-dani.com  CNAME  images.openclaw.e-dani.com  DNS-only
```

`images.openclaw.e-dani.com` is an existing DNS-only record with all four Edge
addresses. A CNAME preserves the requested hostname, so Traefik still selects
the exact canonical router. Existing exact DNS records take precedence over
the wildcard and retain their own proxy/DNS-only behavior.

This wildcard is manually owned in Cloudflare. Canonical aggregate
IngressRoutes carry `external-dns.alpha.kubernetes.io/exclude: "true"`, and
ExternalDNS must keep the matching annotation filter enabled. Do not add a TXT
ownership record or per-host targets for those aggregate routes: doing so
recreates the quota failure and can block ACME challenges.

Before replacing or deleting the wildcard, back up its full Cloudflare JSON,
verify that the target still returns the four Edge addresses, and verify all
47 legacy-to-canonical mappings still have both a LAN and an Edge router.
