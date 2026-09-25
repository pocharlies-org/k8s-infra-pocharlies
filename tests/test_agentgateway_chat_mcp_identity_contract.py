import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"


class AgentGatewayChatMcpIdentityContractTest(unittest.TestCase):
    def test_reconciler_is_a_public_pkce_client_only(self):
        script = (BASE / "scripts" / "agentgateway-chat-mcp-client.sh").read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-agentgateway-chat-mcp}"', script)
        self.assertIn('REALM="${REALM:-edani}"', script)
        self.assertIn('MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"', script)
        self.assertIn('PKCE_METHOD="${PKCE_METHOD:-S256}"', script)
        # The chat client is shared by every /chat-* route: redirect URIs are a
        # space-separated list of EXACT URIs (Open WebUI derives the callback
        # from the connection id), and the reconciler refuses wildcards and any
        # foreign origin outright.
        self.assertIn(
            'REDIRECT_URIS="${REDIRECT_URIS:-https://chat.e-dani.com/oauth/clients/mcp:chat-atlassian/callback}"',
            script,
        )
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', script)
        self.assertIn('RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"', script)
        self.assertIn("unsupported reconcile contract version", script)
        self.assertIn("wildcard URI", script)
        self.assertIn("non-exact or foreign URI", script)
        # public browser client: auth-code + PKCE only, no secret, no service
        # account, no direct access, no implicit, no realm scope.
        self.assertIn("publicClient=true", script)
        self.assertIn("standardFlowEnabled=true", script)
        self.assertIn("directAccessGrantsEnabled=false", script)
        self.assertIn("implicitFlowEnabled=false", script)
        self.assertIn("serviceAccountsEnabled=false", script)
        self.assertIn("fullScopeAllowed=false", script)
        self.assertIn('attributes.\\"pkce.code.challenge.method\\"', script)
        # Regression (SC-600): verify_client must read the client with
        # --format json and match key and value paired.
        # Regression (INFRA-197, measured 2026-09-21): kcadm serializes map
        # fields like `attributes` EMPTY when selected through --fields
        # ({"attributes": {}} even when the attribute is set server-side), so
        # the read must NOT pass --fields — the full JSON carries the map.
        self.assertIn('kget "clients/${CLIENT_UUID}" --format json', script)
        self.assertNotIn("--fields attributes", script)
        self.assertIn('pkce\\.code\\.challenge\\.method', script)
        self.assertIn("oidc-audience-mapper", script)
        self.assertIn('config.\\"included.custom.audience\\"', script)
        self.assertIn('config."access.token.claim"=true', script)
        self.assertIn('config."id.token.claim"=false', script)
        self.assertIn('config."introspection.token.claim"=true', script)
        self.assertIn('config."userinfo.token.claim"=false', script)
        # every configured redirect URI is asserted after the ensure (fail-loud,
        # SC-600 lesson: the hook validates from day one)
        self.assertIn("client redirect URI ${uri} is missing", script)
        # a public client has no secret to mint or verify against
        self.assertNotIn("CLIENT_SECRET", script)
        self.assertIn("rollback_identity", script)
        self.assertNotIn("set -x", script)

    def test_manifest_is_a_hardened_postsync_job_with_no_secret(self):
        manifest = (BASE / "agentgateway-chat-mcp-client.yaml").read_text()
        # public client: no ExternalSecret and no client secret material
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("client_secret", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        # wave 23: after the client reconcilers (21/22), before nothing — no
        # sync-time dependent exists for this client (the /chat-* routes
        # reference it at runtime, not at apply time).
        self.assertIn('argocd.argoproj.io/sync-wave: "23"', manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn('agentgateway.e-dani.com/reconcile-contract-version: "1"', manifest)
        self.assertIn("name: CLIENT_ID, value: agentgateway-chat-mcp", manifest)
        self.assertIn(
            'name: REDIRECT_URIS, value: "https://chat.e-dani.com/oauth/clients/mcp:chat-atlassian/callback"',
            manifest,
        )
        self.assertIn("name: MAPPER_NAME, value: aud-mcp", manifest)
        self.assertIn("name: PKCE_METHOD, value: S256", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        # the job's own netpol is selected by the job's pod label
        self.assertIn('agentgateway.e-dani.com/chat-mcp-client: "true"', manifest)

    def test_kustomization_includes_reconciler_and_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "agentgateway-chat-mcp-client-rollback-job.yaml").read_text()
        self.assertIn("agentgateway-chat-mcp-client.yaml", kustomization)
        self.assertIn("scripts/agentgateway-chat-mcp-client.sh", kustomization)
        self.assertNotIn("manual/agentgateway-chat-mcp-client-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)


if __name__ == "__main__":
    unittest.main()
