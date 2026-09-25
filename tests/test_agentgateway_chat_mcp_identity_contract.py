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
        # account, no direct access, no implicit; realm roles only through the
        # explicit reviewed scope mapping below (fullScopeAllowed stays false).
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

    def test_realm_scope_mapping_emits_the_reviewed_write_role(self):
        # OWU-28 C2 (security nota-security-c2-token.md, 2026-09-25): the
        # gateway's write rules on /chat-atlassian require
        # "agentgateway-write" in jwt.realm_access.roles, and with
        # fullScopeAllowed=false Keycloak 26 emits only realm roles mapped
        # into the client's realm scope. The blocker was this client's empty
        # scope mapping; the fix maps EXACTLY the reviewed set, house pattern
        # of chat-agentgateway-client.sh / agentgateway-read-grants.sh.
        script = (BASE / "scripts" / "agentgateway-chat-mcp-client.sh").read_text()
        self.assertIn(
            'REALM_SCOPE_ROLE_NAMES="${REALM_SCOPE_ROLE_NAMES:-agentgateway-write}"',
            script,
        )
        self.assertIn('EXPECTED_REALM_SCOPE_ROLE_NAMES="agentgateway-write"', script)
        self.assertIn("REALM_SCOPE_ROLE_NAMES is immutable", script)
        self.assertIn('kget "clients/${CLIENT_UUID}/scope-mappings/realm"', script)
        self.assertIn('create "clients/${CLIENT_UUID}/scope-mappings/realm"', script)
        # fail-loud on both the post-create re-read and the post-ensure/audit
        # verification, and never create the role itself: it belongs to
        # agentgateway-write-role.sh.
        self.assertIn("client role scope is missing ${role}", script)
        self.assertIn("client realm scope mapping is missing ${role}", script)
        self.assertIn("the agentgateway-write-role hook owns it", script)
        # the old letter claimed this client emitted no realm role at all —
        # that WAS the C2 blocker and must not come back
        self.assertNotIn("no realm role", script)
        # fullScopeAllowed must STAY false: the explicit mapping replaces the
        # umbrella, it never joins it
        self.assertIn("fullScopeAllowed=false", script)

    def test_manifest_pins_the_realm_scope_env(self):
        manifest = (BASE / "agentgateway-chat-mcp-client.yaml").read_text()
        self.assertIn(
            "{ name: REALM_SCOPE_ROLE_NAMES, value: agentgateway-write }", manifest
        )

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
