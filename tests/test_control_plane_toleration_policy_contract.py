"""SC-6096: contract of the control-plane-toleration-allowlist ClusterPolicy.

ks5-cp-1/2/3 are tainted node-role.kubernetes.io/control-plane:NoSchedule (registry:
kubernetes/node-labels/labels-job.yaml) so nothing that is not the control plane can be
scheduled there (SC-6094: shared Postgres + metrics store saturated ks5-cp-3). The
toleration is added at admission only to the allowlist — pods declaring workload=core or
node-pool=ks5-nvme, DaemonSet pods and longhorn-system pods. The behaviour is exercised by
tests/kyverno/cp-toleration/run-offline.sh (Kyverno CLI); this file pins the shape that
must not drift: admission only, failurePolicy Ignore (house pattern), the single rule, the
four allowlist conditions, the exact toleration, and every fixture present.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICIES = ROOT / "platform" / "kyverno" / "policies.yaml"
FIXTURES = ROOT / "tests" / "kyverno" / "cp-toleration"
NAME = "control-plane-toleration-allowlist"


def policy():
    for doc in yaml.safe_load_all(POLICIES.read_text()):
        if doc and doc.get("kind") == "ClusterPolicy" and doc["metadata"]["name"] == NAME:
            return doc
    raise AssertionError(f"ClusterPolicy {NAME} missing from policies.yaml")


class TestControlPlaneTolerationPolicyContract(unittest.TestCase):
    def test_admission_only_with_ignore_failure_policy(self):
        pol = policy()
        self.assertIs(pol["spec"]["admission"], True)
        self.assertIs(pol["spec"]["background"], False)
        self.assertEqual(pol["spec"]["webhookConfiguration"]["failurePolicy"], "Ignore")

    def test_single_mutate_rule_on_pod_create(self):
        rules = policy()["spec"]["rules"]
        self.assertEqual([r["name"] for r in rules], ["add-control-plane-toleration"])
        rule = rules[0]
        match = rule["match"]["any"][0]["resources"]
        self.assertEqual(match["kinds"], ["Pod"])
        self.assertEqual(match["operations"], ["CREATE"])

    def test_allowlist_preconditions(self):
        # preconditions, not conditions: the CLI (run-offline.sh) showed the new `conditions`
        # block is not evaluated on a mutate rule.
        conds = policy()["spec"]["rules"][0]["preconditions"]["any"]
        keys = [c["key"] for c in conds]
        self.assertEqual(keys, [
            "{{ request.object.spec.nodeSelector.workload || '' }}",
            '{{ request.object.spec.nodeSelector."node-pool" || \'\' }}',
            "{{ length((request.object.metadata.ownerReferences || `[]`)[?kind=='DaemonSet']) }}",
            "{{ request.namespace }}",
        ])
        self.assertEqual(conds[0]["value"], "core")
        self.assertEqual(conds[1]["value"], "ks5-nvme")
        self.assertEqual(conds[3]["value"], "longhorn-system")

    def test_toleration_is_the_control_plane_noschedule(self):
        tol = policy()["spec"]["rules"][0]["mutate"]["patchStrategicMerge"]["spec"]["tolerations"]
        self.assertEqual(tol, [{
            "key": "node-role.kubernetes.io/control-plane",
            "operator": "Exists",
            "effect": "NoSchedule",
        }])

    def test_labels_job_registers_the_taint(self):
        job = (ROOT / "kubernetes" / "node-labels" / "labels-job.yaml").read_text()
        self.assertIn(
            "kubectl taint node \"$node\" node-role.kubernetes.io/control-plane:NoSchedule --overwrite",
            job,
        )

    def test_postgres_declares_the_toleration_explicitly(self):
        # its PVCs are local-path bound to ks5-cp-2/3: without the toleration the primary
        # could not come back if the Kyverno policy were missing.
        cluster = (ROOT / "databases" / "postgres-shared" / "cluster.yaml").read_text()
        self.assertIn("key: node-role.kubernetes.io/control-plane", cluster)

    def test_fixtures_exist(self):
        for name in ("allow-core-pod", "allow-nvme-pod", "allow-daemonset-pod",
                     "allow-longhorn-sharemanager", "deny-plain-pod", "deny-runner-pod"):
            path = FIXTURES / f"{name}.yaml"
            self.assertTrue(path.is_file(), path)
            self.assertTrue(path.read_text().startswith("# user: "), path)


if __name__ == "__main__":
    unittest.main()
