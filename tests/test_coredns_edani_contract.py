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

    def test_committed_block_independent_reader_pins_to_known_targets(self) -> None:
        """Regresion INFRA-902 (C1/C2 estatico) + SKIRM-621: un lector
        independiente del bloque commiteado -- no el regex del generador --
        coincide con las fijaciones que declara el generador (--list-fixed) y
        todo destino es conocido: el Service traefik-lan o el traefik-edge del
        cluster en las lineas `rewrite`, la VIP en las de `hosts`. Varios
        nombres a edge solo pueden ser los declarados en el fichero de edge
        pins. Es la comprobacion que qa midio a mano con grep (hoy 56 rewrite
        + 2 hosts == 58)."""
        text = COREDNS_FILE.read_text(encoding="utf-8")
        start = text.index("  edani-public-lan.server: |")
        end = text.index("  x86-taile0ad27.server: |", start)
        region = text[start:end]
        rewrite_re = re.compile(r"^\s*rewrite name exact (\S+) (\S+)\s*$")
        hosts_re = re.compile(r"^\s*(\d{1,3}(?:\.\d{1,3}){3}) (\S+\.e-dani\.com)\s*$")
        rewrites: dict[str, str] = {}
        hosts: dict[str, str] = {}
        for line in region.splitlines():
            m = rewrite_re.match(line)
            if m:
                rewrites[m.group(1)] = m.group(2)
                continue
            m = hosts_re.match(line)
            if m:
                hosts[m.group(2)] = m.group(1)
        found = gen.find_edani_hosts()
        expected = (found - set(gen.load_exclusions()) - gen.HOSTS_PINNED) | (gen.HOSTS_PINNED & found)
        self.assertEqual(set(rewrites) | set(hosts), expected)
        self.assertEqual(len(rewrites) + len(hosts), len(expected))
        # Ningun destino puede ser una IP publica ni otro Service: la fijacion es
        # exactamente lo que impide la divergencia INFRA-896.
        self.assertEqual(
            set(rewrites.values()),
            {"traefik-lan.traefik-lan.svc.cluster.local", gen.EDGE_SVC},
        )
        self.assertEqual(set(hosts.values()), {"192.168.50.240"})
        # A edge solo lo declarado en networking/dns/coredns-edani-edge-pins.yaml.
        edge_pinned = {n for n, target in rewrites.items() if target == gen.EDGE_SVC}
        self.assertEqual(edge_pinned, set(gen.load_edge_pins()) & found)
        self.assertIn("harbor.e-dani.com", edge_pinned)
        self.assertNotIn("harbor.lan.e-dani.com", edge_pinned)

    def test_edge_pin_integrity_errors(self) -> None:
        """Regresion SKIRM-621: el guard nombra pin edge sin reason, rancio
        (ya no es Host() de traefik-lan) y en conflicto con una exclusion."""
        found = gen.find_edani_hosts()
        text = COREDNS_FILE.read_text(encoding="utf-8")
        exclusions = gen.load_exclusions()
        victim = "harbor.e-dani.com"
        errors = gen.check(found, exclusions, text, {victim: None})
        self.assertTrue(
            any("pin edge" in e and victim in e and "sin `reason`" in e for e in errors),
            errors,
        )
        errors = gen.check(found, exclusions, text, {"borrado.e-dani.com": "motivo"})
        self.assertTrue(any("pin edge rancio" in e for e in errors), errors)
        errors = gen.check(found, {victim: "motivo"}, text, {victim: "motivo"})
        self.assertTrue(
            any("excluido y fijado a edge" in e and victim in e for e in errors), errors
        )
        # Sin los pins edge del fichero real, el bloque commiteado deriva.
        errors = gen.check(found, exclusions, text, {})
        self.assertTrue(any("drift" in e for e in errors), errors)

    def test_architecture_md_documents_generated_block(self) -> None:
        """Regresion INFRA-902 (C4b): ARCHITECTURE.md sigue nombrando el generador,
        la lista de exclusiones con `reason`, el job de CI y el bloque ts.net que
        no se toca. qa lo midio con `git grep -l gen_coredns_edani ARCHITECTURE.md`."""
        doc = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        for needle in (
            "gen_coredns_edani.py",
            "coredns-edani-exclusions.yaml",
            "coredns-edani-guard",
            "x86-taile0ad27.server",
        ):
            self.assertIn(needle, doc)


if __name__ == "__main__":
    unittest.main()
