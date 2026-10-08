"""OWU-28 historia g: contract of the reverse C2 fixture user.

The reconciler agentgateway-write-fixture-user.sh owns EXACTLY ONE IdP fact —
the human test user qa-write-sin-vinculo@e-dani.com of realm edani: it
exists, is enabled, holds the password of its 1Password item (applied through
the ExternalSecret agentgateway-write-fixture-user-credentials), holds the
realm role agentgateway-write, belongs to no group and is not a service
account. Its Atlassian negative is by construction (no entry in
atlassian-identity-bindings, fail-closed by absence in the agentgateway
shim), so nothing here touches that repo.

Unlike the OWU-80 Daniel grant this hook CREATES the user (the id is minted
by Keycloak, so resolution is by EXACT username) and RE-APPLIES the password
on every sync (SC-1635/SC-1645: Keycloak must never drift from 1Password).
These tests pin the identity of the fixture, the password redaction (never
argv, never stdout — it reaches kcadm only as the KC_CLI_PASSWORD environment
of one call), the no-groups / no-service-account assertions, the wave
ordering (25 after the role hook's 20), the rollback scope (remove role +
disable, never delete), the ES/Job/kustomization wiring and the catalog
declarations (ROLES.yaml + PRINCIPALS.md) that keep the drift sweep green.
Functional tests drive the real script against a fake kcadm through the
shared harness in tests/keycloak_hook_testlib.py.
"""

import json, re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # unittest from the repo root
from keycloak_hook_testlib import (BASE, COMMON, FIXTURE, FIXTURE_FAKE_KCADM, ROOT, ROLE,
                                   SA, WRITE_ROLE_FAKE_KCADM, BootstrapSourceContractMixin,
                                   SilentWriteContractMixin, assert_job_hardened,
                                   hook_code, make_token, run_hook)

SCRIPT = BASE / "scripts" / "agentgateway-write-fixture-user.sh"
JOB = BASE / "agentgateway-write-fixture-user-job.yaml"
ROLLBACK_JOB = BASE / "manual" / "agentgateway-write-fixture-user-rollback-job.yaml"

ITEM = "keycloak-next-qa-write-sin-vinculo"
ES_NAME = "agentgateway-write-fixture-user-credentials"

# A sentinel stands in for the real password: it must never surface in the
# fake kcadm journal (argv), stdout or stderr.
PASSWORD = "Sentinel-Password-4f2e9a-DoNotLog"


