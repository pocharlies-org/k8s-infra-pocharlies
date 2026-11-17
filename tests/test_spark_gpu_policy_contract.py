"""DGX-1665: contract of the spark-gpu-queue-only ClusterPolicy.

GPU on the NVIDIA Sparks only through the queue (Dani, 17-11-2026). The behaviour of the
rules is exercised by tests/kyverno/spark-gpu/run-offline.sh (Kyverno CLI, one fixture per
case); this file pins the shape that must not drift: Enforce from day one, admission only,
no autogen (the Pod rule judges the creator), the three rules and every fixture present.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICIES = ROOT / "platform" / "kyverno" / "policies.yaml"
FIXTURES = ROOT / "tests" / "kyverno" / "spark-gpu"
NAME = "spark-gpu-queue-only"


def policy():
    for doc in yaml.safe_load_all(POLICIES.read_text()):
        if doc and doc.get("kind") == "ClusterPolicy" and doc["metadata"]["name"] == NAME:
            return doc
    raise AssertionError(f"ClusterPolicy {NAME} missing from policies.yaml")


class TestSparkGpuPolicyContract(unittest.TestCase):
    def test_enforce_admission_only_without_autogen(self):
        pol = policy()
        self.assertEqual(pol["spec"]["validationFailureAction"], "Enforce")
        self.assertIs(pol["spec"]["background"], False)
        self.assertEqual(pol["metadata"]["annotations"]["pod-policies.kyverno.io/autogen-controllers"], "none")

    def test_three_rules(self):
        names = [r["name"] for r in policy()["spec"]["rules"]]
        self.assertEqual(names, [
            "spark-gpu-pods-only-from-controllers",
            "spark-gpu-workloads-only-from-gitops-or-queue",
            "spark-gpu-jobs-must-end",
        ])

    def test_messages_name_the_ticket(self):
        for rule in policy()["spec"]["rules"]:
            self.assertIn("DGX-1665", rule["validate"]["message"])

    def test_incident_and_bypass_fixtures_exist(self):
        for name in ("deny-incident-pod", "deny-runtimeclass-only-pod", "deny-forged-owner-pod",
                     "allow-comfyui-lane-pod", "allow-resident-worker-pod", "allow-dashboard-job",
                     # DGX-1672: gpu-operator's CUDA validator, and only it
                     "allow-gpu-operator-cuda-validator-pod", "deny-gpu-operator-validator-sa-other-pod",
                     "deny-admin-cuda-validator-pod"):
            path = FIXTURES / f"{name}.yaml"
            self.assertTrue(path.is_file(), path)
            self.assertTrue(path.read_text().startswith("# user: "), path)


if __name__ == "__main__":
    unittest.main()
