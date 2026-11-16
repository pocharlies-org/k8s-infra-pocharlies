"""Contract tests for the generated e-dani.com CoreDNS block (INFRA-902 S1).

Two independent readers of the same source (traefik-lan Host() literals): the
generator's raw-text regex and a PyYAML parse of spec.routes[].match.  They must
agree -- a fixture of ~58 names would be the next divergence (the architect's
spec replaces it with this cross-check)."""

from pathlib import Path
import re
import unittest

import yaml

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import gen_coredns_edani as gen  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TRAFIK_DIR = ROOT / "networking" / "traefik-lan"
COREDNS_FILE = ROOT / "networking" / "dns" / "coredns-custom.yaml"

# The ts.net block, byte for byte as it stands today.  The generator must never
# change a byte of it (C1d).
TS_NET_GOLDEN = """  x86-taile0ad27.server: |
    # This must be a dedicated zone: a hosts entry in e-dani.com does not
    # answer queries for x86.taile0ad27.ts.net.  Traefik ExternalName
    # backends use this pin rather than node-local MagicDNS.
    taile0ad27.ts.net:53 {
      errors
      hosts {
        100.83.56.98 x86.taile0ad27.ts.net
        100.125.62.10 mac-cb.taile0ad27.ts.net
        100.82.219.103 mac-casa.taile0ad27.ts.net
        ttl 60
        fallthrough
      }
      forward . /etc/resolv.conf
      cache 30
    }
"""


def pyyaml_edani_hosts() -> set[str]:
    """Independent reader: parse the manifests and pull Host() from match rules."""
    host_in_match = re.compile(r"Host\(`([^`]+)`\)")
    hosts: set[str] = set()
    for path in sorted(TRAFIK_DIR.glob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if not isinstance(doc, dict) or doc.get("kind") != "IngressRoute":
                continue
            for route in (doc.get("spec") or {}).get("routes", []) or []:
                match = route.get("match")
                if not isinstance(match, str):
                    continue
                for m in host_in_match.finditer(match):
                    if m.group(1).endswith(".e-dani.com"):
                        hosts.add(m.group(1))
    return hosts


class CorednsEdaniContractTest(unittest.TestCase):
    def test_two_independent_parsers_agree(self) -> None:
        """Raw-text regex == PyYAML parse of spec.routes[].match (no fixture)."""
        self.assertEqual(gen.find_edani_hosts(), pyyaml_edani_hosts())

    def test_ts_net_block_is_untouched_byte_for_byte(self) -> None:
        """The generated suffix keeps the ts.net block identical (C1d)."""
        text = COREDNS_FILE.read_text(encoding="utf-8")
        _prefix, _middle, suffix = gen.split_block(text)
        self.assertEqual(suffix, TS_NET_GOLDEN)

    def test_reassembly_preserves_ts_net(self) -> None:
        """--write output still carries the ts.net block byte for byte."""
        text = COREDNS_FILE.read_text(encoding="utf-8")
        prefix, _middle, suffix = gen.split_block(text)
        rebuilt = prefix + gen.build_middle(gen.find_edani_hosts(), {}) + suffix
        self.assertTrue(rebuilt.endswith(TS_NET_GOLDEN))

    def test_pinned_names_only_in_hosts_never_rewrite(self) -> None:
        """dgx/s3 go to `hosts` only; a rewrite would shadow them (dead entry)."""
        middle = gen.build_middle(gen.find_edani_hosts(), {})
        for name in gen.HOSTS_PINNED:
            self.assertNotIn(f"rewrite name exact {name} ", middle)
            self.assertIn(f"{gen.LAN_VIP} {name}", middle)

    def test_exclusion_without_reason_is_rejected(self) -> None:
        """A name excluded with no reason fails the guard (C1b flow)."""
        found = gen.find_edani_hosts()
        victim = sorted(found)[0]
        errors = gen.check(found, {victim: None}, COREDNS_FILE.read_text(encoding="utf-8"))
        self.assertTrue(any("sin `reason`" in e for e in errors), errors)

    def test_unfixed_host_names_itself(self) -> None:
        """A found Host neither pinned nor excluded is named by the guard (C1b)."""
        found = gen.find_edani_hosts()
        # Pretend a brand-new route added a name the committed block does not fix.
        errors = gen.check(found | {"prueba-guard.e-dani.com"}, {}, COREDNS_FILE.read_text(encoding="utf-8"))
        self.assertTrue(
            any("prueba-guard.e-dani.com" in e for e in errors),
            errors,
        )

    def test_multi_host_and_clientip_line_parsed(self) -> None:
        """Regression: several Host() on one line with ClientIP() backticks."""
        line = (
            "      match: (Host(`a.e-dani.com`) || Host(`a.lan.e-dani.com`)) && "
            "(ClientIP(`192.168.50.0/24`) || ClientIP(`10.42.0.0/16`))\n"
        )
        names = {m.group(1) for m in gen.HOST_RE.finditer(line) if m.group(1).endswith(".e-dani.com")}
        self.assertEqual(names, {"a.e-dani.com", "a.lan.e-dani.com"})

    def test_committed_block_is_up_to_date(self) -> None:
        """C1a: the committed block matches the generated one (guard green)."""
        errors = gen.check(gen.find_edani_hosts(), gen.load_exclusions(), COREDNS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(errors, [])

    def test_generated_block_has_no_manual_add_hint(self) -> None:
        """C4a: the ConfigMap no longer tells a human to add names by hand."""
        self.assertNotIn("Add the name here", COREDNS_FILE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
