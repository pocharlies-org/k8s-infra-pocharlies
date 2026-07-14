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
VOLUME_POLICY = (ROOT / "platform/velero/volume-policy.yaml").read_text()
FREQUENCY_MIGRATION = (
    ROOT / "platform/velero/repository-frequency-migration.yaml"
).read_text()


class VeleroOperabilityContractTest(unittest.TestCase):
    def test_aws_plugin_matches_velero_118_and_is_digest_pinned(self):
        self.assertIn(
            "docker.io/velero/velero-plugin-for-aws:v1.14.2@sha256:"
            "0751144c1c8e52d52c48717fbd13ad5a3061e612ae4d7ad744a946cd5b139d1a",
            VALUES,
        )
        self.assertNotIn("velero-plugin-for-aws:v1.13", VALUES)

    def test_repository_maintenance_has_supported_frequency_and_all_limits(self):
        self.assertIn("defaultRepoMaintainFrequency: 24h0m0s", VALUES)
        self.assertNotIn("defaultRepoMaintenanceFrequency", VALUES)
        section = VALUES.split("repositoryMaintenanceJob:", 1)[1].split(
            "# Use node-agent", 1
        )[0]
        for expected in (
            'keepLatestMaintenanceJobs: 1',
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
            {"globalConfig": 1, "prepareQueueLength": 6},
        )
        self.assertEqual(
            config["podResources"],
            {
                "cpuRequest": "10m",
                "cpuLimit": "1000m",
                "memoryRequest": "128Mi",
                "memoryLimit": "1Gi",
            },
        )

    def test_fsb_policy_skips_only_ephemeral_emptydir(self):
        self.assertIn("name: velero-fsb-volume-policy", VOLUME_POLICY)
        self.assertIn("volumeTypes:\n            - emptyDir", VOLUME_POLICY)
        self.assertEqual(VOLUME_POLICY.count("type: skip"), 1)
        for durable_selector in ("persistentVolumeClaim", "csi:", "nfs:"):
            self.assertNotIn(durable_selector, VOLUME_POLICY)

    def test_all_schedules_keep_pvc_fsb_and_reference_policy(self):
        schedule_count = SCHEDULES.count("kind: Schedule")
        self.assertEqual(schedule_count, 3)
        self.assertEqual(SCHEDULES.count("defaultVolumesToFsBackup: true"), 3)
        self.assertEqual(SCHEDULES.count("name: velero-fsb-volume-policy"), 3)
        self.assertNotIn("defaultVolumesToFsBackup: false", SCHEDULES)

    def test_existing_repository_frequency_migration_is_guarded_and_scoped(self):
        self.assertIn('current != "168h0m0s"', FREQUENCY_MIGRATION)
        self.assertIn('"maintenanceFrequency": "24h0m0s"', FREQUENCY_MIGRATION)
        self.assertIn("custom_skipped={skipped}", FREQUENCY_MIGRATION)
        self.assertIn('resources: ["backuprepositories"]', FREQUENCY_MIGRATION)
        self.assertIn('verbs: ["get", "list", "patch"]', FREQUENCY_MIGRATION)
        self.assertIn(
            'resources: ["backups", "restores", "backupstoragelocations"]',
            FREQUENCY_MIGRATION,
        )
        self.assertIn('resources: ["jobs"]', FREQUENCY_MIGRATION)
        self.assertNotIn('verbs: ["*"]', FREQUENCY_MIGRATION)
        self.assertIn("kind: CronJob", FREQUENCY_MIGRATION)
        self.assertIn("suspend: true", FREQUENCY_MIGRATION)
        self.assertIn("concurrencyPolicy: Forbid", FREQUENCY_MIGRATION)
        self.assertNotIn("argocd.argoproj.io/hook", FREQUENCY_MIGRATION)
        self.assertIn("active backup or restore; refusing migration", FREQUENCY_MIGRATION)
        self.assertIn("active repository maintenance; refusing migration", FREQUENCY_MIGRATION)
        self.assertIn(
            "BackupStorageLocations are not both Available", FREQUENCY_MIGRATION
        )
        script = FREQUENCY_MIGRATION.split("                - |\n", 1)[1].split(
            "\n              env:", 1
        )[0]
        compile(textwrap.dedent(script), "repository-frequency-migration", "exec")

    def test_configmap_is_gitops_managed_and_server_stays_on_ks5(self):
        self.assertIn("- platform/velero/node-agent-config.yaml", KUSTOMIZATION)
        self.assertIn("- platform/velero/volume-policy.yaml", KUSTOMIZATION)
        self.assertIn(
            "- platform/velero/repository-frequency-migration.yaml", KUSTOMIZATION
        )
        self.assertRegex(VALUES, r"(?m)^nodeSelector:\n  node-pool: ks5-nvme$")
        self.assertNotIn("single LAN-pinned node-agent", SCHEDULES)


if __name__ == "__main__":
    unittest.main()
