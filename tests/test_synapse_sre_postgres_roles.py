from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SynapseSrePostgresRolesTest(unittest.TestCase):
    def test_roles_are_login_only_without_broad_inheritance(self) -> None:
        cluster = (ROOT / "databases/postgres-shared/cluster.yaml").read_text()
        for role, secret in (
            ("synapse_sre_m2m", "synapse-sre-m2m-db-credentials"),
            ("synapse_sre_reporter", "synapse-sre-reporter-db-credentials"),
        ):
            block = re.search(
                rf"      - name: {role}\n(?P<body>.*?)(?=      - name:|\n  backup:)",
                cluster,
                re.DOTALL,
            )
            self.assertIsNotNone(block, role)
            body = block.group("body")
            self.assertIn("ensure: present", body)
            self.assertIn("login: true", body)
            self.assertIn("inherit: false", body)
            self.assertIn(f"name: {secret}", body)
            self.assertNotIn("bypassrls: true", body)
            self.assertNotIn("inRoles:", body)

    def test_external_secrets_are_individual_and_typed(self) -> None:
        credentials = (
            ROOT / "databases/postgres-shared/app-credentials.yaml"
        ).read_text()
        for suffix in ("m2m", "reporter"):
            self.assertIn(f"name: synapse-sre-{suffix}-db-credentials", credentials)
            self.assertIn(f"key: secret/synapse/sre-{suffix}", credentials)
        self.assertGreaterEqual(credentials.count("property: DB_USER"), 2)
        self.assertGreaterEqual(credentials.count("property: DB_PASSWORD"), 2)
        self.assertNotIn("dataFrom:", credentials)


if __name__ == "__main__":
    unittest.main()
