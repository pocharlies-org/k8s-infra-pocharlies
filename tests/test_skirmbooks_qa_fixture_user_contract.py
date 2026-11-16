"""SKIRM-494: contract of the Skirmbooks QA fixture user.

The reconciler skirmbooks-qa-fixture-user.sh owns EXACTLY ONE IdP fact — the
human test user qa@e-dani.com of realm edani: it exists, is enabled, holds the
password of its 1Password item (applied through the ExternalSecret
skirmbooks-qa-fixture-user-credentials) and is a member of /skirmbooks-users,
the only group oauth2-proxy-skirmbooks lets through (allowed_groups). The
group itself belongs to skirmbooks-sso.sh (wave 21): this hook refuses to
create it. The gestoria tenant role is NOT this hook's fact (migration 0096 of
skirmbooks-gestoria-src, applied: tenant skirmshop role owner).

Sister of test_agentgateway_write_fixture_user_contract.py (OWU-28-g): the
fixture machinery is shared verbatim (fixture-user-common.sh), so the fake
kcadm comes from the shared harness in keycloak_hook_testlib.py
(SKIRMBOOKS_QA_FAKE_KCADM). These tests pin the identity of the fixture, the
password redaction (never argv, never stdout), the membership post-read
(SC-1215), the refusal to create the group, the rollback scope (remove
membership + disable, never delete) and the catalog declarations
(ROLES.yaml + PRINCIPALS.md) that keep the drift sweep green.
"""

import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # unittest from the repo root
from keycloak_hook_testlib import (BASE, COMMON, FIXTURE_COMMON, ROOT,
                                   BootstrapSourceContractMixin, SKIRMBOOKS_QA_FAKE_KCADM,
                                   assert_job_hardened, run_hook)

SCRIPT = BASE / "scripts" / "skirmbooks-qa-fixture-user.sh"
JOB = BASE / "skirmbooks-qa-fixture-user-job.yaml"

ITEM = "keycloak-next-qa"
ES_NAME = "skirmbooks-qa-fixture-user-credentials"
USERNAME = "qa@e-dani.com"
GROUP = "/skirmbooks-users"

FIRST_NAME = "QA"
LAST_NAME = "Fixture"

# A sentinel stands in for the real password: it must never surface in the
# fake kcadm journal (argv), stdout or stderr.
PASSWORD = "Sentinel-Password-9c1d7b-DoNotLog"

# The complete-fixture state: user minted, profile names set, already a
# member of the group.
COMPLETE = {"user-exists": "1", "user-groups": GROUP + "\n",
            "user-firstname": FIRST_NAME + "\n", "user-lastname": LAST_NAME + "\n"}


def run_reconciler(mode="ensure", fixtures=None, extra_env=None):
    env = {"FIXTURE_PASSWORD": PASSWORD, "FAKE_USERNAME": USERNAME,
           "FAKE_PASSWORD": PASSWORD, "FAKE_GROUP": GROUP}
    env.update(extra_env or {})
    return run_hook(SCRIPT, SKIRMBOOKS_QA_FAKE_KCADM, mode=mode,
                    fixtures=fixtures, extra_env=env)


