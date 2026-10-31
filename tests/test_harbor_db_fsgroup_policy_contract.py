"""INFRA-965: contract of the harbor-db-fsgroup-onrootmismatch ClusterPolicy.

The harbor chart hardcodes `fsGroup: 999` on the database pod and repairs the
Postgres data directory only with the `data-permissions-ensurer` init
container, which runs at pod CREATION. Every time kubelet (re)mounts the volume
it re-applies the recursive chown/chmod and the data dir goes back to 2770
(gid 999 + group write + setgid), which Postgres refuses to start with. On
21-10-2026 that took Harbor's database down for a day and no image could be
pushed to harbor.e-dani.com; the same 2770 was measured again on the live PVC
on 28-10-2026 with the pod never recreated.

The policy must therefore keep setting `fsGroupChangePolicy: OnRootMismatch` on
the POD -- not on the StatefulSet, so the chart-rendered manifest stays
byte-identical and ArgoCD stays Synced without an ignoreDifferences entry --
and must never mutate existing objects on policy update (INFRA-512).
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICIES = ROOT / "platform" / "kyverno" / "policies.yaml"
POLICY_NAME = "harbor-db-fsgroup-onrootmismatch"


def documents():
    return [d for d in yaml.safe_load_all(POLICIES.read_text()) if d]


def harbor_policy():
    for doc in documents():
        if doc.get("kind") == "ClusterPolicy" and doc.get("metadata", {}).get("name") == POLICY_NAME:
            return doc
    raise AssertionError(f"ClusterPolicy {POLICY_NAME} missing from policies.yaml")


class TestHarborDbFsgroupPolicyContract(unittest.TestCase):
    def test_mutates_the_pod_not_the_statefulset(self):
        """The chart owns the StatefulSet; patching it would leave ArgoCD OutOfSync."""
        for rule in harbor_policy()["spec"]["rules"]:
            kinds = []
            for match in rule["match"]["any"]:
                kinds += match["resources"]["kinds"]
            self.assertEqual(kinds, ["Pod"], f"rule {rule['name']} must mutate Pods only, got {kinds}")

    def test_scoped_to_the_harbor_database_pod(self):
        rules = harbor_policy()["spec"]["rules"]
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule["match"]["any"][0]["resources"]["namespaces"], ["harbor"])
        self.assertEqual(rule["match"]["any"][0]["resources"]["operations"], ["CREATE"])
        preconditions = rule["preconditions"]["all"]
        self.assertEqual(
            [(p["key"], p["operator"], p["value"]) for p in preconditions],
            [("{{ request.object.metadata.name || '' }}", "Equals", "harbor-database-0")],
        )

    def test_sets_onrootmismatch(self):
        patch = harbor_policy()["spec"]["rules"][0]["mutate"]["patchStrategicMerge"]
        self.assertEqual(patch["spec"]["securityContext"], {"fsGroupChangePolicy": "OnRootMismatch"})

    def test_admission_only(self):
        """INFRA-512: mutating existing objects on policy update rewrote 214 objects."""
        policy = harbor_policy()
        self.assertNotIn("mutateExistingOnPolicyUpdate", yaml.dump(policy))
        self.assertEqual(policy["spec"]["webhookConfiguration"]["failurePolicy"], "Ignore")


if __name__ == "__main__":
    unittest.main()
