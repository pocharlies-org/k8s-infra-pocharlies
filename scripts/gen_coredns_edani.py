#!/usr/bin/env python3
"""Generate the `e-dani.com:53` block of networking/dns/coredns-custom.yaml.

Every ``Host(`*.e-dani.com`)`` served by an IngressRoute under
``networking/traefik-lan/`` must be pinned in the ``edani-public-lan.server``
block of the coredns-custom ConfigMap.  A name left unpinned falls through to
``forward`` and answers the MagicDNS of the node hosting the CoreDNS replica
that replies, so an in-cluster client flips between the LAN and the public
Cloudflare edge depending on where it runs (INFRA-896: SC-2443/SC-2445,
INFRA-889).  This script is the single source of that block: it reads the
traefik-lan routes, drops the names listed in the exclusions file, writes the
edge pins of ``coredns-edani-edge-pins.yaml`` to the in-cluster traefik-edge
(SKIRM-621: Harbor lives in the DC, so pinning ``harbor.e-dani.com`` to
traefik-lan hairpinned registry pulls OVH -> home -> OVH at ~0.25 MB/s), and
writes the block between the two ConfigMap anchors.  The
``x86-taile0ad27.server`` (ts.net) block is never touched.

Modes (argparse form reused from scripts/update_external_dns_targets.py; its
``yaml.safe_dump_all`` write path is deliberately NOT reused -- it round-trips
away the comments this ConfigMap carries):

  --write        rewrite the block in place from the current routes
  --check        exit 1 if the committed block drifts from the generated one,
                 or a Host is neither pinned nor excluded, or the exclusions
                 file is malformed/stale (the CI guard)
  --list-fixed   print every pinned name (rewrite group + hosts group), one per
                 line -- consumed by the S2 dig loop and the S3 probe
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# The four constants are the only place these values are written.
TRAFIK_SVC = "traefik-lan.traefik-lan.svc.cluster.local"
# ClusterIP in front of the traefik-edge pods (networking/traefik-edge/
# edge-cluster-service.yaml), which serve *.e-dani.com inside the DC with the
# public certificate (wildcard-public-tls).
EDGE_SVC = "traefik-edge-cluster.traefik-edge.svc.cluster.local"
LAN_VIP = "192.168.50.240"
# dgx and s3 go ONLY to the `hosts` block (to the LAN VIP).  A `rewrite` runs
# before `hosts` in CoreDNS, so rewriting them would leave the `hosts` entry
# dead.  They never appear in the rewrite group.
HOSTS_PINNED = frozenset({"dgx.e-dani.com", "s3.e-dani.com"})

TRAFIK_DIR = ROOT / "networking" / "traefik-lan"
COREDNS_FILE = ROOT / "networking" / "dns" / "coredns-custom.yaml"
EXCLUSIONS_FILE = ROOT / "networking" / "dns" / "coredns-edani-exclusions.yaml"
EDGE_PINS_FILE = ROOT / "networking" / "dns" / "coredns-edani-edge-pins.yaml"

# Anchors delimiting the generated region inside the ConfigMap `data`.
START_ANCHOR = "  edani-public-lan.server: |\n"
END_ANCHOR = "  x86-taile0ad27.server: |"

# Non-greedy: a real match line combines several Host() with ClientIP()/
# PathPrefix(), e.g. `(Host(`a.e-dani.com`) || Host(`b.lan.e-dani.com`)) &&
# ClientIP(...)`.  A greedy `\`(.+)\`` would swallow the whole line.
HOST_RE = re.compile(r"Host\(`([^`]+)`\)")
# How a name is fixed in the committed block, for the semantic checks.
COMMITTED_REWRITE_RE = re.compile(r"^\s*rewrite name exact (\S+) \S+\s*$")
COMMITTED_HOSTS_RE = re.compile(r"^\s*\d+\.\d+\.\d+\.\d+ (\S+\.e-dani\.com)\s*$")


def find_edani_hosts(trafik_dir: Path = TRAFIK_DIR) -> set[str]:
    """Every `.e-dani.com` name in a Host() literal across the traefik-lan routes.

    Other domains (admin.skirmshop.es) are ignored; `.lan.e-dani.com` aliases
    end in `.e-dani.com` so they are kept."""
    hosts: set[str] = set()
    for path in sorted(trafik_dir.glob("*.yaml")):
        for match in HOST_RE.finditer(path.read_text(encoding="utf-8")):
            name = match.group(1)
            if name.endswith(".e-dani.com"):
                hosts.add(name)
    return hosts


def load_exclusions(path: Path = EXCLUSIONS_FILE) -> dict[str, str]:
    """name -> reason from the exclusions file.  Missing file == no exclusions."""
    if not path.exists():
        return {}
    docs = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
    exclusions: dict[str, str] = {}
    for doc in docs:
        for entry in (doc or {}).get("exclusions", []) or []:
            name = (entry or {}).get("name")
            reason = (entry or {}).get("reason")
            if not name:
                raise ValueError(f"{path.name}: exclusion entry without `name`")
            exclusions[name] = reason
    return exclusions


def load_edge_pins(path: Path = EDGE_PINS_FILE) -> dict[str, str]:
    """name -> reason from the edge-pins file.  Missing file == no edge pins.

    These names are Host() of traefik-lan routes that must NOT be pinned to
    the LAN: their backends live in the DC and the LAN pin would hairpin the
    traffic through home (SKIRM-621).  They are pinned to ``EDGE_SVC``."""
    if not path.exists():
        return {}
    docs = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]
    pins: dict[str, str] = {}
    for doc in docs:
        for entry in (doc or {}).get("pins", []) or []:
            name = (entry or {}).get("name")
            reason = (entry or {}).get("reason")
            if not name:
                raise ValueError(f"{path.name}: pin entry without `name`")
            pins[name] = reason
    return pins


def split_block(text: str) -> tuple[str, str, str]:
    """(prefix incl. start anchor, generated middle, suffix from end anchor)."""
    start = text.index(START_ANCHOR) + len(START_ANCHOR)
    end = text.index(END_ANCHOR, start)
    return text[:start], text[start:end], text[end:]


def build_middle(
    found: set[str],
    exclusions: dict[str, str],
    edge_pins: dict[str, str] | None = None,
) -> str:
    """The generated `e-dani.com:53` block, indented for the ConfigMap scalar."""
    if edge_pins is None:
        edge_pins = load_edge_pins()
    excluded = set(exclusions)
    edge_names = set(edge_pins) & found
    rewrite_names = sorted(found - excluded - HOSTS_PINNED - edge_names)
    hosts_names = sorted(HOSTS_PINNED & found)

    lines: list[str] = []
    lines.append("    e-dani.com:53 {")
    lines.append("      errors")
    lines.extend(
        [
            "      # GENERATED by scripts/gen_coredns_edani.py -- do not edit by hand.",
            "      # Every Host(`*.e-dani.com`) served by an IngressRoute under",
            "      # networking/traefik-lan/ is pinned here so an in-cluster client",
            "      # reaches traefik-lan over the LAN (or traefik-edge for the",
            "      # edge-pinned names below) instead of falling through to",
            "      # `forward` and answering the node's MagicDNS -- which flips between the",
            "      # LAN and the public Cloudflare edge per node (SC-2443/SC-2445: a >100 MB",
            "      # Harbor layer got 413/502 through the Cloudflare proxy; INFRA-889: the",
            "      # libreplay probe flipped to the edge).  A name that must NOT be pinned",
            "      # goes in networking/dns/coredns-edani-exclusions.yaml with a one-line",
            "      # reason; the CI job coredns-edani-guard fails if a Host is neither",
            "      # pinned nor excluded.  dgx and s3 go to the `hosts` block below (a",
            "      # rewrite runs before `hosts` and would leave the entry dead).",
            "      # Names listed in networking/dns/coredns-edani-edge-pins.yaml are",
            "      # pinned to traefik-edge (in-cluster, DC) instead of the LAN: their",
            "      # backends live in the DC and the LAN pin hairpinned their traffic",
            "      # OVH -> home -> OVH (SKIRM-621: Harbor pulls at 0.25 MB/s).",
        ]
    )
    for name in rewrite_names:
        lines.append(f"      rewrite name exact {name} {TRAFIK_SVC}")
    for name in sorted(edge_names):
        lines.append(f"      rewrite name exact {name} {EDGE_SVC}")
    lines.extend(
        [
            "      kubernetes cluster.local in-addr.arpa ip6.arpa {",
            "        pods insecure",
            "        fallthrough in-addr.arpa ip6.arpa",
            "      }",
            "      hosts {",
            "        # Split-horizon for e-dani.com points at traefik-lan over the LAN",
            f"        # (metallb {LAN_VIP}), which terminates TLS for *.e-dani.com.",
            "        # The old pin to the x86 tailnet IP (100.83.56.98) broke TLS: only",
            "        # tailscaled listens on that :443 (INFRA-588).",
        ]
    )
    for name in hosts_names:
        lines.append(f"        {LAN_VIP} {name}")
    lines.extend(
        [
            "        ttl 60",
            "        fallthrough",
            "      }",
            "      forward . /etc/resolv.conf",
            "      cache 30",
            "    }",
        ]
    )
    return "\n".join(lines) + "\n"


def committed_fixed_names(middle: str) -> tuple[set[str], set[str]]:
    """(rewrite-group names, hosts-group names) present in the committed block."""
    rewrites: set[str] = set()
    hosts: set[str] = set()
    for line in middle.splitlines():
        m = COMMITTED_REWRITE_RE.match(line)
        if m:
            rewrites.add(m.group(1))
            continue
        m = COMMITTED_HOSTS_RE.match(line)
        if m:
            hosts.add(m.group(1))
    return rewrites, hosts


def check(
    found: set[str],
    exclusions: dict[str, str],
    current_text: str,
    edge_pins: dict[str, str] | None = None,
) -> list[str]:
    """Return the list of guard failures (empty == the block is correct)."""
    if edge_pins is None:
        edge_pins = load_edge_pins()
    errors: list[str] = []
    excluded = set(exclusions)

    # Exclusion file integrity (independent of the block content).
    for name, reason in exclusions.items():
        if not (isinstance(reason, str) and reason.strip()):
            errors.append(f"exclusión {name} sin `reason` (obligatorio, una línea)")
    stale = sorted(excluded - found)
    if stale:
        errors.append(
            "exclusión rancia (ya no es Host() de traefik-lan): " + ", ".join(stale)
        )

    # Edge-pins file integrity, same rules as the exclusions.
    for name, reason in edge_pins.items():
        if not (isinstance(reason, str) and reason.strip()):
            errors.append(f"pin edge {name} sin `reason` (obligatorio, una línea)")
    stale_edge = sorted(set(edge_pins) - found)
    if stale_edge:
        errors.append(
            "pin edge rancio (ya no es Host() de traefik-lan): " + ", ".join(stale_edge)
        )
    both = sorted(set(edge_pins) & excluded)
    if both:
        errors.append(
            "nombre excluido y fijado a edge a la vez (elige uno): " + ", ".join(both)
        )

    expected_rewrite = found - excluded - HOSTS_PINNED
    expected_hosts = HOSTS_PINNED & found
    _, _, _ = split_block(current_text)  # validate anchors before parsing middle
    prefix, middle, suffix = split_block(current_text)

    committed_rewrites, committed_hosts = committed_fixed_names(middle)

    # A found name that is neither excluded nor pinned in the committed block.
    missing = sorted(expected_rewrite - committed_rewrites)
    for name in missing:
        errors.append(
            f"host sin fijar ni excluir: {name} (añádelo a las exclusiones con "
            f"reason o ejecuta gen_coredns_edani.py --write)"
        )
    missing_hosts = sorted(expected_hosts - committed_hosts)
    for name in missing_hosts:
        errors.append(f"host fijado por hosts ausente en el bloque: {name}")

    # A rewrite/hosts entry in the committed block that should no longer be there.
    stale_rewrite = sorted(committed_rewrites - expected_rewrite)
    for name in stale_rewrite:
        errors.append(f"rewrite sobrante (no es Host() fijable de traefik-lan): {name}")
    stale_hosts = sorted(committed_hosts - expected_hosts)
    for name in stale_hosts:
        errors.append(f"entrada hosts sobrante (no es Host() fijable de traefik-lan): {name}")

    # Byte drift of the whole generated region.
    if middle != build_middle(found, exclusions, edge_pins):
        errors.append(
            "drift: el bloque commiteado no coincide con el generado "
            "(ejecuta gen_coredns_edani.py --write)"
        )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite the block in place")
    parser.add_argument("--check", action="store_true", help="guard: exit 1 on any drift")
    parser.add_argument(
        "--list-fixed", action="store_true", help="print every pinned name, one per line"
    )
    args = parser.parse_args(argv)

    found = find_edani_hosts()
    exclusions = load_exclusions()

    if args.list_fixed:
        fixed = (found - set(exclusions) - HOSTS_PINNED) | (HOSTS_PINNED & found)
        for name in sorted(fixed):
            print(name)
        return 0

    text = COREDNS_FILE.read_text(encoding="utf-8")

    if args.write:
        prefix, _middle, suffix = split_block(text)
        COREDNS_FILE.write_text(prefix + build_middle(found, exclusions) + suffix, encoding="utf-8")
        print(f"escrito {COREDNS_FILE.relative_to(ROOT)} ({len(found)} Host() e-dani.com)")
        return 0

    if args.check:
        errors = check(found, exclusions, text)
        if errors:
            for err in errors:
                print(f"FAIL: {err}", file=sys.stderr)
            return 1
        print(f"ok: bloque e-dani.com generado al día ({len(found)} Host())")
        return 0

    parser.error("need one of --write, --check, --list-fixed")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
