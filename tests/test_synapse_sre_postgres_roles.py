from pathlib import Path
import re
import unittest

import yaml


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
        self.assertIn("name: synapse-agent-m2m-db-credentials", credentials)
        self.assertIn("key: secret/synapse/agent-m2m", credentials)
        # sync-wave -1 matters only for a credential whose ROLE is created in
        # the same change: without it CNPG reconciles a role whose password
        # Secret does not exist yet. The twelve older credentials here predate
        # the convention and their Secrets already existed, so ordering is moot
        # for them — asserting the wave on all of them would be false.
        #
        # This used to be a hard count of 3, which is not an invariant at all:
        # it went red the moment an unrelated credential was added (`keep`, then
        # `aurora`) and the number said nothing about what had broken. Naming
        # the set means adding a new role+Secret pair is a deliberate edit here.
        for name in (
            "synapse-agent-m2m-db-credentials",
            "keep-db-credentials",
            "aurora-db-credentials",
        ):
            doc = next(
                d
                for d in yaml.safe_load_all(credentials)
                if d
                and d.get("kind") == "ExternalSecret"
                and d["metadata"]["name"] == name
            )
            annotations = doc["metadata"].get("annotations") or {}
            self.assertEqual(
                annotations.get("argocd.argoproj.io/sync-wave"),
                "-1",
                f"{name} was provisioned together with its role and must be in "
                "sync-wave -1",
            )
        self.assertGreaterEqual(credentials.count("property: DB_USER"), 2)
        self.assertGreaterEqual(credentials.count("property: DB_PASSWORD"), 2)
        self.assertNotIn("dataFrom:", credentials)

    def test_retired_sre_roles_stay_declared_absent(self) -> None:
        """The SRE roles must remain explicit `absent` entries.

        Deleting an entry from `managed.roles` only makes CNPG stop managing
        the role; it does not drop it, so the role would linger unmanaged. And
        flipping one back to `present` would re-create a login for a plane that
        no longer exists. Both regressions are silent without this check.
        """
        cluster = (ROOT / "databases/postgres-shared/cluster.yaml").read_text()
        for role in ("synapse_sre_m2m", "synapse_sre_reporter"):
            block = re.search(
                rf"      - name: {role}\n(?P<body>.*?)(?=      - name:|\n  backup:)",
                cluster,
                re.DOTALL,
            )
            self.assertIsNotNone(block, role)
            body = block.group("body")
            self.assertIn("ensure: absent", body)
            self.assertNotIn("passwordSecret:", body)
            self.assertNotIn("login: true", body)
        credentials = (
            ROOT / "databases/postgres-shared/app-credentials.yaml"
        ).read_text()
        self.assertNotIn("synapse-sre-", credentials)

    def test_cluster_reconciles_after_secret_wave(self) -> None:
        cluster = (ROOT / "databases/postgres-shared/cluster.yaml").read_text()
        self.assertIn(
            'synapse.e-dani.com/agent-role-credentials-generation: "2"', cluster
        )


if __name__ == "__main__":
    unittest.main()
