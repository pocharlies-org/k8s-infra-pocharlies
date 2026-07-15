import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"


class SynapseSreIdentityContractTest(unittest.TestCase):
    def test_reconciler_is_fixed_scope_and_verifies_minted_claims(self):
        script = (BASE / "scripts" / "synapse-sre-client.sh").read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-synapse-sre-orchestrator}"', script)
        self.assertIn('ROLE_NAME="${ROLE_NAME:-synapse-sre-m2m}"', script)
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', script)
        self.assertIn('FORBIDDEN_REALM_ROLE="${FORBIDDEN_REALM_ROLE:-agentgateway-write}"', script)
        self.assertIn('RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"', script)
        self.assertIn("synapse-draft-orchestrator:synapse-draft-m2m", script)
        self.assertIn('CLIENT_SECRET="${SYNAPSE_DRAFT_CLIENT_SECRET:-}"', script)
        self.assertIn("unsupported reconcile contract version", script)
        self.assertIn("serviceAccountsEnabled=true", script)
        self.assertIn("standardFlowEnabled=false", script)
        self.assertIn("directAccessGrantsEnabled=false", script)
        self.assertIn("fullScopeAllowed=false", script)
        self.assertIn("oidc-audience-mapper", script)
        self.assertIn('"clients/${CLIENT_UUID}/scope-mappings/realm"', script)
        self.assertIn("ensure_role_scope_mapping", script)
        self.assertIn("progress role-scope-verified", script)
        self.assertIn('"roles/${ROLE_NAME}/users" -q first=0 -q max=2', script)
        self.assertIn('"roles/${ROLE_NAME}/groups" -q first=0 -q max=2', script)
        self.assertNotIn("kget users -q max=1000", script)
        self.assertIn("progress role-mapping-verified", script)
        self.assertIn("verify_minted_claims", script)
        self.assertIn("rollback_identity", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${SYNAPSE_SRE_CLIENT_SECRET}"', script)
        self.assertNotIn('echo "${token}"', script)

    def test_manifest_uses_one_vault_property_and_a_hardened_postsync_job(self):
        manifest = (BASE / "synapse-sre-client.yaml").read_text()
        self.assertEqual(manifest.count("kind: ExternalSecret"), 2)
        self.assertIn("key: secret/agentgateway/prod", manifest)
        self.assertIn("property: synapse_sre_orchestrator_client_secret", manifest)
        self.assertIn("property: synapse_draft_orchestrator_client_secret", manifest)
        self.assertIn("name: CLIENT_ID, value: synapse-draft-orchestrator", manifest)
        self.assertIn("name: ROLE_NAME, value: synapse-draft-m2m", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertEqual(manifest.count("activeDeadlineSeconds: 900"), 2)
        self.assertIn('argocd.argoproj.io/sync-wave: "22"', manifest)
        self.assertIn('synapse.e-dani.com/reconcile-contract-version: "1"', manifest)
        self.assertIn('name: RECONCILE_CONTRACT_VERSION, value: "1"', manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertNotIn("agentgateway-write\n", manifest)

    def test_kustomization_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "synapse-sre-client-rollback-job.yaml").read_text()
        self.assertIn("synapse-sre-client.yaml", kustomization)
        self.assertIn("scripts/synapse-sre-client.sh", kustomization)
        self.assertNotIn("manual/synapse-sre-client-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertNotIn("SYNAPSE_SRE_CLIENT_SECRET", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(
            ["kubectl", "kustomize", str(BASE)],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("keycloak-synapse-sre-client", result.stdout)
        self.assertIn("synapse-sre-keycloak-bootstrap", result.stdout)
        self.assertIn("keycloak-synapse-draft-client", result.stdout)
        self.assertIn("synapse-draft-keycloak-bootstrap", result.stdout)


if __name__ == "__main__":
    unittest.main()
