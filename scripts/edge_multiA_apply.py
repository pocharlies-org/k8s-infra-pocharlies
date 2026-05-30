#!/usr/bin/env python3
"""Idempotent edge multi-A HA for the public Traefik edge.

After the KS-5-A HA rollout the edge DaemonSet runs on 4 nodes
(sauvage + ks5-cp-1/2/3). This script publishes, for each customer-facing /
app hostname, a Cloudflare **multi-A** record set pointing at all 4 edge
public IPs (CF-proxied), so a single edge node failing only degrades a
fraction of requests (CF retries another origin on connection failure)
instead of the whole edge going down with sauvage.

WHY DIRECT CLOUDFLARE API (not external-dns annotations):
  external-dns runs with `--policy=upsert-only`. Empirically it will NOT
  rewrite the target SET of an *existing* A-record when its source
  annotation changes (it reports "all records are already up to date").
  So bumping `external-dns.alpha.kubernetes.io/target` to 4 IPs is a no-op
  for records that already exist. BUT upsert-only ALSO never deletes — so
  A-records we add directly via the CF API are safe: external-dns leaves
  them untouched. This script therefore manages the multi-A set directly
  and is the reproducible source of truth for it.

SAFETY:
  * Idempotent: only ADDS missing KS-5 IPs; never deletes; no duplicates.
  * Only touches hostnames whose current record set INCLUDES sauvage
    (the SPOF we are fixing); skips anything that already moved.
  * Matches the existing record's `proxied` flag.
  * `--dry-run` to preview, `--verify` to audit without writing.

DELIBERATELY EXCLUDED (see docs/EDGE_MULTIA_HA.md):
  * Non-proxied (grey-cloud) admin hostnames: cortex, cv, fleet, monitor,
    skirmbooks. Multi-A without the CF proxy gives clients NO failover, so
    a down node = hard failures for whoever's resolver picked it. Left on
    sauvage only on purpose.
  * Infra hostnames that target the *name* sauvage.e-dani.com (CNAME-style):
    brain, harbor, openclaw-webhooks/images. Out of scope for storefront HA.
  * External / non-edge A-records (claude-dgx, dgx, e-dani, server, webhooks).

Requires env: CLOUDFLARE_API_TOKEN  (zone IDs are resolved by name).
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import urllib.request

# Public edge IPs after the KS-5 HA rollout.
SAUVAGE = "57.129.17.172"
KS5 = ["141.94.73.52", "141.94.73.50", "145.239.194.168"]  # ks5-cp-1/2/3
EDGE_IPS = [SAUVAGE, *KS5]

# Proxied, customer-facing / app hostnames to keep HA, per zone.
ZONES = {
    "e-dani.com": [
        "skirmshop",       # Shopify storefront proxy + all path-routed apps
        "bundles", "sii", "firecrawl", "cv-manu",
        "litellm", "whatsapp",
        "alexa", "jarvis-alexa", "home-assistant", "tm",
        "n8n", "n8n-stg",
    ],
    "skirmshop.es": [
        "track", "affiliate", "go",
    ],
}

API = "https://api.cloudflare.com/client/v4"


def _req(method: str, path: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body else None,
        method=method,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    return json.load(urllib.request.urlopen(req, timeout=20))


def zone_id(name: str, token: str) -> str:
    d = _req("GET", f"/zones?name={name}", token)
    if not d.get("success") or not d["result"]:
        raise SystemExit(f"zone {name} not accessible with this token")
    return d["result"][0]["id"]


def records(zid: str, fqdn: str, token: str) -> list[dict]:
    return _req("GET", f"/zones/{zid}/dns_records?type=A&name={fqdn}&per_page=100", token)["result"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="preview adds, do not write")
    ap.add_argument("--verify", action="store_true", help="audit current state only")
    args = ap.parse_args()

    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        raise SystemExit("set CLOUDFLARE_API_TOKEN")

    total_ok = total = 0
    for zone, hosts in ZONES.items():
        zid = zone_id(zone, token)
        for host in hosts:
            fqdn = f"{host}.{zone}"
            total += 1
            recs = records(zid, fqdn, token)
            counts = collections.Counter(r["content"] for r in recs)
            proxied = all(r["proxied"] for r in recs) if recs else True

            if SAUVAGE not in counts:
                print(f"  SKIP   {fqdn:30s} (does not point at sauvage: {sorted(counts)})")
                continue

            missing = [ip for ip in KS5 if ip not in counts]
            if args.verify:
                ok = all(ip in counts for ip in EDGE_IPS)
                total_ok += ok
                dup = [k for k, v in counts.items() if v > 1]
                print(f"  {'OK ' if ok else 'GAP'}    {fqdn:30s} A={len(recs)} all4={ok}"
                      + (f" dups={dup}" if dup else ""))
                continue

            for ip in missing:
                if args.dry_run:
                    print(f"  WOULD-ADD {fqdn} -> {ip} (proxied={proxied})")
                else:
                    _req("POST", f"/zones/{zid}/dns_records", token,
                         {"type": "A", "name": fqdn, "content": ip, "proxied": proxied, "ttl": 1})
            recs2 = records(zid, fqdn, token)
            c2 = collections.Counter(r["content"] for r in recs2)
            ok = all(ip in c2 for ip in EDGE_IPS)
            total_ok += ok
            print(f"  {'DONE' if ok else 'CHECK'}  {fqdn:30s} added={len(missing)} total={len(recs2)} all4={ok}")

    print(f"\n{total_ok}/{total} hostnames with all 4 edge IPs"
          + (" (dry-run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
