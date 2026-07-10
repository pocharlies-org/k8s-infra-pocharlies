import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"


class OpenClawReadonlyIdentityContractTest(unittest.TestCase):
    def test_clients_are_dedicated_fail_closed_and_never_log_credentials(self):
        script = (BASE / "scripts" / "openclaw-readonly-clients.sh").read_text()
        self.assertIn('UI_CLIENT_ID="${UI_CLIENT_ID:-openclaw-readonly-ui}"', script)
        self.assertIn(
            'AGENTGATEWAY_CLIENT_ID="${AGENTGATEWAY_CLIENT_ID:-openclaw-readonly-agentgateway}"',
            script,
        )
        self.assertIn('OPERATOR_EMAIL="${OPERATOR_EMAIL:-info@e-dani.com}"', script)
        self.assertIn('FORBIDDEN_REALM_ROLE="${FORBIDDEN_REALM_ROLE:-agentgateway-write}"', script)
        self.assertIn("standardFlowEnabled=true", script)
        self.assertIn("serviceAccountsEnabled=false", script)
        self.assertIn("standardFlowEnabled=false", script)
        self.assertIn("serviceAccountsEnabled=true", script)
        self.assertGreaterEqual(script.count("fullScopeAllowed=false"), 4)
        self.assertIn("oidc-group-membership-mapper", script)
        self.assertIn("oidc-audience-mapper", script)
        self.assertIn('config.\\"included.custom.audience\\"', script)
        self.assertIn("assert_no_forbidden_role", script)
        self.assertIn("verify_minted_claims", script)
        self.assertIn("mcp.lan.e-dani.com", script)
        self.assertIn("MODE", script)
        self.assertIn("rollback)", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${token}"', script)
        self.assertNotIn('echo "${OPENCLAW_READONLY_UI_CLIENT_SECRET}"', script)
        self.assertNotIn('echo "${OPENCLAW_READONLY_AGENTGATEWAY_CLIENT_SECRET}"', script)

    def test_external_secrets_and_postsync_job_are_least_privilege(self):
        manifest = (BASE / "openclaw-readonly-clients.yaml").read_text()
        self.assertEqual(manifest.count("kind: ExternalSecret"), 2)
        self.assertIn("name: openclaw-readonly-ui-secrets", manifest)
        self.assertIn("name: openclaw-readonly-agentgateway-bootstrap", manifest)
        self.assertIn("key: secret/keycloak-next/openclaw-readonly", manifest)
        self.assertIn("property: ui_client_secret", manifest)
        self.assertIn("property: cookie_secret", manifest)
        self.assertIn("property: agentgateway_client_secret", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("argocd.argoproj.io/sync-wave: \"21\"", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("node-pool: ks5-nvme", manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertNotIn("value: agentgateway-write\n            - name: OPENCLAW", manifest)

    def test_oauth_proxy_allows_only_info_and_forwards_no_bearer(self):
        manifest = (BASE / "oauth2-proxy-openclaw-readonly.yaml").read_text()
        self.assertIn("allowed-emails: |\n    info@e-dani.com", manifest)
        self.assertIn(
            'authenticated_emails_file = "/etc/oauth2-proxy/allowed-emails"', manifest
        )
        self.assertNotIn("email_domains =", manifest)
        self.assertIn('pass_access_token = false', manifest)
        self.assertIn('set_authorization_header = false', manifest)
        self.assertIn("authResponseHeaders:\n      - X-Auth-Request-Email\n      - X-Auth-Request-Groups", manifest)
        self.assertNotIn("authResponseHeaders:\n      - Authorization", manifest)
        self.assertIn("name: sso-openclaw-readonly-chain", manifest)
        self.assertIn("name: oauth2-proxy-openclaw-readonly", manifest)
        self.assertIn("replicas: 2", manifest)
        self.assertIn("minAvailable: 1", manifest)
        self.assertIn("preferredDuringSchedulingIgnoredDuringExecution", manifest)
        self.assertIn("topologyKey: kubernetes.io/hostname", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("node-pool: ks5-nvme", manifest)
        self.assertIn("oauth2-proxy:v7.15.2@sha256:", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn("cidr: 100.107.21.89/32", manifest)
        self.assertNotIn("cidr: 10.42.0.0/24", manifest)

    def test_kustomize_wires_reconciler_but_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "openclaw-readonly-clients-rollback-job.yaml").read_text()
        self.assertIn("oauth2-proxy-openclaw-readonly.yaml", kustomization)
        self.assertIn("openclaw-readonly-clients.yaml", kustomization)
        self.assertIn("scripts/openclaw-readonly-clients.sh", kustomization)
        self.assertNotIn("manual/openclaw-readonly-clients-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)
        self.assertIn("node-pool: ks5-nvme", rollback)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(
            ["kubectl", "kustomize", str(BASE)],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("keycloak-openclaw-readonly-clients", result.stdout)
        self.assertIn("oauth2-proxy-openclaw-readonly", result.stdout)


if __name__ == "__main__":
    unittest.main()
