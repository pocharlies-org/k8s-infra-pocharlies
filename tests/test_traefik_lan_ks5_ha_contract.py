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

    def test_traefik_lan_is_ha_on_the_ks5_pool(self) -> None:
        self.assertGreaterEqual(self.values["deployment"]["replicas"], 2)
        self.assertEqual(
            self.values["nodeSelector"],
            {"kubernetes.io/arch": "amd64", "node-pool": "ks5-nvme"},
        )
        self.assertNotIn("topology: lan", self.values_text)
        self.assertEqual(
            self.values["podDisruptionBudget"],
            {"enabled": True, "minAvailable": 1},
        )
        terms = self.values["affinity"]["podAntiAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]
        self.assertEqual(len(terms), 1)
        self.assertEqual(terms[0]["topologyKey"], "kubernetes.io/hostname")
        self.assertEqual(
            terms[0]["labelSelector"]["matchLabels"],
            {
                "app.kubernetes.io/instance": "traefik-lan-traefik-lan",
                "app.kubernetes.io/name": "traefik",
            },
        )

    def test_harbor_lan_resolves_to_the_cluster_service(self) -> None:
        rewrite = self.coredns["data"]["harbor-lan.override"].strip()
        self.assertEqual(
            rewrite,
            "rewrite name exact harbor.lan.e-dani.com "
            "traefik-lan.traefik-lan.svc.cluster.local",
        )
        self.assertNotIn("192.168.50.240", rewrite)


if __name__ == "__main__":
    unittest.main()
