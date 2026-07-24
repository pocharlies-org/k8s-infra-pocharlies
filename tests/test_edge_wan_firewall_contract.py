from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "ansible/roles/edge_wan_firewall"


class EdgeWanFirewallContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = yaml.safe_load(
            (ROLE / "defaults/main.yml").read_text(encoding="utf-8")
        )
        self.tasks_text = (ROLE / "tasks/main.yml").read_text(encoding="utf-8")
        self.rules_text = (
            ROLE / "templates/edge-wan-firewall.nft.j2"
        ).read_text(encoding="utf-8")
        self.script_text = (
            ROLE / "templates/edge-wan-firewall.sh.j2"
        ).read_text(encoding="utf-8")
        self.unit_text = (
            ROLE / "templates/edge-wan-firewall.service.j2"
        ).read_text(encoding="utf-8")

    def test_defaults_are_narrow_and_derive_only_the_public_route_interface(
        self,
    ) -> None:
        self.assertEqual(self.defaults["edge_wan_firewall_state"], "present")
        self.assertEqual(
            self.defaults["edge_wan_firewall_interfaces"],
            [
                "{{ edge_wan_interface | "
                "default(ansible_default_ipv4.interface) }}"
            ],
        )
        self.assertEqual(
            self.defaults["edge_wan_firewall_blocked_tcp_ports"], [32763]
        )
        self.assertEqual(
            self.defaults["edge_wan_firewall_table"], "edge_wan_guard"
        )
        self.assertLess(self.defaults["edge_wan_firewall_hook_priority"], 0)

    def test_day_two_inventory_pins_live_verified_wan_interfaces(self) -> None:
        inventory = (
            ROOT / "ansible/inventory/ks5-tailscale.ini"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "ks5-cp-1 ansible_host=ks5-cp-1.taile0ad27.ts.net "
            "edge_wan_interface=enp3s0f0",
            inventory,
        )
        self.assertIn(
            "ks5-cp-2 ansible_host=ks5-cp-2.taile0ad27.ts.net "
            "edge_wan_interface=enp3s0f0",
            inventory,
        )
        self.assertIn(
            "ks5-cp-3 ansible_host=ks5-cp-3.taile0ad27.ts.net "
            "edge_wan_interface=eno1",
            inventory,
        )
        self.assertIn(
            "sauvage ansible_host=100.109.183.9 "
            "edge_wan_interface=enp5s0f0",
            inventory,
        )
        self.assertIn("[edge_wan_firewall:children]", inventory)
        self.assertIn("edge_wan_workers", inventory)

    def test_ruleset_blocks_only_configured_tcp_ports_on_wan_interfaces(
        self,
    ) -> None:
        self.assertIn("table inet {{ edge_wan_firewall_table }}", self.rules_text)
        self.assertIn("type filter hook input priority", self.rules_text)
        self.assertIn("policy accept", self.rules_text)
        self.assertIn("iifname", self.rules_text)
        self.assertIn("tcp dport", self.rules_text)
        self.assertIn(
            "edge_wan_firewall_blocked_tcp_ports", self.rules_text
        )
        for allowed_port in ("80", "443", "4444"):
            self.assertNotIn(f"dport {allowed_port}", self.rules_text)
        self.assertNotIn("tailscale0", self.rules_text)
        self.assertNotIn("drop", self.rules_text.lower())

    def test_apply_script_validates_then_replaces_in_one_nft_transaction(
        self,
    ) -> None:
        self.assertIn('"$nft" --check --file "$batch"', self.script_text)
        self.assertIn('"$nft" --file "$batch"', self.script_text)
        self.assertIn(
            'printf "delete table %s %s\\n" "$family" "$table"',
            self.script_text,
        )
        self.assertIn("remove)", self.script_text)
        self.assertIn("delete table", self.script_text)

    def test_dedicated_unit_loads_before_k3s_and_does_not_manage_global_nftables(
        self,
    ) -> None:
        self.assertIn("Before=k3s.service", self.unit_text)
        self.assertIn("Type=oneshot", self.unit_text)
        self.assertIn("RemainAfterExit=yes", self.unit_text)
        self.assertIn(
            "ExecStart={{ edge_wan_firewall_script_path }} apply",
            self.unit_text,
        )
        self.assertIn(
            "ExecStop={{ edge_wan_firewall_script_path }} remove",
            self.unit_text,
        )
        self.assertNotIn("nftables.service", self.unit_text)

    def test_role_validates_scope_and_has_idempotent_present_and_absent_paths(
        self,
    ) -> None:
        self.assertIn("edge_wan_firewall_state in ['present', 'absent']", self.tasks_text)
        self.assertIn("ansible_default_ipv4.interface", self.tasks_text)
        self.assertIn("ansible_interfaces", self.tasks_text)
        self.assertIn("tailscale0", self.tasks_text)
        self.assertIn("lo", self.tasks_text)
        self.assertIn("else 'started'", self.tasks_text)
        self.assertIn("enabled: true", self.tasks_text)
        self.assertIn("state: stopped", self.tasks_text)
        self.assertIn("enabled: false", self.tasks_text)
        self.assertIn("edge_wan_firewall_state == 'present'", self.tasks_text)
        self.assertIn("edge_wan_firewall_state == 'absent'", self.tasks_text)
        self.assertIn("groups.get('edge_wan_firewall'", self.tasks_text)
        self.assertIn("policy_rc_d: 101", self.tasks_text)
        self.assertIn("is-enabled", self.tasks_text)
        self.assertIn("nftables.service", self.tasks_text)
        self.assertIn("check_mode: false", self.tasks_text)
        self.assertIn("not ansible_check_mode", self.tasks_text)
        self.assertNotIn("community.general.ufw", self.tasks_text)
        self.assertNotIn("name: nftables.service", self.tasks_text)
        self.assertNotIn("ansible.builtin.shell", self.tasks_text)
        self.assertNotIn("ssh ", self.tasks_text.lower())

    def test_day_two_playbook_is_serial_and_targets_only_public_edges(
        self,
    ) -> None:
        playbook = yaml.safe_load(
            (
                ROOT / "ansible/playbooks/edge-wan-firewall.yml"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(len(playbook), 1)
        play = playbook[0]
        self.assertEqual(play["hosts"], "edge_wan_firewall")
        self.assertTrue(play["become"])
        self.assertTrue(play["gather_facts"])
        self.assertEqual(play["serial"], 1)
        self.assertTrue(play["any_errors_fatal"])
        self.assertEqual(play["roles"], ["edge_wan_firewall"])

    def test_bootstrap_installs_guard_after_k3s_control_plane(self) -> None:
        bootstrap = yaml.safe_load(
            (ROOT / "ansible/playbooks/bootstrap-ks5.yml").read_text(
                encoding="utf-8"
            )
        )
        roles = bootstrap[0]["roles"]
        self.assertEqual(
            roles[roles.index("k3s_control_plane") + 1],
            "edge_wan_firewall",
        )

    def test_runbook_documents_canary_rollout_and_single_command_rollback(
        self,
    ) -> None:
        runbook = (ROOT / "docs/runbook.md").read_text(encoding="utf-8")
        self.assertIn("--limit ks5-cp-1", runbook)
        self.assertIn("sauvage", runbook)
        self.assertIn(
            "-e edge_wan_firewall_state=absent",
            runbook,
        )
        self.assertIn("systemctl is-enabled nftables.service", runbook)
        self.assertGreaterEqual(runbook.count("ansible edge_wan_firewall"), 2)
        self.assertIn("80/tcp", runbook)
        self.assertIn("443/tcp", runbook)
        self.assertIn("4444/tcp", runbook)
        self.assertIn("tailscale0", runbook)
        self.assertIn("does not open", runbook)


if __name__ == "__main__":
    unittest.main()
