"""SC-5299 (CA8): the cut/undo scripts and the inotify limit live in git, not by hand."""
from hashlib import sha256
from pathlib import Path
import configparser
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / "ansible"
FILES = ANSIBLE / "roles/ca8_scripts/files"

# Reviewed 2026-11-14 (undo rewritten without eval after the PR #523 security review);
# identical to /usr/local/sbin on atlantic, ks5-cp-1/2/3, alphalink.
PINNED_SHA256 = {
    "ca8-cut.sh": "cfc20901b3e23ca7addbc5c879e30d89ff96bcbaf0ad7ceaf35ee50ac60a7e91",
    "ca8-undo.sh": "4abab6be6c9694cfec6a114972b3c4748018fda100cab9d9376f98ec9e5888fa",
}
BUGGY_UNDO = 's/-A INPUT/-D INPUT/'


def load_yaml(rel: str):
    return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))


class Ca8ScriptsContractTest(unittest.TestCase):
    def test_scripts_match_the_reviewed_copies(self) -> None:
        for name, digest in PINNED_SHA256.items():
            data = (FILES / name).read_bytes()
            self.assertEqual(sha256(data).hexdigest(), digest, name)
            self.assertTrue(data.startswith(b"#!/bin/bash\n"), name)

    def test_no_copy_of_the_buggy_undo(self) -> None:
        for path in [*FILES.iterdir(), ROOT / "scripts/ca8/ca8-run-c.sh"]:
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if BUGGY_UNDO in line:
                    # Only allowed as a quoted warning in a comment.
                    self.assertTrue(line.lstrip().startswith("#"), f"{path}: {line}")

    def test_undo_never_evaluates_rule_text(self) -> None:
        text = (FILES / "ca8-undo.sh").read_text(encoding="utf-8")
        self.assertNotIn("eval", text)
        self.assertIn("-L INPUT --line-numbers -n", text)
        # Only lists and deletes: never adds, flushes or touches a policy.
        for forbidden in (" -I ", " -A ", " -F", " -P ", " -X", "ACCEPT"):
            self.assertNotIn(forbidden, text, forbidden)

    def test_generator_cuts_and_undoes_through_the_node_scripts(self) -> None:
        text = (ROOT / "scripts/ca8/ca8-run-c.sh").read_text(encoding="utf-8")
        self.assertIn("CUT=/usr/local/sbin/ca8-cut.sh", text)
        self.assertIn("UNDO=/usr/local/sbin/ca8-undo.sh", text)
        self.assertIn('node_cmd "$n" "$CUT ', text)
        self.assertNotIn("iptables -w -I", text)
        self.assertNotIn("-I INPUT", text)
        self.assertNotIn("UNDO_B64", text)
        self.assertNotIn("StrictHostKeyChecking=no", text)
        self.assertIn("-o ServerAliveInterval=5 -o ServerAliveCountMax=3", text)

    def test_cut_schedules_undo_before_the_first_rule(self) -> None:
        text = (FILES / "ca8-cut.sh").read_text(encoding="utf-8")
        timer = text.index('run "$SYSTEMD_RUN" --unit="$UNIT"')
        backup = text.index('run "$SYSTEMD_RUN" --unit="$BACKUP_UNIT"')
        first_rule = text.index('-I INPUT')
        self.assertLess(timer, first_rule)
        self.assertLess(backup, first_rule)

    def test_role_installs_undo_before_cut_as_root_0755(self) -> None:
        task = load_yaml("ansible/roles/ca8_scripts/tasks/main.yml")[0]
        copy = task["ansible.builtin.copy"]
        self.assertEqual(task["loop"], ["ca8-undo.sh", "ca8-cut.sh"])
        self.assertEqual(copy["dest"], "/usr/local/sbin/{{ item }}")
        self.assertEqual((copy["owner"], copy["group"], copy["mode"]), ("root", "root", "0755"))

    def test_playbook_targets_ca8_nodes(self) -> None:
        play = load_yaml("ansible/playbooks/ca8-scripts.yml")[0]
        self.assertEqual(play["hosts"], "ca8_nodes")
        self.assertTrue(play["become"])
        self.assertEqual(play["roles"], ["ca8_scripts"])

    def test_inventory_ca8_nodes(self) -> None:
        inv = configparser.ConfigParser(allow_no_value=True, delimiters=(" ",))
        inv.optionxform = str
        inv.read(ANSIBLE / "inventory/ks5-tailscale.ini")
        self.assertEqual(set(inv["ca8_nodes"]), {"atlantic", "alphalink"})
        self.assertEqual(list(inv["ca8_nodes:children"]), ["ks5_control_plane"])
        self.assertEqual(set(inv["k3s_nodes:children"]), {"ovh_nodes", "ca8_nodes"})


class InotifyContractTest(unittest.TestCase):
    def test_lineinfile_owns_only_max_user_instances(self) -> None:
        task = load_yaml("ansible/roles/common_hardening/tasks/inotify.yml")[0]
        lif = task["ansible.builtin.lineinfile"]
        self.assertEqual(lif["path"], "/etc/sysctl.d/99-inotify.conf")
        self.assertIn("max_user_instances", lif["regexp"])
        self.assertNotIn("max_user_watches", str(task))
        self.assertEqual(
            lif["line"], "fs.inotify.max_user_instances = {{ common_hardening_inotify_max_user_instances }}"
        )
        defaults = load_yaml("ansible/roles/common_hardening/defaults/main.yml")
        self.assertEqual(defaults["common_hardening_inotify_max_user_instances"], 8192)

    def test_handler_sets_only_that_key(self) -> None:
        handler = load_yaml("ansible/roles/common_hardening/handlers/main.yml")[0]
        self.assertEqual(handler["name"], task_notify())
        self.assertEqual(
            handler["ansible.builtin.command"],
            "sysctl -w fs.inotify.max_user_instances={{ common_hardening_inotify_max_user_instances }}",
        )

    def test_common_role_and_playbook_include_it(self) -> None:
        main = load_yaml("ansible/roles/common_hardening/tasks/main.yml")
        self.assertIn(
            "inotify.yml", [t.get("ansible.builtin.import_tasks") for t in main]
        )
        play = load_yaml("ansible/playbooks/node-inotify.yml")[0]
        self.assertEqual(play["hosts"], "k3s_nodes:!sauvage")
        inc = play["tasks"][0]["ansible.builtin.include_role"]
        self.assertEqual((inc["name"], inc["tasks_from"]), ("common_hardening", "inotify"))


def task_notify() -> str:
    task = load_yaml("ansible/roles/common_hardening/tasks/inotify.yml")[0]
    return task["notify"]


if __name__ == "__main__":
    unittest.main()
