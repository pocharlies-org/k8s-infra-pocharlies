import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (ROOT / "storage/longhorn/system-backup-cron.yaml").read_text()
KUSTOMIZATION = (ROOT / "kustomization.yaml").read_text()
RUNBOOK = (ROOT / "docs/runbook-longhorn-systembackup.md").read_text()


class LonghornSystemBackupContractTest(unittest.TestCase):
    def test_design_is_gitops_managed_but_inert_until_external_dr_gate(self):
        self.assertIn("- storage/longhorn/system-backup-cron.yaml", KUSTOMIZATION)
        self.assertIn("kind: CronJob", MANIFEST)
        self.assertIn("suspend: true", MANIFEST)
        self.assertIn("concurrencyPolicy: Forbid", MANIFEST)
        self.assertIn("timeZone: Etc/UTC", MANIFEST)
        self.assertIn("backoffLimit: 0", MANIFEST)
        self.assertNotIn("argocd.argoproj.io/hook", MANIFEST)

    def test_retention_and_observability_are_bounded(self):
        self.assertIn('value: "4"', MANIFEST)
        self.assertIn("successfulJobsHistoryLimit: 3", MANIFEST)
        self.assertIn("failedJobsHistoryLimit: 7", MANIFEST)
        self.assertIn("activeDeadlineSeconds: 93600", MANIFEST)
        self.assertIn('"system_backup_ready"', MANIFEST)
        self.assertIn('"system_backup_error"', MANIFEST)
        self.assertIn('"deleting_expired_system_backup"', MANIFEST)
        self.assertIn("managed_ready[retain:]", MANIFEST)
        self.assertIn('and item.get("status", {}).get("state") == "Ready"', MANIFEST)

    def test_preflight_fails_closed_before_creating_any_backup(self):
        create_position = MANIFEST.index('"creating_system_backup"')
        for required_gate in (
            'validate_external_target("default")',
            '"active_or_unknown_system_backup"',
            '"system_restore_present"',
            '"active_or_unknown_longhorn_backup"',
            '"active_or_unknown_velero_backup"',
            '"degraded_longhorn_volumes"',
            '"volumes_without_last_backup"',
        ):
            self.assertIn(required_gate, MANIFEST)
            self.assertLess(MANIFEST.index(required_gate), create_position)
        self.assertIn('required_failure_domain = "external"', MANIFEST)
        self.assertIn('"100.83.56.98"', MANIFEST)
        self.assertIn('".svc.cluster.local"', MANIFEST)
        self.assertIn('"volumeBackupPolicy": "if-not-present"', MANIFEST)
        self.assertNotIn('"Unknown",', MANIFEST)

    def test_rbac_is_namespaced_and_cannot_mutate_systemrestore(self):
        self.assertNotIn("kind: ClusterRole", MANIFEST)
        self.assertNotIn("kind: ClusterRoleBinding", MANIFEST)
        self.assertIn('resources: ["systembackups"]', MANIFEST)
        self.assertIn('verbs: ["get", "list", "create", "delete"]', MANIFEST)
        self.assertIn(
            'resources: ["backuptargets", "backups", "volumes", "systemrestores"]',
            MANIFEST,
        )
        self.assertIn('verbs: ["get", "list"]', MANIFEST)
        self.assertNotRegex(
            MANIFEST,
            r'resources: \["systemrestores"\][\s\S]{0,160}'
            r'verbs: \[[^\]]*(?:create|update|patch|delete)',
        )
        self.assertNotIn("kind: SystemRestore", MANIFEST)

    def test_runner_is_pinned_nonroot_and_ks5_only(self):
        self.assertIn("node-pool: ks5-nvme", MANIFEST)
        self.assertNotIn("kubernetes.io/hostname: ubuntu", MANIFEST)
        self.assertIn("runAsNonRoot: true", MANIFEST)
        self.assertIn("runAsUser: 65532", MANIFEST)
        self.assertIn("readOnlyRootFilesystem: true", MANIFEST)
        self.assertIn('drop: ["ALL"]', MANIFEST)
        self.assertRegex(MANIFEST, r"image: python:[^\s]+@sha256:[0-9a-f]{64}")

    def test_embedded_runner_compiles(self):
        script = MANIFEST.split("              args:\n                - |\n", 1)[1].split(
            "\n              env:", 1
        )[0]
        compile(textwrap.dedent(script), "system-backup-runner", "exec")

    def test_runbook_keeps_restore_manual_and_separate(self):
        self.assertIn("NO-GO", RUNBOOK)
        self.assertIn("SystemBackup no sustituye", RUNBOOK)
        self.assertIn("No existe ningún manifiesto `SystemRestore`", RUNBOOK)
        self.assertIn("mismo minor de Longhorn", RUNBOOK)


if __name__ == "__main__":
    unittest.main()
