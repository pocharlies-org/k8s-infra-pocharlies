"""OWU-80 (OWU-28 P6): contract of the human write grant to Daniel.

The reconciler agentgateway-write-grant-daniel.sh owns EXACTLY ONE IdP fact —
the direct realm-role mapping of agentgateway-write (realm edani) onto the
human user pinned by subject e51253a7-c137-4c6c-9fb9-af9cecd3b147
(username me@e-dani.com). These tests pin the identity of the grant, the
never-create-users / never-create-role limits, the post-ensure assertion, the
rollback scope, the wave/kustomization wiring and the catalog declarations
(ROLES.yaml + PRINCIPALS.md) that keep the keycloak-role-drift sweep green.
The functional tests drive the real script against a fake kcadm through the
shared harness in tests/keycloak_hook_testlib.py.
"""

import json
import re
import unittest

# ci.yml drives these files with `python3 -m unittest tests/<file>.py` from the
# repo root: unittest puts only the root on sys.path (pytest does not), so the
# sibling testlib module must be importable explicitly.
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from keycloak_hook_testlib import (
    BASE,
    COMMON,
    DANIEL_FAKE_KCADM,
    ROOT,
    BootstrapSourceContractMixin,
    SilentWriteContractMixin,
    assert_job_hardened,
    hook_code,
    run_hook,
)

SCRIPT = BASE / "scripts" / "agentgateway-write-grant-daniel.sh"
JOB = BASE / "agentgateway-write-grant-daniel-job.yaml"
ROLLBACK_JOB = BASE / "manual" / "agentgateway-write-grant-daniel-rollback-job.yaml"

SUBJECT = "e51253a7-c137-4c6c-9fb9-af9cecd3b147"
USERNAME = "me@e-dani.com"
# OWU-28 historia g: the second tolerated human holder of the role, the QA
# fixture of the reverse C2 test (owned by
# agentgateway-write-fixture-user.sh, pinned there by exact username).
FIXTURE = "qa-write-sin-vinculo@e-dani.com"
ROLE = "agentgateway-write"
SA = "service-account-agentgateway-mcp"


