import json
import re
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALUES = (ROOT / "platform/velero/values.yaml").read_text()
NODE_AGENT_CONFIG = (ROOT / "platform/velero/node-agent-config.yaml").read_text()
KUSTOMIZATION = (ROOT / "kustomization.yaml").read_text()
SCHEDULES = (ROOT / "platform/velero/schedules.yaml").read_text()


class VeleroOperabilityContractTest(unittest.TestCase):
    def test_aws_plugin_matches_velero_118_and_is_digest_pinned(self):
        self.assertIn(
            "docker.io/velero/velero-plugin-for-aws:v1.14.2@sha256:"
            "0751144c1c8e52d52c48717fbd13ad5a3061e612ae4d7ad744a946cd5b139d1a",
            VALUES,
        )
        self.assertNotIn("velero-plugin-for-aws:v1.13", VALUES)

    def test_repository_maintenance_has_supported_frequency_and_all_limits(self):
        self.assertIn("defaultRepoMaintainFrequency: 168h0m0s", VALUES)
        self.assertNotIn("defaultRepoMaintenanceFrequency", VALUES)
        section = VALUES.split("repositoryMaintenanceJob:", 1)[1].split(
            "# Use node-agent", 1
        )[0]
        for expected in (
            'keepLatestMaintenanceJobs: 3',
            'cpuRequest: "100m"',
            'cpuLimit: "1"',
            'memoryRequest: "512Mi"',
            'memoryLimit: "2Gi"',
            "loadAffinity:",
            "- key: node-pool",
            'values: ["ks5-nvme"]',
        ):
            self.assertIn(expected, section)
        self.assertEqual(section.count("loadAffinity:"), 1)
        self.assertNotIn("topology: lan", section)

    def test_node_agent_covers_lan_and_ovh_but_not_remote(self):
        section = VALUES.split("nodeAgent:", 1)[1].split("# Velero server", 1)[0]
        self.assertIn('values: ["lan", "ovh"]', section)
        self.assertNotIn('values: ["lan", "ovh", "remote"]', section)
        self.assertIsNone(re.search(r"^  nodeSelector:\s*$", section, re.MULTILINE))
        self.assertIn("--node-agent-configmap=velero-node-agent-config", section)
        self.assertIn('cpu: "1"', section)
        self.assertNotIn("privileged:", section)

    def test_node_agent_config_limits_data_movers(self):
        match = re.search(
            r"^  node-agent-config\.json: \|\n(?P<body>(?: {4}.*(?:\n|$))+)",
            NODE_AGENT_CONFIG,
            re.MULTILINE,
        )
        self.assertIsNotNone(match)
        config = json.loads(textwrap.dedent(match.group("body")))
        self.assertEqual(
            config["loadConcurrency"],
            {"globalConfig": 1, "prepareQueueLength": 12},
        )
        self.assertEqual(
            config["podResources"],
            {
                "cpuRequest": "100m",
                "cpuLimit": "1000m",
                "memoryRequest": "256Mi",
                "memoryLimit": "1Gi",
            },
        )

    def test_configmap_is_gitops_managed_and_server_stays_on_ks5(self):
        self.assertIn("- platform/velero/node-agent-config.yaml", KUSTOMIZATION)
        self.assertRegex(VALUES, r"(?m)^nodeSelector:\n  node-pool: ks5-nvme$")
        self.assertNotIn("single LAN-pinned node-agent", SCHEDULES)


if __name__ == "__main__":
    unittest.main()
