import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"

# The functional harness of the exclusivity hook (fake kcadm + JWT maker) is
# owned by the OWU-80 contract file; OWU-28-g extends that same control flow,
# so it reuses the harness instead of cloning the parse logic.
sys.path.insert(0, str(ROOT / "tests"))
from test_agentgateway_write_grant_daniel_contract import (  # noqa: E402
    WRITE_ROLE_FAKE_KCADM,
    make_token,
)

SUBJECT = "e51253a7-c137-4c6c-9fb9-af9cecd3b147"
FIXTURE = "qa-write-sin-vinculo@e-dani.com"
ROLE = "agentgateway-write"


class KeycloakAgentGatewayRoleContractTest(unittest.TestCase):
    def test_reconciler_is_exclusive_idempotent_and_redacted(self):
        script = (BASE / "scripts" / "agentgateway-write-role.sh").read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-agentgateway-mcp}"', script)
        self.assertIn('ROLE_NAME="${ROLE_NAME:-agentgateway-write}"', script)
        self.assertIn('roles/${ROLE_NAME}/users', script)
        self.assertIn('roles/${ROLE_NAME}/groups', script)
        self.assertIn('service-account-${CLIENT_ID}', script)
        self.assertIn('target_has_direct_role', script)
        self.assertIn('assert_effective_role_exclusivity', script)
        self.assertIn('non-service user', script)
        self.assertIn('another service account', script)
        self.assertIn('verify_token_claim_present', script)
        self.assertIn('verify_token_claim_absent', script)
        self.assertIn('exclusive_service_account', script)
        self.assertIn('MODE must be ensure, audit, or rollback', script)
        self.assertNotIn('set -x', script)
        self.assertNotIn('echo "${token}"', script)
        self.assertNotIn('echo "${client_secret}"', script)

    def test_owu80_tolerates_exactly_one_pinned_human_grantee(self):
        # SC-44 owned the role exclusively for the service account. OWU-80
        # (OWU-28 P6, security ruling nota-security-owu28.md (b)) extends the
        # reviewed holder set with EXACTLY ONE human, pinned by immutable
        # subject; the mapping itself is owned by
        # agentgateway-write-grant-daniel.sh.
        script = (BASE / "scripts" / "agentgateway-write-role.sh").read_text()
        self.assertIn(
            'HUMAN_GRANTEE_ID="${HUMAN_GRANTEE_ID:-e51253a7-c137-4c6c-9fb9-af9cecd3b147}"',
            script,
        )
        self.assertIn(
            'HUMAN_GRANTEE_USERNAME="${HUMAN_GRANTEE_USERNAME:-me@e-dani.com}"', script
        )
        self.assertIn(
            '[ "${HUMAN_GRANTEE_ID}" = "e51253a7-c137-4c6c-9fb9-af9cecd3b147" ]', script
        )
        self.assertIn('[ "${HUMAN_GRANTEE_USERNAME}" = "me@e-dani.com" ]', script)
        # Tolerance is per pinned identity only: the effective-role audit skips
        # the failure exactly for the pinned subject, and the direct-mapping
        # audit accepts exactly the pinned username. Any other holder still
        # hits the fail-closed messages.
        self.assertIn('[ "${user_id}" = "${HUMAN_GRANTEE_ID}" ]', script)
        self.assertIn('[ "${username}" = "${HUMAN_GRANTEE_USERNAME}" ]', script)
        self.assertIn('non-service user', script)
        self.assertIn('unauthorized user', script)
        # The role rollback cascades every holder: it must refuse BEFORE any
        # mutation while the human grant exists, pointing at the grant's own
        # manual rollback.
        self.assertIn('human_holds_direct_role', script)
        self.assertIn(
            'agentgateway-write-grant-daniel-rollback-job.yaml first', script
        )

    def test_job_is_postsync_nonroot_pinned_and_tokenless(self):
        manifest = (BASE / "agentgateway-write-role-job.yaml").read_text()
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn("capabilities:\n              drop: [\"ALL\"]", manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertIn("name: keycloak-bootstrap", manifest)
        self.assertNotIn("KC_BOOTSTRAP_ADMIN_PASSWORD\n              value:", manifest)

    def test_rollback_is_manual_and_not_reconciled_by_argo(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "agentgateway-write-role-rollback-job.yaml").read_text()
        self.assertIn("agentgateway-write-role-job.yaml", kustomization)
        self.assertIn("namespace: keycloak", kustomization)
        self.assertIn("scripts/agentgateway-write-role.sh", kustomization)
        self.assertNotIn("manual/agentgateway-write-role-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)


class WriteRoleHookToleratesFixtureUserTest(unittest.TestCase):
    """OWU-28 historia g: the exclusivity audit of the SC-44 hook tolerates a
    SECOND human, the QA fixture qa-write-sin-vinculo@e-dani.com, pinned by
    exact username (its id is minted by Keycloak). A third user still fails
    closed, and the role rollback refuses to run while the fixture mapping
    exists."""

    def run_write_role(self, mode, fixtures=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            state = tmp_path / "state"
            state.mkdir()
            journal = tmp_path / "journal"
            journal.touch()
            fake_kcadm = tmp_path / "kcadm.sh"
            fake_kcadm.write_text(WRITE_ROLE_FAKE_KCADM)
            fake_kcadm.chmod(0o755)
            for name in fixtures or ():
                (state / name).write_text("1")
            env = os.environ.copy()
            env.update(
                {
                    "MODE": mode,
                    "KCADM": str(fake_kcadm),
                    "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-a-real-secret",
                    "KEYCLOAK_URL": "http://keycloak.stub.invalid",
                    "FAKE_STATE": str(state),
                    "FAKE_JOURNAL": str(journal),
                    "FAKE_SUBJECT": SUBJECT,
                    "FAKE_MCP_TOKEN": make_token(
                        [ROLE, "default-roles-edani"], "agentgateway-mcp"
                    ),
                }
            )
            result = subprocess.run(
                ["/bin/sh", str(BASE / "scripts" / "agentgateway-write-role.sh")],
                capture_output=True,
                text=True,
                env=env,
            )
            return result, journal.read_text()

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
