"""INFRA-1488: contract of the arc-runner-ttl ClusterPolicy.

Every ARC EphemeralRunner is born with a Kyverno TTL so no runner outlives 12 h. Behaviour
is proven live in the PR; this pins what must not drift: admission only with failurePolicy
Ignore, add-only label on CREATE of any EphemeralRunner, and the cleanup controller's RBAC.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCS = [d for d in yaml.safe_load_all((ROOT / "platform" / "kyverno" / "policies.yaml").read_text()) if d]


def doc(kind, name):
    for d in DOCS:
        if d.get("kind") == kind and d["metadata"]["name"] == name:
            return d
    raise AssertionError(f"{kind} {name} missing from policies.yaml")


class TestArcRunnerTtlPolicyContract(unittest.TestCase):
    def test_admission_only_ignore(self):
        spec = doc("ClusterPolicy", "arc-runner-ttl")["spec"]
        self.assertIs(spec["admission"], True)
        self.assertIs(spec["background"], False)
        self.assertEqual(spec["webhookConfiguration"]["failurePolicy"], "Ignore")

    def test_every_ephemeralrunner_gets_ttl_on_create(self):
        rule = doc("ClusterPolicy", "arc-runner-ttl")["spec"]["rules"][0]
        res = rule["match"]["any"][0]["resources"]
        self.assertEqual(res["kinds"], ["actions.github.com/v1alpha1/EphemeralRunner"])
        self.assertEqual(res["operations"], ["CREATE"])
        self.assertNotIn("namespaces", res)  # every scale set, present or future
        self.assertEqual(rule["mutate"]["patchStrategicMerge"],
                         {"metadata": {"labels": {"+(cleanup.kyverno.io/ttl)": "12h"}}})

    def test_cleanup_controller_can_delete_runners(self):
        role = doc("ClusterRole", "kyverno:cleanup-controller:arc-runners")
        self.assertEqual(role["metadata"]["labels"]["rbac.kyverno.io/aggregate-to-cleanup-controller"], "true")
        rule = role["rules"][0]
        self.assertEqual((rule["apiGroups"], rule["resources"]), (["actions.github.com"], ["ephemeralrunners"]))
        self.assertTrue({"list", "watch", "delete"} <= set(rule["verbs"]))

    def test_reports_controller_reads_runners_only(self):
        role = doc("ClusterRole", "kyverno:reports-controller:arc-runners")
        self.assertEqual(role["metadata"]["labels"]["rbac.kyverno.io/aggregate-to-reports-controller"], "true")
        self.assertEqual(role["rules"][0]["verbs"], ["get", "list", "watch"])


if __name__ == "__main__":
    unittest.main()
