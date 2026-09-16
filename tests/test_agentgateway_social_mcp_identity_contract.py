import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"


class AgentGatewaySocialMcpIdentityContractTest(unittest.TestCase):
    def test_reconciler_is_a_public_pkce_client_only(self):
        script = (BASE / "scripts" / "agentgateway-social-mcp-client.sh").read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-agentgateway-social-mcp}"', script)
        self.assertIn('REALM="${REALM:-edani}"', script)
        self.assertIn('MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"', script)
        self.assertIn('PKCE_METHOD="${PKCE_METHOD:-S256}"', script)
        self.assertIn(
            'REDIRECT_URI="${REDIRECT_URI:-https://chat.e-dani.com/oauth/clients/mcp:social/callback}"',
            script,
        )
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', script)
        self.assertIn('RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"', script)
        self.assertIn("unsupported reconcile contract version", script)
        # public browser client: auth-code + PKCE only, no secret, no service
        # account, no direct access, no implicit, no realm scope.
        self.assertIn("publicClient=true", script)
        self.assertIn("standardFlowEnabled=true", script)
        self.assertIn("directAccessGrantsEnabled=false", script)
        self.assertIn("implicitFlowEnabled=false", script)
        self.assertIn("serviceAccountsEnabled=false", script)
        self.assertIn("fullScopeAllowed=false", script)
        self.assertIn('attributes.\\"pkce.code.challenge.method\\"', script)
        # Regression (SC-600): kcadm's CSV output does not serialize map
        # fields like `attributes`, so verify_client must read the client
        # with --format json and match key and value paired.
        self.assertIn("--fields attributes --format json", script)
        self.assertIn('pkce\\.code\\.challenge\\.method', script)
        self.assertIn("oidc-audience-mapper", script)
        self.assertIn('config.\\"included.custom.audience\\"', script)
        self.assertIn('config."access.token.claim"=true', script)
        self.assertIn('config."id.token.claim"=false', script)
        self.assertIn('config."introspection.token.claim"=true', script)
        self.assertIn('config."userinfo.token.claim"=false', script)
        # a public client has no secret to mint or verify against
        self.assertNotIn("mint", script)
        self.assertNotIn("CLIENT_SECRET", script)
        self.assertIn("rollback_identity", script)
        self.assertNotIn("set -x", script)

    def test_manifest_is_a_hardened_postsync_job_with_no_secret(self):
        manifest = (BASE / "agentgateway-social-mcp-client.yaml").read_text()
        # public client: no ExternalSecret and no client secret material
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("client_secret", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn('argocd.argoproj.io/sync-wave: "22"', manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn('agentgateway.e-dani.com/reconcile-contract-version: "1"', manifest)
        self.assertIn("name: CLIENT_ID, value: agentgateway-social-mcp", manifest)
        self.assertIn("name: REDIRECT_URI, value: https://chat.e-dani.com/oauth/clients/mcp:social/callback", manifest)
        self.assertIn("name: MAPPER_NAME, value: aud-mcp", manifest)
        self.assertIn("name: PKCE_METHOD, value: S256", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)

    def test_kustomization_includes_reconciler_and_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "agentgateway-social-mcp-client-rollback-job.yaml").read_text()
        self.assertIn("agentgateway-social-mcp-client.yaml", kustomization)
        self.assertIn("scripts/agentgateway-social-mcp-client.sh", kustomization)
        self.assertNotIn("manual/agentgateway-social-mcp-client-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)
        self.assertNotIn("client_secret", rollback)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(
            ["kubectl", "kustomize", str(BASE)],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("keycloak-agentgateway-social-mcp-client", result.stdout)
        self.assertIn("agentgateway-social-mcp-client.sh", result.stdout)


if __name__ == "__main__":
    unittest.main()
