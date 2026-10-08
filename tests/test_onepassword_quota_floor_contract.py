"""DGX-506 regression: the quota floor (966 -> ~195 calls/day) must not quietly break.

Offline, no cluster, no 1Password. Complements test_onepassword_change_detector.py
(detector logic) and test_onepassword_onchange_policy_contract.py (no mutate-existing).
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "external-secrets" / "change-detector"
POLICIES = ROOT / "platform" / "kyverno" / "policies.yaml"
STORES = {"onepassword", "onepassword-connect"}
# Periodic exceptions (5, DGX-505) live in other repos; none is rendered here.
PERIODIC_IN_THIS_REPO = set()


def load(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def repo_externalsecrets():
    for p in sorted(ROOT.rglob("*.yaml")):
        if any(x in p.parts for x in (".git", ".claude", ".company", "node_modules")):
            continue
        try:
            docs = load(p)
        except yaml.YAMLError:
            continue
        for d in docs:
            if isinstance(d, dict) and d.get("kind") in ("ExternalSecret", "ClusterExternalSecret"):
                spec = d["spec"].get("externalSecretSpec", d["spec"])
                yield p, d, spec


class OnChangeCoverageTest(unittest.TestCase):
    def test_policy_defaults_both_stores_to_onchange(self):
        policy = next(d for d in load(POLICIES) if d.get("metadata", {}).get("name") == "externalsecret-onepassword-onchange")
        rule = policy["spec"]["rules"][0]
        stores = next(c["value"] for c in rule["preconditions"]["all"] if "secretStoreRef" in c["key"])
        self.assertEqual(set(stores), STORES)
        self.assertEqual(rule["mutate"]["patchStrategicMerge"]["spec"]["refreshPolicy"], "OnChange")
        # only fills the gap: an ES that sets its own refreshPolicy is untouched
        self.assertTrue(any("refreshPolicy" in c["key"] and c["value"] == "" for c in rule["preconditions"]["all"]))

    def test_no_onepassword_externalsecret_here_opts_out_of_onchange(self):
        seen = 0
        for p, d, spec in repo_externalsecrets():
            if (spec.get("secretStoreRef") or {}).get("name") not in STORES:
                continue
            seen += 1
            policy = spec.get("refreshPolicy")
            name = d["metadata"]["name"]
            if name in PERIODIC_IN_THIS_REPO:
                continue
            self.assertIn(policy, (None, "OnChange"), f"{p.relative_to(ROOT)}::{name} refreshPolicy={policy}")
        self.assertGreater(seen, 0, "scan found no onepassword ExternalSecret: the glob broke")


class CronJobFloorTest(unittest.TestCase):
    def setUp(self):
        self.cron = load(BASE / "cronjob.yaml")[0]
        self.pod = self.cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]

    def test_schedule_is_every_4h(self):
        self.assertEqual(self.cron["spec"]["schedule"], "23 */4 * * *")

    def test_service_account_exists_in_rbac(self):
        sa = self.pod["serviceAccountName"]
        self.assertEqual(sa, "onepassword-change-detector")
        self.assertIn(("ServiceAccount", sa), [(d["kind"], d["metadata"]["name"]) for d in load(BASE / "rbac.yaml")])

    def test_list_vault_runs_as_uid_999(self):
        c = next(c for c in self.pod["initContainers"] if c["name"] == "list-vault")
        self.assertEqual((c["securityContext"]["runAsUser"], c["securityContext"]["runAsGroup"]), (999, 999))


if __name__ == "__main__":
    unittest.main()