class WriteFixtureUserFunctionalTest(SilentWriteContractMixin, unittest.TestCase):
    NOOP_FIXTURES = {"user-exists": "1", "addroles-silent-noop": "1"}

    def run_reconciler(self, mode="ensure", fixtures=None, extra_env=None):
        env = {"FIXTURE_PASSWORD": PASSWORD, "FAKE_USERNAME": FIXTURE,
               "FAKE_PASSWORD": PASSWORD}
        env.update(extra_env or {})
        return run_hook(SCRIPT, FIXTURE_FAKE_KCADM, mode=mode, fixtures=fixtures,
                        extra_env=env)

    # ---- ensure -------------------------------------------------------

    def test_ensure_creates_the_user_then_applies_password_and_grants_role(self):
        result, journal, state = self.run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"created":true', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("create users", journal)
        self.assertIn("set-password", journal)
        self.assertIn("--uid fixture-user-id --rolename " + ROLE, journal)
        self.assertIn(ROLE, state.get("user-roles", ""))
        self.assertIn("password-applied", state)
        # The role write is followed by a re-read (SC-1215 post-assertion).
        self.assertGreater(
            journal.rindex("role-mappings/realm"), journal.index("add-roles")
        )

    def test_ensure_is_idempotent_but_still_reapplies_the_password(self):
        # SC-1635/SC-1645: the password is re-applied on every sync so
        # Keycloak cannot drift from 1Password; creation and the grant are
        # skipped when already present.
        result, journal, state = self.run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "user-roles": ROLE + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"created":false', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("create users", journal)
        self.assertNotIn("add-roles", journal)
        self.assertIn("set-password", journal)
        self.assertIn("password-applied", state)

    def test_ensure_reenables_a_disabled_user(self):
        result, journal, state = self.run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "user-disabled": "1", "user-roles": ROLE + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("enabled=true", journal)
        self.assertNotIn("user-disabled", state)

    def test_ensure_never_leaks_the_password_into_argv_or_output(self):
        result, journal, _ = self.run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(PASSWORD, journal)
        self.assertNotIn(PASSWORD, result.stdout)
        self.assertNotIn(PASSWORD, result.stderr)
        self.assertNotIn("--new-password", journal)

    def test_ensure_fails_before_any_mutation_without_the_credential(self):
        result, journal, _ = self.run_reconciler(
            "ensure", extra_env={"FIXTURE_PASSWORD": ""}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FIXTURE_PASSWORD is empty", result.stderr)
        self.assertNotIn("create users", journal)
        self.assertNotIn("set-password", journal)
        self.assertNotIn("add-roles", journal)

    def test_ensure_never_creates_the_role(self):
        result, journal, _ = self.run_reconciler("ensure", fixtures={"role-missing": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to create it here", result.stderr)
        self.assertNotIn("create users", journal)

    def test_ensure_fails_when_the_username_is_a_service_account(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-exists": "1", "user-sa": "1"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("service account", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_fails_when_the_fixture_has_groups(self):
        # The reverse C2 negative isolates ONE variable: write WITHOUT the
        # Atlassian binding. Groups would mix fixtures — refused.
        result, journal, _ = self.run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "user-groups": "/edani-operators\n"},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("no groups", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_surfaces_server_reply_on_create_failure(self):
        # (the add-roles failure path is covered by SilentWriteContractMixin)
        result, _, _ = self.run_reconciler("ensure", fixtures={"create-fail": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("server replied", result.stderr)

    def test_ensure_fails_when_the_exact_username_is_ambiguous(self):
        # An exact search answering with two users is a realm the contract
        # does not describe: fail closed, never pick one, never create.
        result, journal, _ = self.run_reconciler("ensure", fixtures={"two-users": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("does not resolve", result.stderr)
        self.assertNotIn("create users", journal)

    # ---- audit / rollback ---------------------------------------------

    def test_audit_passes_when_present_and_fails_when_absent(self):
        ok, _, _ = self.run_reconciler(
            "audit", fixtures={"user-exists": "1", "user-roles": ROLE + "\n"}
        )
        self.assertEqual(0, ok.returncode, ok.stderr)
        self.assertIn('"present":true', ok.stdout)
        bad, journal, _ = self.run_reconciler("audit")
        self.assertNotEqual(0, bad.returncode)
        self.assertIn("audit:", bad.stderr)
        self.assertNotIn("create users", journal)
        self.assertNotIn("add-roles", journal)

    def test_rollback_removes_the_role_and_disables_without_deleting(self):
        result, journal, state = self.run_reconciler(
            "rollback", fixtures={"user-exists": "1", "user-roles": ROLE + "\n"}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("remove-roles", journal)
        self.assertIn("enabled=false", journal)
        self.assertIn("user-disabled", state)
        # Deleting a principal is the CTO's decision: never here.
        self.assertNotIn("delete", journal)

    def test_rollback_is_idempotent_when_the_user_is_absent(self):
        result, journal, _ = self.run_reconciler("rollback")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("remove-roles", journal)
        self.assertNotIn("update", journal)

    # ---- identity pins --------------------------------------------------

    def test_identity_cannot_be_repointed_by_environment(self):
        for var, value in (
            ("REALM", "other"),
            ("ROLE_NAME", "other-role"),
            ("USERNAME", "someone-else@e-dani.com"),
        ):
            result, journal, _ = self.run_reconciler("ensure", extra_env={var: value})
            self.assertNotEqual(0, result.returncode, f"{var} must be immutable")
            self.assertIn(f"{var} is immutable", result.stderr)
            self.assertNotIn("create users", journal)

    def test_unknown_mode_fails(self):
        result, _, _ = self.run_reconciler("ensure", extra_env={"MODE": "grant-everything"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("MODE must be ensure, audit, or rollback", result.stderr)


class WriteFixtureUserStaticTest(BootstrapSourceContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT
    def test_script_pins_the_reviewed_identity(self):
        script = SCRIPT.read_text()
        self.assertIn('REALM="${REALM:-edani}"', script)
        self.assertIn(f'ROLE_NAME="${{ROLE_NAME:-{ROLE}}}"', script)
        self.assertIn(f'USERNAME="${{USERNAME:-{FIXTURE}}}"', script)
        self.assertIn(f'[ "${{USERNAME}}" = "{FIXTURE}" ]', script)

    def test_password_reaches_kcadm_only_via_the_environment(self):
        code = hook_code(SCRIPT, COMMON)
        self.assertIn('KC_CLI_PASSWORD="${FIXTURE_PASSWORD}"', code)
        # Never argv, never a JSON attribute, never echoed.
        self.assertNotIn("--new-password", code)
        self.assertNotIn("-s value=", code)
        self.assertNotIn('echo "${FIXTURE_PASSWORD}"', code)
        self.assertNotIn('printf \'%s\\n\' "${FIXTURE_PASSWORD}"', code)
        self.assertNotIn("set -x", code)

    def test_script_creates_users_but_never_deletes_anything(self):
        code = hook_code(SCRIPT, COMMON)
        self.assertIn('"${KCADM}" create users', code)
        self.assertIn('"${KCADM}" set-password', code)
        self.assertIn('"${KCADM}" add-roles', code)
        self.assertIn('"${KCADM}" remove-roles', code)
        self.assertNotIn('"${KCADM}" delete', code)
        # The exact-username resolution, never a prefix search.
        self.assertIn('exact=true', code)

    def test_job_is_postsync_wave25_nonroot_pinned_and_tokenless(self):
        manifest = JOB.read_text()
        assert_job_hardened(self, manifest)
        self.assertIn(f"value: {ROLE}", manifest)
        self.assertIn(f"value: {FIXTURE}", manifest)
        self.assertIn("name: FIXTURE_PASSWORD", manifest)
        self.assertIn(f"name: {ES_NAME}", manifest)
        self.assertNotIn("KC_BOOTSTRAP_ADMIN_PASSWORD\n              value:", manifest)
        self.assertNotIn(PASSWORD, manifest)

    def test_external_secret_follows_the_onepassword_onchange_pattern(self):
        manifest = JOB.read_text()
        self.assertIn("kind: ExternalSecret", manifest)
        self.assertIn(f"name: {ES_NAME}", manifest)
        # Kyverno externalsecret-onepassword-onchange + the 1000/day quota.
        self.assertIn("refreshPolicy: OnChange", manifest)
        self.assertIn("name: onepassword", manifest)
        self.assertIn("kind: ClusterSecretStore", manifest)
        self.assertIn(f"key: {ITEM}/password", manifest)
        self.assertIn("creationPolicy: Owner", manifest)
        self.assertIn("deletionPolicy: Retain", manifest)

    def test_wave_ordering_is_after_the_role_hook(self):
        role_job = (BASE / "agentgateway-write-role-job.yaml").read_text()
        self.assertIn('argocd.argoproj.io/sync-wave: "20"', role_job)
        self.assertIn('argocd.argoproj.io/sync-wave: "25"', JOB.read_text())

    def test_wired_into_kustomize_and_rollback_is_manual(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("agentgateway-write-fixture-user-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-write-fixture-user.sh", kustomization)
        self.assertIn("keycloak-agentgateway-write-fixture-user", kustomization)
        self.assertIn("kc-admin-common.sh=scripts/kc-admin-common.sh", kustomization)
        self.assertNotIn(
            "manual/agentgateway-write-fixture-user-rollback-job.yaml", kustomization
        )
        rollback = ROLLBACK_JOB.read_text()
        self.assertIn("value: rollback", rollback)
        self.assertIn(f"value: {ROLE}", rollback)
        self.assertIn(f"value: {FIXTURE}", rollback)
        self.assertIn("backoffLimit: 0", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    def test_catalog_and_principals_declare_the_fixture(self):
        catalog = json.loads((BASE / "ROLES.yaml").read_text())
        entry = next(r for r in catalog["roles"] if r["name"] == ROLE)
        self.assertEqual(entry["grantees"], sorted([FIXTURE, SA, "me@e-dani.com"]))
        defaults = next(r for r in catalog["roles"] if r["name"] == "default-roles-edani")
        self.assertIn(FIXTURE, defaults["grantees"])
        principals_text = (BASE / "PRINCIPALS.md").read_text()
        block = re.search(r"```json\n(.*?)\n```", principals_text, re.S).group(1)
        principals = json.loads(block)
        entry = next(p for p in principals["principals"] if p["username"] == FIXTURE)
        self.assertEqual(entry["realm_roles"], sorted(entry["realm_roles"]))
        self.assertIn(ROLE, entry["realm_roles"])
        self.assertEqual(entry["owner"], "QA")
        self.assertEqual(entry["type"], "humano")

    def test_write_role_hook_tolerates_exactly_this_fixture(self):
        script = (BASE / "scripts" / "agentgateway-write-role.sh").read_text()
        self.assertIn(
            f'FIXTURE_GRANTEE_USERNAME="${{FIXTURE_GRANTEE_USERNAME:-{FIXTURE}}}"', script
        )
        self.assertIn(f'[ "${{FIXTURE_GRANTEE_USERNAME}}" = "{FIXTURE}" ]', script)
        self.assertIn('[ "${username}" = "${FIXTURE_GRANTEE_USERNAME}" ]', script)

    def test_documented_in_readme_runbook_and_ci(self):
        readme = (BASE / "README.md").read_text()
        self.assertIn("agentgateway-write-fixture-user-job.yaml", readme)
        self.assertIn(FIXTURE, readme)
        runbook = (BASE / "RUNBOOK.md").read_text()
        self.assertIn("## 17. Write fixture user", runbook)
        self.assertIn("agentgateway-write-fixture-user-rollback-job.yaml", runbook)
        self.assertIn(ITEM, runbook)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn(
            "sh -n platform/keycloak-next/scripts/agentgateway-write-fixture-user.sh", ci
        )
        self.assertIn("tests/test_agentgateway_write_fixture_user_contract.py", ci)


class WriteRoleHookToleratesFixtureUserTest(unittest.TestCase):
    """OWU-28 historia g, security condition 3: the exclusivity audit of the
    SC-44 hook tolerates EXACTLY two human holders — Daniel by subject and
    the QA fixture by exact username — and a third user still fails closed.
    The role rollback refuses to run while the fixture mapping exists."""

    def run_write_role(self, mode, fixtures=None):
        result, journal, _ = run_hook(
            BASE / "scripts" / "agentgateway-write-role.sh",
            WRITE_ROLE_FAKE_KCADM,
            mode=mode,
            flags=fixtures,
            extra_env={
                "FAKE_SUBJECT": "e51253a7-c137-4c6c-9fb9-af9cecd3b147",
                "FAKE_MCP_TOKEN": make_token(
                    [ROLE, "default-roles-edani"], "agentgateway-mcp"
                ),
            },
        )
        return result, journal

    def test_ensure_passes_with_the_fixture_present(self):
        # Both tolerated humans hold the role: the audit passes, mutating
        # nothing (the service account already holds it).
        result, journal = self.run_write_role("ensure", fixtures=["fixture_present"])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertNotIn("add-roles", journal)

    def test_ensure_still_fails_on_a_third_user(self):
        # Daniel and the fixture are tolerated; a third holder is not.
        result, _ = self.run_write_role(
            "ensure", fixtures=["fixture_present", "intruder"]
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unauthorized user", result.stderr)

    def test_role_rollback_refuses_while_the_fixture_holds(self):
        # Daniel's grant absent (his refusal message must not mask this one):
        # the fixture mapping alone must stop the role delete.
        result, journal = self.run_write_role(
            "rollback", fixtures=["human_absent", "fixture_present"]
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "agentgateway-write-fixture-user-rollback-job.yaml first", result.stderr
        )
        # Refused BEFORE any mutation.
        self.assertNotIn("remove-roles", journal)
        self.assertNotIn("delete", journal)

    def test_fixture_tolerance_is_pinned_not_environment_switchable(self):
        script = (BASE / "scripts" / "agentgateway-write-role.sh").read_text()
        self.assertIn(
            f'FIXTURE_GRANTEE_USERNAME="${{FIXTURE_GRANTEE_USERNAME:-{FIXTURE}}}"',
            script,
        )
        self.assertIn(
            f'[ "${{FIXTURE_GRANTEE_USERNAME}}" = "{FIXTURE}" ]', script
        )
        # Tolerance by exact username in the direct audit; by resolved id in
        # the effective audit (the fixture id is minted, not pinned).
        self.assertIn('[ "${username}" = "${FIXTURE_GRANTEE_USERNAME}" ]', script)
        self.assertIn("fixture_grantee_id", script)
        self.assertIn("fixture_holds_direct_role", script)
        self.assertIn(
            "agentgateway-write-fixture-user-rollback-job.yaml first", script
        )


if __name__ == "__main__":
    unittest.main()
