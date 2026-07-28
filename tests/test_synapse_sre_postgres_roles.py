from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SynapseSrePostgresRolesTest(unittest.TestCase):
    def test_migration_owner_is_nologin_and_membership_is_bounded(self) -> None:
        cluster = (ROOT / "databases/postgres-shared/cluster.yaml").read_text()

        owner = re.search(
            r"      - name: synapse_owner\n(?P<body>.*?)(?=      - name:|\n  backup:)",
            cluster,
            re.DOTALL,
        )
        self.assertIsNotNone(owner)
        owner_body = owner.group("body")
        self.assertIn("ensure: present", owner_body)
        self.assertIn("login: false", owner_body)
        self.assertIn("disablePassword: true", owner_body)
        self.assertNotIn("passwordSecret:", owner_body)
        self.assertNotIn("superuser: true", owner_body)
        self.assertNotIn("bypassrls: true", owner_body)

        for role in ("synapse_migration", "synapse_admin"):
            block = re.search(
                rf"      - name: {role}\n(?P<body>.*?)(?=      - name:|\n  backup:)",
                cluster,
                re.DOTALL,
            )
            self.assertIsNotNone(block, role)
            body = block.group("body")
            self.assertIn("inRoles:\n          - synapse_owner", body)

        migration = re.search(
            r"      - name: synapse_migration\n(?P<body>.*?)(?=      - name:|\n  backup:)",
            cluster,
            re.DOTALL,
        )
        migration_body = migration.group("body")
        self.assertIn("login: true", migration_body)
        self.assertNotIn("passwordSecret:", migration_body)
        self.assertNotIn("synapse_admin", migration_body)

    def test_roles_are_login_only_without_broad_inheritance(self) -> None:
        cluster = (ROOT / "databases/postgres-shared/cluster.yaml").read_text()
        for role, secret in (
            ("synapse_agent_m2m", "synapse-agent-m2m-db-credentials"),
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
        documents = credentials.split("\n---\n")
        for name, vault_key in (
            ("synapse-agent-m2m-db-credentials", "secret/synapse/agent-m2m"),
            ("synapse-sre-m2m-db-credentials", "secret/synapse/sre-m2m"),
            (
                "synapse-sre-reporter-db-credentials",
                "secret/synapse/sre-reporter",
            ),
        ):
            document = next(
                (
                    document
                    for document in documents
                    if f"  name: {name}\n" in document
                ),
                None,
            )
            self.assertIsNotNone(document, name)
            self.assertIn('argocd.argoproj.io/sync-wave: "-1"', document)
            self.assertIn("type: kubernetes.io/basic-auth", document)
            self.assertIn(f"key: {vault_key}", document)
            self.assertIn("property: DB_USER", document)
            self.assertIn("property: DB_PASSWORD", document)
        self.assertNotIn("dataFrom:", credentials)

    def test_cluster_reconciles_after_secret_wave(self) -> None:
        cluster = (ROOT / "databases/postgres-shared/cluster.yaml").read_text()
        self.assertIn(
            'synapse.e-dani.com/agent-role-credentials-generation: "2"', cluster
        )


if __name__ == "__main__":
    unittest.main()
