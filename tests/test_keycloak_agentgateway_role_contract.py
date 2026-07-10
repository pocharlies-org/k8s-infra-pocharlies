import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"


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

    def test_job_is_postsync_nonroot_pinned_and_tokenless(self):
        manifest = (BASE / "agentgateway-write-role-job.yaml").read_text()
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
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
        self.assertIn("automountServiceAccountToken: false", rollback)


if __name__ == "__main__":
    unittest.main()
