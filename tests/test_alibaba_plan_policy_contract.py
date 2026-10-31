"""DGX-626 (epic DGX-619, P5b): contract of the externalsecret-alibaba-plan-only-litellm ClusterPolicy.

The Alibaba Token Plan keys (1Password items alibaba-model-studio*) are read in
namespace litellm only; every other consumer goes through the plan-gateway.
The behaviour of the rules is exercised by tests/kyverno/alibaba-plan/ (Kyverno
CLI offline, server dry-run after sync); this file pins the shape that must not
drift: Enforce, admission only, litellm excluded from every rule, the message
that names the epic and the gateway.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICIES = ROOT / "platform" / "kyverno" / "policies.yaml"
FIXTURES = ROOT / "tests" / "kyverno" / "alibaba-plan"
NAME = "externalsecret-alibaba-plan-only-litellm"


def policy():
    for doc in yaml.safe_load_all(POLICIES.read_text()):
        if doc and doc.get("kind") == "ClusterPolicy" and doc["metadata"]["name"] == NAME:
            return doc
    raise AssertionError(f"ClusterPolicy {NAME} missing from policies.yaml")


class TestAlibabaPlanPolicyContract(unittest.TestCase):
    def test_enforce_and_admission_only(self):
        spec = policy()["spec"]
        self.assertEqual(spec["validationFailureAction"], "Enforce")
        self.assertIs(spec["background"], False)
        self.assertEqual(spec["webhookConfiguration"]["failurePolicy"], "Ignore")

    def test_three_rules_cover_data_extract_and_find(self):
        names = {r["name"] for r in policy()["spec"]["rules"]}
        self.assertEqual(names, {
            "deny-alibaba-plan-data-key",
            "deny-alibaba-plan-datafrom-extract",
            "deny-alibaba-plan-datafrom-find",
        })

    def test_every_rule_targets_externalsecrets_and_excludes_litellm_only(self):
        for rule in policy()["spec"]["rules"]:
            kinds = rule["match"]["any"][0]["resources"]["kinds"]
            self.assertEqual(kinds, ["external-secrets.io/v1/ExternalSecret"], rule["name"])
            self.assertEqual(rule["exclude"]["any"],
                             [{"resources": {"namespaces": ["litellm"]}}], rule["name"])
            self.assertNotIn("mutate", rule, rule["name"])

    def test_message_names_the_epic_and_the_gateway(self):
        for rule in policy()["spec"]["rules"]:
            msg = rule["validate"]["message"]
            self.assertIn("DGX-619", msg, rule["name"])
            self.assertIn("plan-gateway", msg, rule["name"])

    def test_fixtures_are_consistent_with_the_claim(self):
        deny = sorted(FIXTURES.glob("deny-*.yaml"))
        allow = sorted(FIXTURES.glob("allow-*.yaml"))
        self.assertGreaterEqual(len(deny), 8)
        self.assertGreaterEqual(len(allow), 6)
        for f in deny:
            doc = yaml.safe_load(f.read_text())
            self.assertNotEqual(doc["metadata"]["namespace"], "litellm", f.name)
            if "catchall" not in f.name:  # a regexp that matches everything names nothing
                self.assertIn("alibaba", yaml.dump(doc["spec"]).lower(), f.name)
        for f in allow:
            doc = yaml.safe_load(f.read_text())
            blob = yaml.dump(doc["spec"]).lower()
            if "alibaba-model-studio" in blob:
                self.assertEqual(doc["metadata"]["namespace"], "litellm", f.name)


if __name__ == "__main__":
    unittest.main()
