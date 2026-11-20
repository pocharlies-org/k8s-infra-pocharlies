"""INFRA-1412 (INFRA-902 S3): contrato de la sonda de divergencia de e-dani.com.

La sonda (networking/dns/edani-dns-divergence-watch.yaml) muestrea los nombres que
scripts/gen_coredns_edani.py --list-fixed fija contra todos los endpoints de kube-dns
y empuja edani_dns_public_answer a vmsingle (VMRule EdaniDnsPublicAnswer). Su lista
(names.txt en el ConfigMap) es la única copia que lee el job: estos tests la atan al
generador (una lista a mano sería la misma clase de fallo que combate la épica) y
fijan los invariantes del manifiesto (RBAC mínimo, VMRule, métrica, sonda).
"""
import pathlib
import re
import socket
import struct
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import gen_coredns_edani as gen  # noqa: E402

MANIFEST = ROOT / "networking" / "dns" / "edani-dns-divergence-watch.yaml"
DOCS = [d for d in yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")) if d]


def doc(kind):
    got = [d for d in DOCS if d["kind"] == kind]
    assert len(got) == 1, f"se esperaba exactamente 1 {kind}, hay {len(got)}"
    return got[0]


def probe_namespace():
    """Ejecuta el probe embebido como módulo (main no corre: __name__ != '__main__')."""
    ns = {"__name__": "probe_under_test"}
    exec(doc("ConfigMap")["data"]["probe.py"], ns)
    return ns


class TestNamesSingleSource(unittest.TestCase):
    def test_names_txt_equals_list_fixed(self):
        """names.txt == el conjunto fijo del generador (rewrite + hosts), ni uno más."""
        committed = {
            ln.strip()
            for ln in doc("ConfigMap")["data"]["names.txt"].splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        }
        found = gen.find_edani_hosts()
        expected = (found - set(gen.load_exclusions()) - gen.HOSTS_PINNED) | (
            gen.HOSTS_PINNED & found
        )
        self.assertEqual(committed, expected)


class TestProbeClassifier(unittest.TestCase):
    def setUp(self):
        self.probe = probe_namespace()

    def test_lan_vip_constant_matches_generator(self):
        self.assertEqual(self.probe["LAN_VIP"], gen.LAN_VIP)

    def test_private_answers_are_not_divergence(self):
        self.assertFalse(self.probe["answer_is_public"]([gen.LAN_VIP]))
        self.assertFalse(self.probe["answer_is_public"](["10.43.1.2"]))
        self.assertFalse(self.probe["answer_is_public"](["10.43.0.10", gen.LAN_VIP]))

    def test_public_answer_is_divergence(self):
        self.assertTrue(self.probe["answer_is_public"](["104.16.1.1"]))
        # Una pública aunque sea entre privadas también es divergencia.
        self.assertTrue(self.probe["answer_is_public"]([gen.LAN_VIP, "104.16.1.1"]))


class TestDnsParser(unittest.TestCase):
    """Regresión del parser stdlib (el único camino de resolución: alpine/k8s no trae dig)."""

    def setUp(self):
        self.probe = probe_namespace()

    @staticmethod
    def _response(tid, answers, rcode=0):
        qname = b"\x07example\x03com\x00"
        header = struct.pack(">HHHHHH", tid, 0x8000 | rcode, 1, len(answers), 0, 0)
        question = qname + struct.pack(">HH", 1, 1)
        body = b""
        for ip in answers:
            body += b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4) + socket.inet_aton(ip)
        return header + question + body

    def test_parses_compressed_answer_name(self):
        rcode, ips = self.probe["parse_response"](self._response(42, ["192.168.50.240"]), 42)
        self.assertEqual((rcode, ips), (0, ["192.168.50.240"]))

    def test_multiple_a_records(self):
        _rcode, ips = self.probe["parse_response"](self._response(7, ["10.43.1.1", "1.2.3.4"]), 7)
        self.assertEqual(ips, ["10.43.1.1", "1.2.3.4"])

    def test_nxdomain_yields_no_answers(self):
        rcode, ips = self.probe["parse_response"](self._response(9, [], rcode=3), 9)
        self.assertEqual((rcode, ips), (3, []))

    def test_wrong_id_raises(self):
        with self.assertRaises(ValueError):
            self.probe["parse_response"](self._response(1, ["1.1.1.1"]), 2)

    def test_short_response_raises(self):
        with self.assertRaises(ValueError):
            self.probe["parse_response"](b"\x00\x01", 1)


class TestManifestInvariants(unittest.TestCase):
    def test_rbac_is_minimal(self):
        role = doc("Role")
        self.assertEqual(role["metadata"]["namespace"], "kube-system")
        self.assertEqual(
            role["rules"],
            [{"apiGroups": [""], "resources": ["endpoints"], "verbs": ["get"]}],
        )
        rb = doc("RoleBinding")
        self.assertEqual(rb["metadata"]["namespace"], "kube-system")
        self.assertEqual(
            rb["subjects"],
            [{"kind": "ServiceAccount", "name": "edani-dns-divergence-watch", "namespace": "monitoring"}],
        )

    def test_vmrule_alerts_on_the_gauge(self):
        vmrule = doc("VMRule")
        self.assertEqual(vmrule["metadata"]["namespace"], "monitoring")
        rules = vmrule["spec"]["groups"][0]["rules"]
        self.assertEqual([r["alert"] for r in rules], ["EdaniDnsPublicAnswer"])
        self.assertIn("edani_dns_public_answer", rules[0]["expr"])

    def test_probe_pushes_the_gauge_the_rule_reads(self):
        """La métrica que empuja la sonda es exactamente la que evalúa la VMRule."""
        expr = doc("VMRule")["spec"]["groups"][0]["rules"][0]["expr"].strip()
        metric = re.match(r"(\w+)", expr).group(1)
        self.assertIn(metric + " ", doc("ConfigMap")["data"]["probe.py"])

    def test_cronjob_shape(self):
        cronjob = doc("CronJob")
        self.assertEqual(cronjob["metadata"]["namespace"], "monitoring")
        self.assertEqual(cronjob["spec"]["schedule"], "*/5 * * * *")
        pod = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]
        self.assertEqual(pod["serviceAccountName"], "edani-dns-divergence-watch")
        container = pod["containers"][0]
        self.assertEqual(container["image"], "alpine/k8s:1.32.5")
        env = {e["name"]: e["value"] for e in container["env"]}
        self.assertEqual(
            env["VM_PUSH_URL"],
            "http://vmsingle-vm-victoria-metrics-k8s-stack.monitoring.svc:8428",
        )
        self.assertEqual(env["EXTRA_TEST_NAME"], "")


if __name__ == "__main__":
    unittest.main()
