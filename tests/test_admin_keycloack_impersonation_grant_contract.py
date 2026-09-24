import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"


class AdminKeycloackImpersonationGrantContractTest(unittest.TestCase):
    """SC-709 / SC-1215: the reconciler adds exactly one client-role mapping
    (impersonation of realm-management) to the admin-keycloack-server service
    account and is additive-only — it never enforces exclusivity, never creates
    or deletes the built-in role, and never touches other identities."""

    def test_reconciler_is_additive_and_redacted(self):
        script = (BASE / "scripts" / "admin-keycloack-impersonation-grant.sh").read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-admin-keycloack-server}"', script)
        self.assertIn('MAPPING_CLIENT="${MAPPING_CLIENT:-realm-management}"', script)
        self.assertIn('ROLE_NAME="${ROLE_NAME:-impersonation}"', script)
        self.assertIn('service-account-${CLIENT_ID}', script)
        # Canonical REST collection with fully-resolved uuids (no --in-client).
        self.assertIn(
            'users/${SERVICE_ACCOUNT_ID}/role-mappings/clients/${MAPPING_CLIENT_UUID}/roles',
            script,
        )
        # Raw REST, never the version-sensitive "kcadm add-roles --in-client".
        # Checked against executable code only: the header comment names the
        # flag precisely to explain why it is avoided.
        code = "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn('add-roles', code)
        # The built-in role is only read; a missing one fails closed.
        self.assertIn('clients/${MAPPING_CLIENT_UUID}/roles/${ROLE_NAME}', script)
        self.assertIn('refusing to create an IdP built-in', script)
        self.assertIn('MODE must be ensure, audit, or rollback', script)
        self.assertNotIn('set -x', script)
        self.assertNotIn('echo "${KC_BOOTSTRAP_ADMIN_PASSWORD}"', script)

    def test_reconciler_does_not_enforce_exclusivity_or_touch_the_role(self):
        script = (BASE / "scripts" / "admin-keycloack-impersonation-grant.sh").read_text()
        # Additive-only: no exclusivity auditing copied from write-role.
        self.assertNotIn('assert_effective_role_exclusivity', script)
        self.assertNotIn('another service account', script)
        # Never deletes the built-in role itself (only the user's mapping list).
        self.assertNotIn('delete "roles', script)
        self.assertNotIn('delete "clients/${MAPPING_CLIENT_UUID}/roles"', script)

    def test_job_is_postsync_nonroot_pinned_and_tokenless(self):
        manifest = (BASE / "admin-keycloack-impersonation-grant-job.yaml").read_text()
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn("capabilities:\n              drop: [\"ALL\"]", manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertIn("name: keycloak-bootstrap", manifest)
        self.assertIn("value: admin-keycloack-server", manifest)
        self.assertIn("value: realm-management", manifest)
        self.assertIn("value: impersonation", manifest)
        self.assertNotIn("KC_BOOTSTRAP_ADMIN_PASSWORD\n              value:", manifest)

    def test_wired_into_argo_and_rollback_is_manual(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "admin-keycloack-impersonation-grant-rollback-job.yaml").read_text()
        self.assertIn("admin-keycloack-impersonation-grant-job.yaml", kustomization)
        self.assertIn("scripts/admin-keycloack-impersonation-grant.sh", kustomization)
        self.assertNotIn("manual/admin-keycloack-impersonation-grant-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)


if __name__ == "__main__":
    unittest.main()
