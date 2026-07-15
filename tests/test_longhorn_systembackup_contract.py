import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (ROOT / "storage/longhorn/system-backup-cron.yaml").read_text()
KUSTOMIZATION = (ROOT / "kustomization.yaml").read_text()
RUNBOOK = (ROOT / "docs/runbook-longhorn-systembackup.md").read_text()
CI_WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text()


class LonghornSystemBackupContractTest(unittest.TestCase):
    def test_contract_is_wired_into_ci(self):
        self.assertIn("longhorn-systembackup-contract:", CI_WORKFLOW)
        self.assertIn(
            "python3 -m unittest tests/test_longhorn_systembackup_contract.py",
            CI_WORKFLOW,
        )

    def test_design_is_permanently_suspended_manual_gitops_template(self):
        self.assertIn("- storage/longhorn/system-backup-cron.yaml", KUSTOMIZATION)
        self.assertIn("kind: CronJob", MANIFEST)
        self.assertIn('schedule: "0 0 1 1 *"', MANIFEST)
        self.assertIn("suspend: true", MANIFEST)
        self.assertIn("concurrencyPolicy: Forbid", MANIFEST)
        self.assertIn("timeZone: Etc/UTC", MANIFEST)
        self.assertIn("backoffLimit: 0", MANIFEST)
        self.assertNotIn('schedule: "0 12 * * 0"', MANIFEST)
        self.assertNotIn("argocd.argoproj.io/hook", MANIFEST)
        self.assertIn("permanece `suspend: true` de forma permanente", RUNBOOK)
        self.assertIn("Nunca se debe\ncambiar `suspend` a `false`", RUNBOOK)

    def test_window_defaults_closed_and_runner_cannot_authorize_itself(self):
        self.assertIn("name: longhorn-system-backup-window", MANIFEST)
        self.assertIn('authorized: "false"', MANIFEST)
        self.assertIn("runId: closed", MANIFEST)
        self.assertIn('expiresAt: "1970-01-01T00:00:00Z"', MANIFEST)
        self.assertIn('resources: ["configmaps"]', MANIFEST)
        self.assertIn('resourceNames: ["longhorn-system-backup-window"]', MANIFEST)
        self.assertIn('verbs: ["get"]', MANIFEST)
        self.assertNotRegex(
            MANIFEST,
            r'resources: \["configmaps"\][\s\S]{0,160}'
            r'verbs: \[[^\]]*(?:create|update|patch|delete)',
        )
        self.assertIn('data.get("authorized") != "true"', MANIFEST)
        self.assertIn('"system_backup_window_too_short"', MANIFEST)
        self.assertIn('"system_backup_window_too_long"', MANIFEST)
        self.assertIn('r"[0-9a-f]{40}"', MANIFEST)

    def test_velero_exclusion_is_exact_rechecked_and_read_only(self):
        self.assertIn('resources: ["backups", "schedules"]', MANIFEST)
        self.assertIn('verbs: ["get", "list"]', MANIFEST)
        for schedule in (
            "daily-aiops",
            "daily-critical",
            "daily-x86-critical",
            "weekly-all",
        ):
            self.assertIn(f'"{schedule}"', MANIFEST)
            self.assertIn(f"`{schedule}`", RUNBOOK)
        self.assertIn("actual_schedules != required_velero_schedules", MANIFEST)
        self.assertIn('get("paused") is not True', MANIFEST)
        self.assertIn('"velero_schedules_not_paused"', MANIFEST)
        self.assertIn('"active_or_unknown_velero_backup"', MANIFEST)
        self.assertIn('metadata.get("generation")', MANIFEST)
        self.assertIn('"velero_schedule_changed_during_window"', MANIFEST)
        self.assertIn('backup_uids - expected_snapshot["backup_uids"]', MANIFEST)
        self.assertIn('"velero_backup_created_during_window"', MANIFEST)
        self.assertGreaterEqual(
            MANIFEST.count("expected_snapshot=velero_snapshot"),
            3,
        )
        self.assertGreaterEqual(
            MANIFEST.count(
                "                  read_authorized_window(expected_window=window)"
            ),
            2,
        )
        self.assertGreaterEqual(
            MANIFEST.count("                      expected_window=window,"),
            1,
        )
        self.assertNotRegex(
            MANIFEST,
            r'/apis/velero\.io[^\n]+(?:PATCH|POST|DELETE)',
        )
        self.assertIn("no se promete exclusión bidireccional", RUNBOOK)
        self.assertIn("freeze exclusivo", RUNBOOK)
        self.assertIn("UID y `metadata.generation` inicial", RUNBOOK)
        self.assertIn("cree y borre por completo entre dos polls", RUNBOOK)

    def test_deterministic_name_is_crash_safe_one_shot_lock(self):
        self.assertIn(
            'backup_name = f"longhorn-system-backup-{run_id}"', MANIFEST
        )
        self.assertIn('item.get("metadata", {}).get("name") == backup_name', MANIFEST)
        self.assertIn('"system_backup_window_already_consumed"', MANIFEST)
        self.assertIn('request("POST", longhorn_path("systembackups")', MANIFEST)
        self.assertIn(
            'expected_job_name = f"longhorn-system-backup-job-{run_id}"',
            MANIFEST,
        )
        self.assertIn('fieldPath: metadata.labels[\'batch.kubernetes.io/job-name\']', MANIFEST)
        self.assertIn('"system_backup_job_name_mismatch"', MANIFEST)
        self.assertIn("normalized_window != expected_window", MANIFEST)
        self.assertIn('"system_backup_window_changed"', MANIFEST)
        self.assertNotIn("now.strftime", MANIFEST)
        self.assertIn("dos Jobs concurrentes compiten por el mismo nombre", RUNBOOK)
        self.assertIn("nunca se reutiliza el `runId`", RUNBOOK)
        self.assertRegex(RUNBOOK, r"No\nhay replay, purge ni segundo Job")
        self.assertIn("no es un ledger anti-replay eterno", RUNBOOK)
        self.assertIn("historial Git", RUNBOOK)

    def test_volume_health_is_a_safe_state_allowlist(self):
        self.assertIn(
            'state == "attached" and robustness == "healthy"', MANIFEST
        )
        self.assertIn('state == "detached"', MANIFEST)
        self.assertIn('robustness in {"healthy", "unknown"}', MANIFEST)
        self.assertIn('"unsafe_longhorn_volume_state"', MANIFEST)
        self.assertNotIn('robustness != "degraded"', MANIFEST)
        self.assertIn("`faulted`, `degraded`", RUNBOOK)
        self.assertIn("`detached/unknown`", RUNBOOK)

    def test_retention_and_observability_are_bounded(self):
        self.assertIn('value: "4"', MANIFEST)
        self.assertIn("ttlSecondsAfterFinished: 604800", MANIFEST)
        self.assertNotIn("successfulJobsHistoryLimit:", MANIFEST)
        self.assertNotIn("failedJobsHistoryLimit:", MANIFEST)
        self.assertIn("activeDeadlineSeconds: 93600", MANIFEST)
        self.assertIn('"system_backup_ready"', MANIFEST)
        self.assertIn('"system_backup_error"', MANIFEST)
        self.assertIn('"deleting_expired_system_backup"', MANIFEST)
        self.assertIn("managed_ready[retain:]", MANIFEST)
        self.assertIn('and item.get("status", {}).get("state") == "Ready"', MANIFEST)
        self.assertIn("no están gobernados por\n`concurrencyPolicy`", RUNBOOK)

    def test_preflight_fails_closed_before_creating_any_backup(self):
        create_position = MANIFEST.index('"creating_system_backup"')
        for required_gate in (
            "window = read_authorized_window(require_full_duration=True)",
            "velero_snapshot = validate_velero_exclusion()",
            'validate_external_target("default")',
            '"active_or_unknown_system_backup"',
            '"system_restore_present"',
            '"active_or_unknown_longhorn_backup"',
            '"unsafe_longhorn_volume_state"',
            '"volumes_without_last_backup"',
        ):
            self.assertIn(required_gate, MANIFEST)
            self.assertLess(MANIFEST.index(required_gate), create_position)
        self.assertIn('required_failure_domain = "external"', MANIFEST)
        self.assertIn('"100.83.56.98"', MANIFEST)
        self.assertIn('".svc.cluster.local"', MANIFEST)
        self.assertIn('"volumeBackupPolicy": "if-not-present"', MANIFEST)

    def test_rbac_is_namespaced_and_cannot_mutate_systemrestore(self):
        self.assertNotIn("kind: ClusterRole", MANIFEST)
        self.assertNotIn("kind: ClusterRoleBinding", MANIFEST)
        self.assertIn('resources: ["systembackups"]', MANIFEST)
        self.assertIn('verbs: ["get", "list", "create", "delete"]', MANIFEST)
        self.assertIn(
            'resources: ["backuptargets", "backups", "volumes", "systemrestores"]',
            MANIFEST,
        )
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
        self.assertIn("restauran las configuraciones de ambos\n   repos", RUNBOOK)


if __name__ == "__main__":
    unittest.main()
