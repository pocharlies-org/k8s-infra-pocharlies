from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class PrivateServiceExposureContractTest(unittest.TestCase):
    def test_rabbitmq_preserves_the_tailnet_endpoint_without_a_nodeport(self) -> None:
        manifest = yaml.safe_load(
            (
                ROOT
                / "databases/postgres-shared/shared-rabbitmq-ext.yaml"
            ).read_text(encoding="utf-8")
        )
        kustomization = yaml.safe_load(
            (
                ROOT / "databases/postgres-shared/kustomization.yaml"
            ).read_text(encoding="utf-8")
        )

        self.assertIn(
            "shared-rabbitmq-ext.yaml",
            kustomization["resources"],
        )
        self.assertEqual(manifest["spec"]["type"], "ClusterIP")
        self.assertEqual(manifest["spec"]["externalIPs"], ["100.109.183.9"])
        self.assertEqual(
            manifest["spec"]["ports"],
            [
                {
                    "name": "amqp",
                    "port": 30672,
                    "targetPort": 5672,
                    "protocol": "TCP",
                }
            ],
        )

    def test_traefik_load_balancer_does_not_publish_nodeports_or_metrics(self) -> None:
        values = yaml.safe_load(
            (ROOT / "networking/traefik-lan/values.yaml").read_text(
                encoding="utf-8"
            )
        )

        self.assertIs(
            values["service"]["spec"].get("allocateLoadBalancerNodePorts"),
            False,
        )
        self.assertEqual(
            values["service"]["spec"]["externalTrafficPolicy"],
            "Local",
        )
        self.assertIs(values["ports"]["metrics"]["expose"]["default"], False)
        self.assertIs(
            values["metrics"]["prometheus"].get("service", {}).get("enabled"),
            True,
        )


if __name__ == "__main__":
    unittest.main()