class SkirmbooksQaFixtureFunctionalTest(unittest.TestCase):
    def test_ensure_creates_the_user_then_applies_password_and_grants_membership(self):
        result, journal, state = run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"created":true', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("create users", journal)
        self.assertIn("set-password", journal)
        self.assertIn("update users/fixture-user-id/groups/skirmbooks-users-gid", journal)
        self.assertIn(GROUP, state.get("user-groups", ""))
        # The membership write is followed by a re-read (SC-1215 post-assertion).
        self.assertGreater(
            journal.rindex("get users/fixture-user-id/groups"),
            journal.index("update users/fixture-user-id/groups"),
        )

    def test_ensure_sets_the_profile_names_when_creating_the_user(self):
        # OWU-76: a user without firstName/lastName is sent to Update Account
        # Information at login. The names are part of the create itself.
        result, journal, _ = run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        create_line = next(l for l in journal.splitlines() if l.startswith("create users"))
        self.assertIn(f"firstName={FIRST_NAME}", create_line)
        self.assertIn(f"lastName={LAST_NAME}", create_line)
        self.assertIn("requiredActions=[]", create_line)
        self.assertIn("emailVerified=true", create_line)

    def test_ensure_is_a_noop_on_a_complete_fixture(self):
        result, journal, _ = run_reconciler("ensure", fixtures=dict(COMPLETE))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"created":false', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("create users", journal)
        self.assertNotIn("update users/fixture-user-id/groups", journal)
        # The password is re-applied on every sync (Keycloak == 1Password).
        self.assertIn("set-password", journal)

    def test_ensure_grants_membership_when_missing(self):
        fixtures = dict(COMPLETE)
        del fixtures["user-groups"]
        result, journal, state = run_reconciler("ensure", fixtures=fixtures)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("update users/fixture-user-id/groups/skirmbooks-users-gid", journal)
        self.assertIn(GROUP, state.get("user-groups", ""))

    def test_ensure_post_assertion_fails_when_the_membership_write_silently_noops(self):
        # SC-1215: a 0-exit write that did not land must be caught by the
        # post-ensure read, not reported as granted.
        fixtures = dict(COMPLETE)
        del fixtures["user-groups"]
        fixtures["membership-silent-noop"] = "1"
        result, _, state = run_reconciler("ensure", fixtures=fixtures)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("post-ensure assertion failed", result.stderr)
        self.assertNotIn(GROUP, state.get("user-groups", ""))

    def test_ensure_surfaces_server_reply_on_membership_write_failure(self):
        fixtures = dict(COMPLETE)
        del fixtures["user-groups"]
        fixtures["membership-fail"] = "1"
        result, _, _ = run_reconciler("ensure", fixtures=fixtures)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("server replied", result.stderr)

    def test_ensure_refuses_to_create_the_group_owned_by_skirmbooks_sso(self):
        # The group is skirmbooks-sso.sh's fact (wave 21): missing here means
        # the trunk moved — fail loud, never create it from this hook.
        result, journal, _ = run_reconciler("ensure", fixtures={"group-missing": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("owned by skirmbooks-sso.sh", result.stderr)
        self.assertNotIn("create groups", journal)

    def test_ensure_fails_before_any_mutation_without_the_password(self):
        result, journal, _ = run_reconciler("ensure", extra_env={"FIXTURE_PASSWORD": ""})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FIXTURE_PASSWORD is empty", result.stderr)
        self.assertNotIn("create users", journal)
        self.assertNotIn("update", journal)

    def test_ensure_fails_closed_when_the_username_is_ambiguous(self):
        # Two users with the exact username is a realm the contract does not
        # describe: it must never be mistaken for "absent" (which would
        # create a user).
        result, journal, _ = run_reconciler("ensure", fixtures={"two-users": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("does not resolve to at most one user", result.stderr)
        self.assertNotIn("create users", journal)

    def test_password_never_reaches_argv_stdout_or_stderr(self):
        result, journal, _ = run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(PASSWORD, journal)
        self.assertNotIn(PASSWORD, result.stdout)
        self.assertNotIn(PASSWORD, result.stderr)

    def test_audit_passes_on_a_complete_fixture(self):
        result, journal, _ = run_reconciler("audit", fixtures=dict(COMPLETE))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        # Audit mutates nothing.
        self.assertNotIn("create", journal)
        self.assertNotIn("update", journal)
        self.assertNotIn("set-password", journal)

    def test_audit_fails_when_the_membership_is_missing(self):
        fixtures = dict(COMPLETE)
        del fixtures["user-groups"]
        result, _, _ = run_reconciler("audit", fixtures=fixtures)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("is not a member of " + GROUP, result.stderr)

    def test_rollback_removes_membership_and_disables_never_deletes(self):
        result, journal, state = run_reconciler("rollback", fixtures=dict(COMPLETE))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("delete users/fixture-user-id/groups/skirmbooks-users-gid", journal)
        self.assertNotIn(GROUP, state.get("user-groups", ""))
        self.assertIn("user-disabled", state)
        # Deleting a principal is the CTO's decision: never here.
        self.assertNotIn("delete users/fixture-user-id\n", journal)

    def test_rollback_is_idempotent_on_an_absent_user(self):
        result, journal, _ = run_reconciler("rollback")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertNotIn("create", journal)


class SkirmbooksQaFixtureStaticTest(BootstrapSourceContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT
    EXTRA_LIBS = (FIXTURE_COMMON,)

    def test_script_pins_its_identity(self):
        code = SCRIPT.read_text()
        self.assertIn('[ "${USERNAME}" = "qa@e-dani.com" ]', code)
        self.assertIn('[ "${USER_GROUP}" = "/skirmbooks-users" ]', code)
        self.assertIn('[ "${REALM}" = "edani" ]', code)

    def test_script_shares_the_fixture_machinery(self):
        # The duplicados guard forced the extraction: the fixture flows come
        # from fixture-user-common.sh, never from a local copy.
        code = SCRIPT.read_text()
        self.assertIn('. "${0%/*}/fixture-user-common.sh"', code)
        self.assertNotIn("resolve_user_id() {", code)
        self.assertNotIn("apply_password() {", code)

    def test_job_manifest_is_hardened(self):
        assert_job_hardened(self, JOB.read_text())

    def test_job_wires_the_group_and_the_password_secret(self):
        manifest = JOB.read_text()
        self.assertIn("value: /skirmbooks-users", manifest)
        self.assertIn("value: qa@e-dani.com", manifest)
        self.assertIn("name: " + ES_NAME, manifest)
        self.assertIn("key: FIXTURE_PASSWORD", manifest)

    def test_external_secret_reads_the_onepassword_item(self):
        manifest = JOB.read_text()
        self.assertIn("kind: ExternalSecret", manifest)
        self.assertIn("name: " + ES_NAME, manifest)
        self.assertIn(f"key: {ITEM}/password", manifest)
        self.assertIn("refreshPolicy: OnChange", manifest)
        self.assertIn("kind: ClusterSecretStore", manifest)

    def test_kustomization_registers_the_resource_and_the_configmap(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("skirmbooks-qa-fixture-user-job.yaml", kustomization)
        self.assertIn("name: keycloak-skirmbooks-qa-fixture-user", kustomization)
        self.assertIn(
            "skirmbooks-qa-fixture-user.sh=scripts/skirmbooks-qa-fixture-user.sh",
            kustomization,
        )
        self.assertIn(
            "fixture-user-common.sh=scripts/fixture-user-common.sh", kustomization
        )

    def test_catalog_declarations_keep_the_drift_sweep_green(self):
        # The same facts tests/test_keycloak_rbac_grant_declaration_contract.py
        # enforces from the manifest: the grantee is declared in PRINCIPALS.md
        # and in the grantees of default-roles-edani in ROLES.yaml.
        principals = (BASE / "PRINCIPALS.md").read_text()
        self.assertIn('"username": "qa@e-dani.com"', principals)
        roles = json.loads((BASE / "ROLES.yaml").read_text())
        default = next(r for r in roles["roles"] if r["name"] == "default-roles-edani")
        self.assertIn(USERNAME, default["grantees"])


if __name__ == "__main__":
    unittest.main()
