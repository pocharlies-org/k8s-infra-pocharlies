from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/sauvage_cri_watchdog"


class SavageCriWatchdogContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = yaml.safe_load(
            (ROLE / "defaults/main.yml").read_text(encoding="utf-8")
        )
        self.tasks_text = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
        self.script_text = (
            ROLE / "templates/sauvage-cri-watchdog.sh.j2"
        ).read_text(encoding="utf-8")
        self.service_text = (
            ROLE / "templates/sauvage-cri-watchdog.service.j2"
        ).read_text(encoding="utf-8")
        self.timer_text = (
            ROLE / "templates/sauvage-cri-watchdog.timer.j2"
        ).read_text(encoding="utf-8")
        self.playbook = yaml.safe_load(
            (ROOT / "ansible/playbooks/sauvage-cri-watchdog.yml").read_text(
                encoding="utf-8"
            )
        )

    def test_defaults_keep_a_bounded_restart_policy(self) -> None:
        self.assertGreaterEqual(
            int(self.defaults["sauvage_cri_watchdog_threshold"]), 3
        )
        self.assertGreaterEqual(
            int(self.defaults["sauvage_cri_watchdog_min_gap_seconds"]), 1800
        )
        self.assertEqual(
            self.defaults["sauvage_cri_watchdog_script_path"],
            "/usr/local/bin/sauvage-cri-watchdog",
        )
        self.assertEqual(
            self.defaults["sauvage_cri_watchdog_state_file"],
            "/run/sauvage-cri-watchdog.last-restart",
        )

    def test_script_detects_the_infra_944_signature_and_restarts_k3s_agent(
        self,
    ) -> None:
        self.assertIn("Failed to create pod sandbox", self.script_text)
        self.assertIn("failed to reserve sandbox name", self.script_text)
        self.assertIn("journalctl -u k3s-agent", self.script_text)
        self.assertIn(
            "systemctl restart k3s-agent.service", self.script_text
        )
        # The restart must be rate-limited through the state file and must
        # skip a k3s-agent that is not active (already cycling on its own).
        self.assertIn(
            "{{ sauvage_cri_watchdog_state_file }}", self.script_text
        )
        self.assertIn(
            "systemctl is-active --quiet k3s-agent.service", self.script_text
        )

    def test_units_wire_timer_to_script_and_run_as_oneshot(self) -> None:
        self.assertIn(
            "ExecStart={{ sauvage_cri_watchdog_script_path }}",
            self.service_text,
        )
        self.assertIn("Type=oneshot", self.service_text)
        self.assertIn(
            "OnUnitActiveSec={{ sauvage_cri_watchdog_timer_interval }}",
            self.timer_text,
        )
        self.assertIn("WantedBy=timers.target", self.timer_text)

    def test_playbook_is_scoped_to_sauvage_with_become(self) -> None:
        play = self.playbook[0]
        self.assertEqual(play["hosts"], "sauvage")
        self.assertTrue(play["become"])
        self.assertEqual(play["roles"], ["sauvage_cri_watchdog"])
        self.assertIn("inventory_hostname == 'sauvage'", self.tasks_text)


if __name__ == "__main__":
    unittest.main()
