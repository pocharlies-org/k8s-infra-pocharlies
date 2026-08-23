from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
VALKEY_DIR = ROOT / "databases/postgres-shared"
ACTIVATION_SCRIPT = ROOT / "scripts/valkey/activate-shared-valkey-acl.sh"


class SharedValkeyChatbotContractTest(unittest.TestCase):
    def test_acl_secret_is_reconciled_from_vault_with_all_required_keys(self) -> None:
        manifest = yaml.safe_load(
            (VALKEY_DIR / "shared-valkey-secrets.yaml").read_text(encoding="utf-8")
        )
        kustomization = yaml.safe_load(
            (VALKEY_DIR / "kustomization.yaml").read_text(encoding="utf-8")
        )

        self.assertIn("shared-valkey-secrets.yaml", kustomization["resources"])
        self.assertEqual(manifest["kind"], "ExternalSecret")
        self.assertEqual(manifest["spec"]["secretStoreRef"], {
            "name": "vault-backend",
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
                item["secretKey"]: (
                    item["remoteRef"]["key"],
                    item["remoteRef"]["property"],
                )
                for item in manifest["spec"]["data"]
            },
            {
                "users.acl": ("databases/shared-valkey-acl", "users_acl"),
                "replication-password": (
                    "databases/shared-valkey-acl",
                    "replication_password",
                ),
                "sentinel-password": (
                    "databases/shared-valkey-acl",
                    "sentinel_password",
                ),
                "sentinel-valkey-password": (
                    "databases/shared-valkey-acl",
                    "sentinel_valkey_password",
                ),
            },
        )

    def test_valkey_ingress_is_exactly_scoped_to_deterministic_chatbot(self) -> None:
        documents = list(yaml.safe_load_all(
            (VALKEY_DIR / "shared-valkey.yaml").read_text(encoding="utf-8")
        ))
        policy = next(
            document for document in documents
            if document
            and document.get("kind") == "NetworkPolicy"
            and document["metadata"]["name"] == "shared-valkey-ingress"
        )
        expected_peer = {
            "namespaceSelector": {
                "matchLabels": {"kubernetes.io/metadata.name": "skirmshop"}
            },
            "podSelector": {
                "matchLabels": {
                    "app.kubernetes.io/name": "skirmshop-chatbot",
                    "app.kubernetes.io/instance": "deterministic",
                }
            },
        }
        matching_rules = [
            rule for rule in policy["spec"]["ingress"]
            if rule.get("from") == [expected_peer]
        ]
        self.assertEqual(matching_rules, [{
            "from": [expected_peer],
            "ports": [{"protocol": "TCP", "port": 6379}],
        }])

    def test_activation_gate_loads_and_verifies_acl_on_every_member(self) -> None:
        script = ACTIVATION_SCRIPT.read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

        self.assertIn("shared-valkey-chatbot-contract:", workflow)
        self.assertIn("bash -n scripts/valkey/activate-shared-valkey-acl.sh", workflow)
        self.assertIn("tests/test_shared_valkey_chatbot_contract.py", workflow)
        self.assertIn("externalsecret/${external_secret}", script)
        self.assertIn('"force-sync=$(date -u +%Y%m%dT%H%M%SZ)-$$"', script)
        self.assertIn('reason" == "SecretSynced"', script)
        self.assertIn(r'{{printf "%s\n" $key}}', script)
        self.assertNotIn(r'{{printf "%s\\n" $key}}', script)
        self.assertIn("expected_acl_sha256", script)
        self.assertIn('env EXPECTED_ACL_SHA256="$expected_acl_sha256"', script)
        self.assertIn('projected_sha256="$(sha256sum /acl/users.acl', script)
        self.assertIn('[ "$projected_sha256" = "$EXPECTED_ACL_SHA256" ]', script)
        self.assertIn("PRE-LOAD SECURITY BOUNDARY", script)
        self.assertIn('chatbot_line_count" = 1', script)
        self.assertIn('chatbot_password_count" = 1', script)
        acl_load_position = script.index(
            'result="$(valkey-cli -p 6379 --user sentinel'
        )
        for preload_assertion in (
            '[ "$chatbot_line_count" = 1 ]',
            '[ "$chatbot_password_count" = 1 ]',
            '[ "$actual_acl_tokens" = "$expected_acl_tokens" ]',
        ):
            self.assertLess(script.index(preload_assertion), acl_load_position)
        self.assertIn("ACL LOAD", script)
        self.assertIn("ACL DRYRUN chatbot HSET", script)
        self.assertIn("actual_acl_tokens", script)
        self.assertIn("expected_acl_tokens", script)
        self.assertIn("+auth +del +eval +exists +hdel +hget +hset +incr", script)
        self.assertIn("+pexpire +ping +pttl +quit +time", script)
        self.assertNotIn("+@connection", script)
        self.assertIn(
            "User\\ chatbot\\ has\\ no\\ permissions\\ to\\ access\\ the\\ "
            "*rho:forbidden:acl-activation-probe*key",
            script,
        )
        for denied_probe in (
            "CLIENT PAUSE 1000",
            "CLIENT KILL TYPE normal",
            "CLIENT UNBLOCK 1",
            "COMMAND INFO ACL",
            "SELECT 0",
            "FLUSHDB",
        ):
            self.assertIn(f"assert_command_denied {denied_probe}", script)
        self.assertIn("NOPERM*", script)
        self.assertEqual(script.count('REDISCLI_AUTH="$chatbot_password"'), 5)
        self.assertNotIn("VALKEYCLI_AUTH", script)
        self.assertIn("shared-valkey-0 shared-valkey-1 shared-valkey-2", script)
        self.assertIn("expected one master and two replicas", script)
        self.assertIn('exec "$master_pod" -c valkey', script)
        self.assertIn("healthy replicas correctly reject writes as READONLY", script)


if __name__ == "__main__":
    unittest.main()
