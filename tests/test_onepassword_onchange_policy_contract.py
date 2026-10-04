"""INFRA-512: contract of the externalsecret-onepassword-onchange ClusterPolicy.

The rule that mutated EXISTING ExternalSecrets on policy update
(`onchange-existing`, `mutateExistingOnPolicyUpdate: true`) rewrote all 214
ExternalSecrets when the policy was applied on 03-10 and exhausted the daily
1Password quota of 1,000 requests. It and the ClusterRole that only it used
(`kyverno:background-controller:externalsecrets`) must never come back: this
policy mutates at admission only. The detector
(platform/external-secrets/change-detector) is what propagates changes to
objects that already exist.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICIES = ROOT / "platform" / "kyverno" / "policies.yaml"
POLICY_NAME = "externalsecret-onepassword-onchange"
BACKGROUND_ROLE = "kyverno:background-controller:externalsecrets"


def documents():
    return [d for d in yaml.safe_load_all(POLICIES.read_text()) if d]


def onchange_policy():
    for doc in documents():
        if doc.get("kind") == "ClusterPolicy" and doc.get("metadata", {}).get("name") == POLICY_NAME:
            return doc
    raise AssertionError(f"ClusterPolicy {POLICY_NAME} missing from policies.yaml")


class TestOnchangePolicyContract(unittest.TestCase):
    def test_no_mutate_existing_on_the_policy(self):
        policy = onchange_policy()
        blob = yaml.dump(policy)
        self.assertNotIn("mutateExistingOnPolicyUpdate", blob)
        rule_names = [r["name"] for r in policy["spec"]["rules"]]
        self.assertNotIn("onchange-existing", rule_names)
        self.assertIn("onchange-at-admission", rule_names)

    def test_mutate_rules_are_admission_only(self):
        for rule in onchange_policy()["spec"]["rules"]:
            mutate = rule.get("mutate")
            if mutate is None:
                continue
            self.assertNotIn("targets", mutate,
                             f"rule {rule['name']}: mutate-existing targets are forbidden (INFRA-512)")

    def test_background_controller_role_gone_from_git(self):
        for doc in documents():
            self.assertNotEqual(
                doc.get("metadata", {}).get("name"), BACKGROUND_ROLE,
                f"ClusterRole {BACKGROUND_ROLE} existed only for the removed "
                "onchange-existing rule (INFRA-512)")

    def test_no_reference_to_the_role_in_manifests(self):
        hits = []
        for path in sorted(ROOT.rglob("*.yaml")):
            if any(p in path.parts for p in (".git", ".company", ".claude")):
                continue
            if BACKGROUND_ROLE in path.read_text():
                hits.append(str(path.relative_to(ROOT)))
        self.assertEqual(hits, [], f"{BACKGROUND_ROLE} still referenced in {hits}")


if __name__ == "__main__":
    unittest.main()
