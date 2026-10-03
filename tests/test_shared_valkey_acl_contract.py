from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
VALKEY_DIR = ROOT / "databases/postgres-shared"
ACTIVATION_SCRIPT = ROOT / "scripts/valkey/activate-shared-valkey-acl.sh"

TCP = lambda port: {"protocol": "TCP", "port": port}  # noqa: E731


def namespace_peer(namespace: str, pod: dict | None = None, expressions: list | None = None) -> dict:
    peer = {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": namespace}}}
    selector: dict = {}
    if pod is not None:
        selector["matchLabels"] = pod
    if expressions is not None:
        selector["matchExpressions"] = expressions
    if selector:
        peer["podSelector"] = selector
    return peer


class SharedValkeyAclContractTest(unittest.TestCase):
    def test_acl_secret_is_reconciled_from_1password_with_all_required_keys(self) -> None:
        manifest = yaml.safe_load(
            (VALKEY_DIR / "shared-valkey-secrets.yaml").read_text(encoding="utf-8")
        )
        kustomization = yaml.safe_load(
            (VALKEY_DIR / "kustomization.yaml").read_text(encoding="utf-8")
        )

        self.assertIn("shared-valkey-secrets.yaml", kustomization["resources"])
        self.assertEqual(manifest["kind"], "ExternalSecret")
        self.assertEqual(manifest["spec"]["secretStoreRef"], {
            "name": "onepassword",
            "kind": "ClusterSecretStore",
        })
        self.assertEqual(manifest["spec"]["target"], {
            "name": "shared-valkey-acl",
            "creationPolicy": "Orphan",
            "deletionPolicy": "Retain",
            "template": {
                "metadata": {
                    "annotations": {
                        "argocd.argoproj.io/tracking-id": "",
                        "argocd.argoproj.io/compare-options": "IgnoreExtraneous",
                    },
                },
            },
        })
        self.assertEqual(
            {
                item["secretKey"]: item["remoteRef"]["key"]
                for item in manifest["spec"]["data"]
            },
            {
                "users.acl": "databases-shared-valkey-acl/users_acl",
                "replication-password": (
                    "databases-shared-valkey-acl/replication_password"
                ),
                "sentinel-password": (
                    "databases-shared-valkey-acl/sentinel_password"
                ),
                "sentinel-valkey-password": (
                    "databases-shared-valkey-acl/sentinel_valkey_password"
                ),
            },
        )

    def _ingress_policy(self) -> dict:
        documents = list(yaml.safe_load_all(
            (VALKEY_DIR / "shared-valkey.yaml").read_text(encoding="utf-8")
        ))
        return next(
            document for document in documents
            if document
            and document.get("kind") == "NetworkPolicy"
            and document["metadata"]["name"] == "shared-valkey-ingress"
        )

    def test_valkey_ingress_admits_exactly_the_known_consumers(self) -> None:
        policy = self._ingress_policy()
        self.assertEqual(policy["spec"]["podSelector"], {"matchLabels": {"app": "shared-valkey"}})
        self.assertEqual(policy["spec"]["policyTypes"], ["Ingress"])
        self.assertEqual(policy["spec"]["ingress"], [
            {"from": [{"podSelector": {"matchLabels": {"app": "shared-valkey"}}}],
             "ports": [TCP(6379), TCP(26379)]},
            {"from": [namespace_peer("monitoring", pod={"app.kubernetes.io/name": "prometheus-blackbox-exporter"})],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer("skirmshop", pod={"app.kubernetes.io/instance": "affiliate"})],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer("skirmshop-brain-prod")],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer("skirmshop", pod={"app": "firecrawl-api"})],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer(
                "skirmshop",
                expressions=[{"key": "app", "operator": "In", "values": [
                    "skirmbooks-fiscal-validator",
                    "skirmbooks-fiscal-validator-validation",
                    "skirmbooks-fiscal-validator-analysis",
                ]}],
            )],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer(
                "control-nexus",
                expressions=[{"key": "app", "operator": "In", "values": [
                    "dgx-dashboard-backend",
                    "dgx-dashboard-worker",
                    "dgx-studio-bot",
                    "op-dgx-spark-bot",
                ]}],
            )],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer("whatsapp-mcp", pod={"app": "whatsapp-connector"})],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer("whatsapp-mcp", pod={"app": "whatsapp-connector-professional"})],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer("whatsapp-mcp", pod={"app": "mcp-sse"})],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer(
                "libreplay",
                expressions=[{"key": "app", "operator": "In", "values": [
                    "libreplay-web",
                    "libreplay-worker",
                    "libreplay-db-seed",
                ]}],
            )],
             "ports": [TCP(6379)]},
            {"from": [namespace_peer("monitoring", pod={"app.kubernetes.io/name": "vmagent"})],
             "ports": [TCP(9121)]},
        ])

    def test_activation_gate_reconciles_and_loads_the_acl_on_every_member(self) -> None:
        script = ACTIVATION_SCRIPT.read_text(encoding="utf-8")

        self.assertIn("externalsecret/${external_secret}", script)
        self.assertIn('"force-sync=$(date -u +%Y%m%dT%H%M%SZ)-$$"', script)
        self.assertIn('reason" == "SecretSynced"', script)
        self.assertIn(r'{{printf "%s\n" $key}}', script)
        self.assertNotIn(r'{{printf "%s\\n" $key}}', script)
        self.assertIn("ACL LOAD", script)
        self.assertIn("shared-valkey-0 shared-valkey-1 shared-valkey-2", script)
        self.assertIn("expected one master and two replicas", script)

    def test_activation_gate_proves_projection_freshness_by_hash_not_by_user_marker(self) -> None:
        script = ACTIVATION_SCRIPT.read_text(encoding="utf-8")

        # The expected digest comes from the live Secret's users.acl, not from
        # the presence of some marker account in the file.
        self.assertIn(r'"jsonpath={.data.users\.acl}"', script)
        self.assertIn("base64 -d | sha256sum", script)
        # Each member must project exactly that content before ACL LOAD runs.
        self.assertIn("sha256sum /acl/users.acl", script)
        self.assertIn('sh "$expected_sha"', script)
        self.assertIn('fail "projected ACL file is stale on ${pod}"', script)
        # The gate is account-agnostic: no per-user marker or probe survives.
        self.assertNotIn('grep -q "^user', script)
        self.assertNotIn("chatbot", script)

    def test_ci_lints_the_script_and_runs_this_contract(self) -> None:
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("shared-valkey-acl-contract:", workflow)
        self.assertIn("bash -n scripts/valkey/activate-shared-valkey-acl.sh", workflow)
        self.assertIn("tests/test_shared_valkey_acl_contract.py", workflow)


if __name__ == "__main__":
    unittest.main()
