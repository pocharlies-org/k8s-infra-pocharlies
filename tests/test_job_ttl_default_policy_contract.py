"""SC-5907: contract of the job-ttl-default ClusterPolicy.

It replaced kube-system/sauvage-pod-reaper: every Job admitted without a ttl gets 86400.
Behaviour is proven live (probe Jobs in the PR); this pins what must not drift: admission
only with failurePolicy Ignore, add-only (an owner's ttl wins), and ArgoCD-tracked Jobs
that are not hooks left alone (a TTL'd synced Job is re-created and re-run by selfHeal).
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICIES = ROOT / "platform" / "kyverno" / "policies.yaml"
NAME = "job-ttl-default"


def policy():
    for doc in yaml.safe_load_all(POLICIES.read_text()):
        if doc and doc.get("kind") == "ClusterPolicy" and doc["metadata"]["name"] == NAME:
            return doc
    raise AssertionError(f"ClusterPolicy {NAME} missing from policies.yaml")


class TestJobTtlDefaultPolicyContract(unittest.TestCase):
    def test_admission_only_ignore(self):
        spec = policy()["spec"]
        self.assertIs(spec["admission"], True)
        self.assertIs(spec["background"], False)
        self.assertEqual(spec["webhookConfiguration"]["failurePolicy"], "Ignore")

    def test_adds_ttl_only_when_absent(self):
        rule = policy()["spec"]["rules"][0]
        self.assertEqual(rule["match"]["any"][0]["resources"]["operations"], ["CREATE"])
        self.assertEqual(rule["mutate"]["patchStrategicMerge"], {"spec": {"+(ttlSecondsAfterFinished)": 86400}})

    def test_argocd_synced_jobs_excluded_unless_hook(self):
        keys = [c["key"] for c in policy()["spec"]["rules"][0]["preconditions"]["any"]]
        self.assertIn("argocd.argoproj.io/tracking-id", keys[0])
        self.assertIn("argocd.argoproj.io/hook", keys[1])
        self.assertIn("helm.sh/hook", keys[1])

    def test_reaper_is_gone(self):
        self.assertFalse((ROOT / "kubernetes" / "workloads" / "sauvage-pod-reaper.yaml").exists())
        self.assertNotIn("sauvage-pod-reaper", (ROOT / "kustomization.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
