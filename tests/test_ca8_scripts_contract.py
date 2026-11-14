"""SC-5299 (CA8): the cut/undo scripts and the inotify limit live in git, not by hand."""
from hashlib import sha256
from pathlib import Path
import configparser
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = ROOT / "ansible"
FILES = ANSIBLE / "roles/ca8_scripts/files"

# Reviewed 2026-11-14; identical to /usr/local/sbin on atlantic, ks5-cp-1/2/3, alphalink.
PINNED_SHA256 = {
    "ca8-cut.sh": "cfc20901b3e23ca7addbc5c879e30d89ff96bcbaf0ad7ceaf35ee50ac60a7e91",
    "ca8-undo.sh": "42ed97c033a103ad79a24b55c8d4b14fb29c35e7ce95c08feaa64a161bf2ab39",
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

    def test_generator_undo_calls_the_node_script(self) -> None:
        text = (ROOT / "scripts/ca8/ca8-run-c.sh").read_text(encoding="utf-8")
        self.assertIn(
            "UNDO_B64=$(printf '%s' '/usr/local/sbin/ca8-undo.sh' | base64 -w0)", text
        )

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
