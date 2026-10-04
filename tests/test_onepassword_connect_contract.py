"""INFRA-511 / INFRA-523: contract of the 1Password Connect read path.

ExternalSecrets read 1Password through the in-cluster Connect server
(platform/onepassword-connect) and the `onepassword-connect` store, which do
not spend the account's daily quota. Until every repository is rewritten,
Kyverno moves ExternalSecrets written for the `onepassword` SDK store to it at
admission. This pins what keeps that safe: the translation fails open, runs
before the ExternalSecrets of this app, the OnChange policy and the change
detector cover both stores, the images come from the Harbor mirror by digest
and the store points at the Service that exists.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORES = ["onepassword", "onepassword-connect"]


def docs(path):
    return [d for d in yaml.safe_load_all((ROOT / path).read_text()) if d]


def policy(name):
    return next(d for d in docs("platform/kyverno/policies.yaml")
                if d.get("kind") == "ClusterPolicy" and d["metadata"]["name"] == name)


def wave(obj):
    return (obj["metadata"].get("annotations") or {}).get("argocd.argoproj.io/sync-wave")


def store_condition(rule):
    return next(c for c in rule["preconditions"]["all"] if "secretStoreRef.name" in c["key"])


class OnePasswordConnectContractTest(unittest.TestCase):
    def test_translation_fails_open_and_runs_before_the_externalsecrets(self):
        p = policy("externalsecret-onepassword-to-connect")
        self.assertEqual(p["spec"]["webhookConfiguration"]["failurePolicy"], "Ignore")
        self.assertEqual(wave(p), "-1")
        self.assertFalse(p["spec"]["background"])

    def test_translation_only_touches_the_sdk_store_and_has_no_mutate_existing(self):
        p = policy("externalsecret-onepassword-to-connect")
        for rule in p["spec"]["rules"]:
            cond = store_condition(rule)
            self.assertEqual((cond["operator"], cond["value"]), ("Equals", "onepassword"))
            self.assertEqual(rule["match"]["any"][0]["resources"]["kinds"], ["external-secrets.io/v1/ExternalSecret"])
            self.assertNotIn("mutateExistingOnPolicyUpdate", rule["mutate"])
        switch = next(r for r in p["spec"]["rules"] if r["name"] == "switch-store")
        self.assertEqual(switch["mutate"]["patchStrategicMerge"]["spec"]["secretStoreRef"]["name"], "onepassword-connect")

    def test_onchange_policy_covers_both_stores(self):
        for rule in policy("externalsecret-onepassword-onchange")["spec"]["rules"]:
            cond = store_condition(rule)
            self.assertEqual(cond["operator"], "AnyIn")
            self.assertEqual(sorted(cond["value"]), STORES)

    def test_change_detector_forces_both_stores(self):
        cron = docs("platform/external-secrets/change-detector/cronjob.yaml")
        job = next(d for d in cron if d.get("kind") == "CronJob")
        envs = [e for c in job["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"] for e in c.get("env", [])]
        names = next(e["value"] for e in envs if e["name"] == "STORE_NAMES")
        self.assertEqual(sorted(names.split(",")), STORES)

    def test_images_come_from_the_harbor_mirror_by_digest(self):
        dep = next(d for d in docs("platform/onepassword-connect/connect.yaml") if d["kind"] == "Deployment")
        for c in dep["spec"]["template"]["spec"]["containers"]:
            self.assertTrue(c["image"].startswith("harbor.lan.e-dani.com/"), c["image"])
            self.assertIn("@sha256:", c["image"])

    def test_store_points_at_the_connect_service(self):
        svc = next(d for d in docs("platform/onepassword-connect/connect.yaml") if d["kind"] == "Service")
        store = docs("platform/external-secrets/cluster-secret-store-onepassword-connect.yaml")[0]
        port = next(p["port"] for p in svc["spec"]["ports"] if p["name"] == "connect-api")
        expected = f"http://{svc['metadata']['name']}.{svc['metadata']['namespace']}.svc.cluster.local:{port}"
        self.assertEqual(store["spec"]["provider"]["onepassword"]["connectHost"], expected)
        self.assertEqual(store["spec"]["provider"]["onepassword"]["vaults"], {"k8s-pocharlies": 1})

    def test_a_connect_failure_does_not_hold_back_the_rest_of_the_app(self):
        # Only the namespace (-2) and the translation policy (-1) are ordered;
        # Connect and its store sync with everything else in wave 0.
        for d in docs("platform/onepassword-connect/connect.yaml"):
            self.assertIsNone(wave(d), d["kind"])
        self.assertIsNone(wave(docs("platform/external-secrets/cluster-secret-store-onepassword-connect.yaml")[0]))
        self.assertEqual(wave(docs("platform/onepassword-connect/namespace.yaml")[0]), "-2")

    def test_everything_is_in_the_app(self):
        res = yaml.safe_load((ROOT / "kustomization.yaml").read_text())["resources"]
        self.assertIn("platform/onepassword-connect", res)
        self.assertIn("platform/external-secrets/cluster-secret-store-onepassword-connect.yaml", res)


if __name__ == "__main__":
    unittest.main()
