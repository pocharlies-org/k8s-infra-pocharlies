from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class TraefikLanKs5HaContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.values_text = (ROOT / "networking/traefik-lan/values.yaml").read_text(
            encoding="utf-8"
        )
        self.values = yaml.safe_load(self.values_text)
        documents = list(
            yaml.safe_load_all(
                (ROOT / "networking/dns/coredns-custom.yaml").read_text(
                    encoding="utf-8"
                )
            )
        )
        self.coredns = documents[0]
        metallb_documents = list(
            yaml.safe_load_all(
                (ROOT / "networking/metallb/ippool.yaml").read_text(
                    encoding="utf-8"
                )
            )
        )
        self.l2_advertisement = next(
            document
            for document in metallb_documents
            if document["kind"] == "L2Advertisement"
        )

    def test_traefik_lan_runs_only_on_x86_infrastructure(self) -> None:
        self.assertEqual(self.values["deployment"]["replicas"], 1)
        self.assertEqual(
            self.values["nodeSelector"],
            {"kubernetes.io/hostname": "ubuntu"},
        )
        self.assertEqual(
            self.values["podDisruptionBudget"],
            {"enabled": False},
        )
        self.assertEqual(
            self.values["service"]["spec"]["externalTrafficPolicy"], "Local"
        )
        self.assertEqual(
            self.values["tolerations"],
            [
                {
                    "key": "pool",
                    "operator": "Equal",
                    "value": "dev",
                    "effect": "PreferNoSchedule",
                }
            ],
        )
        self.assertEqual(
            self.values["affinity"],
            {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {
                                        "key": "kubernetes.io/hostname",
                                        "operator": "In",
                                        "values": ["ubuntu"],
                                    }
                                ]
                            }
                        ]
                    }
                }
            },
        )
        self.assertEqual(self.values["topologySpreadConstraints"], [])

    def test_lan_vips_are_announced_only_from_physical_lan_nodes(self) -> None:
        self.assertEqual(
            self.l2_advertisement["spec"]["nodeSelectors"],
            [{"matchLabels": {"kubernetes.io/hostname": "ubuntu"}}],
        )

    def test_harbor_lan_resolves_to_the_cluster_service(self) -> None:
        self.assertNotIn("harbor-lan.override", self.coredns["data"])
        server = self.coredns["data"]["edani-public-lan.server"]
        self.assertIn(
            "rewrite name exact harbor.lan.e-dani.com "
            "traefik-lan.traefik-lan.svc.cluster.local",
            server,
        )
        self.assertIn("kubernetes cluster.local in-addr.arpa ip6.arpa", server)
        self.assertNotIn("192.168.50.240", server)


if __name__ == "__main__":
    unittest.main()
