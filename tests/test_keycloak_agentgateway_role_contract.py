"""OWU-80 / OWU-28-g: the exclusivity hook (agentgateway-write-role.sh)
keeps its own contract here; the functional harness (fake kcadm + JWT maker)
comes from tests/keycloak_hook_testlib.py. The fixture-user tolerance tests
of OWU-28-g live in test_agentgateway_write_fixture_user_contract.py."""

import pathlib
import unittest

from keycloak_hook_testlib import BASE, ROOT, WRITE_ROLE_FAKE_KCADM, make_token, run_hook

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
        # audit accepts exactly the pinned username. Any other user still
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


class WriteRoleHookToleratesPinnedHumanTest(unittest.TestCase):
    """The SC-44 hook keeps running every sync; after OWU-80 it must pass with
    the human grant present, pass before it lands, still fail on any other
    holder, and its role rollback must refuse to run while the human holds."""

    def run_write_role(self, mode, fixtures=None):
        result, journal, _ = run_hook(
            BASE / "scripts" / "agentgateway-write-role.sh",
            WRITE_ROLE_FAKE_KCADM,
            mode=mode,
            flags=fixtures,
            extra_env={
                "FAKE_SUBJECT": SUBJECT,
                "FAKE_MCP_TOKEN": make_token(
                    [ROLE, "default-roles-edani"], "agentgateway-mcp"
                ),
            },
        )
        return result, journal

    def test_ensure_passes_with_the_human_grantee_present(self):
        result, journal = self.run_write_role("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"human_grantee_holds":true', result.stdout)
        # steady state: nothing to add, the SA already holds the role
        self.assertNotIn("add-roles", journal)

    def test_ensure_passes_before_the_grant_lands(self):
        # First sync after the merge: wave 20 runs before this grant hook's
        # wave 25, so the human is not a holder yet — tolerated, not required.
        result, _ = self.run_write_role("ensure", fixtures=["human_absent"])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"human_grantee_holds":false', result.stdout)

    def test_ensure_still_fails_on_any_other_holder(self):
        result, _ = self.run_write_role("ensure", fixtures=["intruder"])
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unauthorized user", result.stderr)

    def test_role_rollback_refuses_while_the_human_holds(self):
        result, journal = self.run_write_role("rollback")
        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "agentgateway-write-grant-daniel-rollback-job.yaml first", result.stderr
        )
        # Refused BEFORE any mutation: the SA grant and the role are intact.
        self.assertNotIn("remove-roles", journal)
        self.assertNotIn("delete", journal)


if __name__ == "__main__":
    unittest.main()