class WriteGrantDanielFunctionalTest(SilentWriteContractMixin, unittest.TestCase):
    def run_reconciler(self, mode="ensure", fixtures=None, extra_env=None):
        env = {"FAKE_SUBJECT": SUBJECT}
        env.update(extra_env or {})
        return run_hook(SCRIPT, DANIEL_FAKE_KCADM, mode=mode, fixtures=fixtures,
                        extra_env=env)

    # ---- ensure -------------------------------------------------------

    def test_ensure_grants_the_pinned_user_and_asserts_after(self):
        result, journal, state = self.run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn(f"--uid {SUBJECT} --rolename {ROLE}", journal)
        self.assertIn(ROLE, state.get("user-roles", ""))
        # The post-ensure assertion re-reads the user's direct realm-role
        # mappings (OWU-80 spec): the mapping collection was queried AFTER the
        # add-roles call, not only before it.
        self.assertGreater(journal.rindex("role-mappings/realm"), journal.index("add-roles"))

    def test_ensure_is_idempotent_when_already_granted(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-roles": ROLE + "\n"}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("add-roles", journal)

    def test_ensure_fails_loud_on_absent_subject_and_never_creates_users(self):
        result, journal, _ = self.run_reconciler("ensure", fixtures={"user-missing": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("does not exist", result.stderr)
        self.assertIn("refusing to create a human user", result.stderr)
        self.assertNotIn("add-roles", journal)
        self.assertNotIn("create", journal)

    def test_ensure_fails_on_username_drift_of_the_pinned_subject(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-username": "someone-else@e-dani.com\n"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not the pinned", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_fails_on_disabled_user(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-enabled": "false\n"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("disabled", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_refuses_a_service_account_identity(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-sa": "some-client\n"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("service account", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_never_creates_the_role(self):
        result, journal, _ = self.run_reconciler("ensure", fixtures={"role-missing": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to create it here", result.stderr)
        self.assertNotIn("add-roles", journal)
        self.assertNotIn("create", journal)

    # ---- audit / rollback ---------------------------------------------

    def test_audit_passes_when_present_and_fails_when_absent(self):
        ok, _, _ = self.run_reconciler("audit", fixtures={"user-roles": ROLE + "\n"})
        self.assertEqual(0, ok.returncode, ok.stderr)
        self.assertIn('"present":true', ok.stdout)
        bad, journal, _ = self.run_reconciler("audit")
        self.assertNotEqual(0, bad.returncode)
        self.assertIn("audit:", bad.stderr)
        self.assertNotIn("add-roles", journal)
        self.assertNotIn("remove-roles", journal)

    def test_rollback_removes_only_the_human_mapping(self):
        result, journal, state = self.run_reconciler(
            "rollback", fixtures={"user-roles": ROLE + "\n"}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn(f"--uid {SUBJECT} --rolename {ROLE}", journal)
        self.assertNotIn(ROLE, state.get("user-roles", ""))
        # The role itself is never deleted by this hook.
        self.assertNotIn("delete", journal)

    def test_rollback_is_idempotent_when_absent_or_user_gone(self):
        result, journal, _ = self.run_reconciler("rollback")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("remove-roles", journal)
        gone, _, _ = self.run_reconciler("rollback", fixtures={"user-missing": "1"})
        self.assertEqual(0, gone.returncode, gone.stderr)
        self.assertIn('"present":false', gone.stdout)

    # ---- identity pins --------------------------------------------------

    def test_identity_cannot_be_repointed_by_environment(self):
        for var, value in (
            ("REALM", "other"),
            ("ROLE_NAME", "other-role"),
            ("USER_ID", "00000000-0000-0000-0000-000000000000"),
            ("USER_NAME", "someone-else@e-dani.com"),
        ):
            result, journal, _ = self.run_reconciler("ensure", extra_env={var: value})
            self.assertNotEqual(0, result.returncode, f"{var} must be immutable")
            self.assertIn(f"{var} is immutable", result.stderr)
            self.assertNotIn("add-roles", journal)

    def test_unknown_mode_fails(self):
        result, _, _ = self.run_reconciler("ensure", extra_env={"MODE": "grant-everything"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("MODE must be ensure, audit, or rollback", result.stderr)


SCRIPT = SCRIPT


class WriteGrantDanielStaticTest(BootstrapSourceContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT
    def test_script_pins_the_reviewed_identity(self):
        script = SCRIPT.read_text()
        self.assertIn(f'REALM="${{REALM:-edani}}"', script)
        self.assertIn(f'ROLE_NAME="${{ROLE_NAME:-{ROLE}}}"', script)
        self.assertIn(f'USER_ID="${{USER_ID:-{SUBJECT}}}"', script)
        self.assertIn(f'USER_NAME="${{USER_NAME:-{USERNAME}}}"', script)
        self.assertIn(f'[ "${{USER_ID}}" = "{SUBJECT}" ]', script)
        self.assertIn(f'[ "${{USER_NAME}}" = "{USERNAME}" ]', script)

    def test_script_never_mutates_users_or_the_role(self):
        code = hook_code(SCRIPT, COMMON)
        # Only add-roles / remove-roles touch the realm, and only for the
        # pinned uid and role: no create, update or delete of any resource.
        self.assertNotIn('"${KCADM}" create', code)
        self.assertNotIn('"${KCADM}" update', code)
        self.assertNotIn('"${KCADM}" delete', code)
        self.assertNotIn('"${KCADM}" set', code)
        self.assertIn('"${KCADM}" add-roles', code)
        self.assertIn('"${KCADM}" remove-roles', code)

    def test_script_is_redacted(self):
        code = hook_code(SCRIPT, COMMON)
        self.assertNotIn("set -x", code)
        self.assertNotIn('echo "${KC_BOOTSTRAP_ADMIN_PASSWORD}"', code)
        self.assertNotIn('printf \'%s\\n\' "${KC_BOOTSTRAP_ADMIN_PASSWORD}"', code)

    def test_job_is_postsync_wave25_nonroot_pinned_and_tokenless(self):
        manifest = JOB.read_text()
        assert_job_hardened(self, manifest)
        self.assertIn(f"value: {ROLE}", manifest)
        self.assertIn(f"value: {SUBJECT}", manifest)
        self.assertIn(f"value: {USERNAME}", manifest)
        self.assertNotIn("KC_BOOTSTRAP_ADMIN_PASSWORD\n              value:", manifest)

    def test_wired_into_kustomize_and_rollback_is_manual(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("agentgateway-write-grant-daniel-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-write-grant-daniel.sh", kustomization)
        self.assertIn("kc-admin-common.sh=scripts/kc-admin-common.sh", kustomization)
        self.assertNotIn(
            "manual/agentgateway-write-grant-daniel-rollback-job.yaml", kustomization
        )
        rollback = ROLLBACK_JOB.read_text()
        self.assertIn("value: rollback", rollback)
        self.assertIn(f"value: {SUBJECT}", rollback)
        self.assertIn(f"value: {ROLE}", rollback)
        self.assertIn("backoffLimit: 0", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    def test_catalog_and_principals_declare_the_grant(self):
        catalog = json.loads((BASE / "ROLES.yaml").read_text())
        entry = next(r for r in catalog["roles"] if r["name"] == ROLE)
        self.assertEqual(entry["grantees"], sorted([USERNAME, FIXTURE, SA]))
        self.assertIn("OWU-80", entry["origin"])
        self.assertIn("OWU-80", entry["privilege"]["denies"])
        principals_text = (BASE / "PRINCIPALS.md").read_text()
        block = re.search(r"```json\n(.*?)\n```", principals_text, re.S).group(1)
        principals = json.loads(block)
        entry = next(
            p for p in principals["principals"] if p["username"] == USERNAME
        )
        self.assertIn(ROLE, entry["realm_roles"])
        self.assertEqual(entry["realm_roles"], sorted(entry["realm_roles"]))

    def test_write_role_hook_tolerates_exactly_this_human(self):
        script = (BASE / "scripts" / "agentgateway-write-role.sh").read_text()
        self.assertIn(f'HUMAN_GRANTEE_ID="${{HUMAN_GRANTEE_ID:-{SUBJECT}}}"', script)
        self.assertIn(
            f'HUMAN_GRANTEE_USERNAME="${{HUMAN_GRANTEE_USERNAME:-{USERNAME}}}"', script
        )
        self.assertIn(
            f'[ "${{HUMAN_GRANTEE_ID}}" = "{SUBJECT}" ]', script
        )
        # The tolerance is by subject id in the effective-role audit and by
        # pinned username in the direct-mapping audit; the role rollback
        # refuses to delete the role while the human grant exists.
        self.assertIn('[ "${user_id}" = "${HUMAN_GRANTEE_ID}" ]', script)
        self.assertIn('[ "${username}" = "${HUMAN_GRANTEE_USERNAME}" ]', script)
        self.assertIn("agentgateway-write-grant-daniel-rollback-job.yaml first", script)

    def test_documented_in_readme_runbook_and_ci(self):
        readme = (BASE / "README.md").read_text()
        self.assertIn("agentgateway-write-grant-daniel-job.yaml", readme)
        self.assertIn(SUBJECT, readme)
        self.assertIn("OWU-77", readme)
        runbook = (BASE / "RUNBOOK.md").read_text()
        self.assertIn("## 16. Human write grant", runbook)
        self.assertIn("agentgateway-write-grant-daniel-rollback-job.yaml", runbook)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("sh -n platform/keycloak-next/scripts/agentgateway-write-grant-daniel.sh", ci)
        self.assertIn("tests/test_agentgateway_write_grant_daniel_contract.py", ci)



if __name__ == "__main__":
    unittest.main()
