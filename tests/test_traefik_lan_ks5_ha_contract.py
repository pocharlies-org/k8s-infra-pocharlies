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

    def test_traefik_lan_is_ha_across_ovh_and_non_ubuntu_lan(self) -> None:
        self.assertGreaterEqual(self.values["deployment"]["replicas"], 4)
        self.assertNotIn("nodeSelector", self.values)
        self.assertEqual(
            self.values["podDisruptionBudget"],
            {"enabled": True, "minAvailable": 3},
        )
        node_terms = self.values["affinity"]["nodeAffinity"][
            "requiredDuringSchedulingIgnoredDuringExecution"
        ]["nodeSelectorTerms"]
        self.assertEqual(
            node_terms,
            [
                {
                    "matchExpressions": [
                        {
                            "key": "node-pool",
                            "operator": "In",
                            "values": ["ks5-nvme"],
                        }
                    ]
                },
                {
                    "matchExpressions": [
                        {
                            "key": "topology",
                            "operator": "In",
                            "values": ["lan"],
                        },
                        {
                            "key": "kubernetes.io/hostname",
                            "operator": "NotIn",
                            "values": ["ubuntu"],
                        },
                    ]
                },
            ],
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
        self.assertEqual(
            self.values["service"]["spec"]["externalTrafficPolicy"], "Local"
        )
        self.assertEqual(
            self.values["tolerations"],
            [
                {
                    "key": "dedicated",
                    "operator": "Equal",
                    "value": "llm",
                    "effect": "NoSchedule",
                }
            ],
        )
        self.assertEqual(
            self.values["topologySpreadConstraints"],
            [
                {
                    "maxSkew": 1,
                    "topologyKey": "topology",
                    "whenUnsatisfiable": "DoNotSchedule",
                    "nodeAffinityPolicy": "Honor",
                    "nodeTaintsPolicy": "Honor",
                    "labelSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/instance": "traefik-lan-traefik-lan",
                            "app.kubernetes.io/name": "traefik",
                        }
                    },
                }
            ],
        )

    def test_lan_vips_are_announced_only_from_physical_lan_nodes(self) -> None:
        self.assertEqual(
            self.l2_advertisement["spec"]["nodeSelectors"],
            [
                {
                    "matchExpressions": [
                        {
                            "key": "topology",
                            "operator": "In",
                            "values": ["lan"],
                        },
                        {
                            "key": "kubernetes.io/hostname",
                            "operator": "NotIn",
                            "values": ["ubuntu"],
                        },
                    ]
                }
            ],
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
