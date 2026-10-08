import functools, pathlib, shutil, subprocess, sys, unittest

# The CI calls `python3 -m unittest tests/test_x.py` by path, so tests/ is not on sys.path.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from kcadm_fake import run_reconciler  # noqa: E402


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "jarvis-echo-client.sh"
LIB = BASE / "scripts" / "keycloak-reconcile-lib.sh"

REVIEWED_ROLE = "agentgateway-read:workspace"

# The stateful kcadm stand-in (fake state, call journal, minted-token semantics measured
# live in INFRA-44) is shared with the hermes-enviar test: tests/kcadm_fake.py.
_run = functools.partial(run_reconciler, SCRIPT, "jarvis-echo")


def _state(role_present=True, client=None):
    state = {"clients": {}, "roles": {}}
    if role_present:
        state["roles"][REVIEWED_ROLE] = {"id": "role-workspace", "composite": False}
    if client is not None:
        state["clients"]["jarvis-echo"] = client
    return state


def _existing_client(**extra):
    # The state measured live on 2026-10-04, the day INFRA-477 opened: the
    # hand-created client with fullScopeAllowed STILL TRUE, the reviewed grant
    # in place and an EMPTY client role scope (the role travelled through the
    # flag alone).
    client = {
        "clientId": "jarvis-echo", "enabled": "true", "publicClient": "false",
        "standardFlowEnabled": "false", "directAccessGrantsEnabled": "false",
        "serviceAccountsEnabled": "true", "fullScopeAllowed": "true",
        "secret": "generated-jarvis-echo",
        "sa_roles": [REVIEWED_ROLE, "default-roles-edani"],
        "scope_roles": [],
        "mappers": {"m1": {"name": "aud-mcp", "audience": "mcp.lan.e-dani.com"}},
    }
    client.update(extra)
    return client


def _converged_client(**extra):
    client = _existing_client()
    client.update(fullScopeAllowed="false", scope_roles=[REVIEWED_ROLE])
    client.update(extra)
    return client


class JarvisEchoIdentityContractTest(unittest.TestCase):
    def test_reconciler_is_fixed_scope_and_never_touches_the_secret(self):
        script = SCRIPT.read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-jarvis-echo}"', script)
        self.assertIn('READ_ROLE_NAME="${READ_ROLE_NAME:-agentgateway-read:workspace}"', script)
        self.assertIn('EXPECTED_READ_ROLE_NAME="agentgateway-read:workspace"', script)
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', script)
        self.assertIn('MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"', script)
        self.assertIn("unsupported immutable client", script)
        self.assertIn("READ_ROLE_NAME is immutable", script)
        self.assertIn("serviceAccountsEnabled=true", script)
        self.assertIn("standardFlowEnabled=false", script)
        self.assertIn("directAccessGrantsEnabled=false", script)
        # INFRA-477: the mechanical helpers (audience mapper upsert, mint,
        # login) live in the shared reconcile library; the reconciler sources
        # it and keeps only policy here.
        self.assertIn('. "$(dirname "$0")/keycloak-reconcile-lib.sh"', script)
        self.assertIn("oidc-audience-mapper", LIB.read_text())
        # The role is owned by the read-grants hook: never created or deleted
        # here, and the reconciler refuses to run without it.
        self.assertIn("the agentgateway-read-grants hook owns it", script)
        self.assertNotIn("create roles", script)
        self.assertNotIn('delete "roles/', script)
        self.assertNotIn("delete roles", script)
        # The secret is never written: neither branch of the upsert carries a
        # secret field, and the mint only reads it through the admin API.
        self.assertNotIn("-s secret=", script)
        self.assertIn('client_secret_via_admin "${CLIENT_UUID}"', script)
        self.assertIn('"clients/$1/client-secret"', LIB.read_text())
        self.assertIn("check_exact_token", script)
        self.assertIn("restored to true and confirmed", script)
        self.assertIn("manual intervention required", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${client_secret}"', script)
        self.assertNotIn('echo "${token}"', script)

    def test_guards_are_immutable_before_any_call(self):
        result, calls, _ = _run("ensure", _state(), {"CLIENT_ID": "jarvis-echo-2"})
        self.assertEqual(1, result.returncode)
        self.assertIn("unsupported immutable client", result.stderr)
        self.assertEqual([], calls)
        result, calls, _ = _run(
            "ensure", _state(), {"READ_ROLE_NAME": "agentgateway-read:gsc"}
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("READ_ROLE_NAME is immutable", result.stderr)
        self.assertEqual([], calls)

    def test_ensure_adopts_the_live_hand_created_client(self):
        # The INFRA-477 adoption path: the client exists with the flag true
        # and an empty scope. Ensure maps the role into the client role scope,
        # flips fullScopeAllowed=false only afterwards, and verifies the
        # exact token. The upsert update itself must not carry the flag.
        result, calls, state = _run("ensure", _state(client=_existing_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_id":"jarvis-echo","realm_role":"agentgateway-read:workspace","present":true', result.stdout)
        self.assertIn('"fullscope_allowed":false,"token_verified":true', result.stdout)
        updates = [c for c in calls if c.startswith("update clients/uuid-jarvis-echo ")]
        self.assertTrue(updates)
        self.assertFalse(any("fullScopeAllowed=false" in c for c in updates[:1]), updates)
        self.assertTrue(any("fullScopeAllowed=false" in c for c in updates), updates)
        self.assertFalse(any(c.startswith("create clients ") for c in calls))
        self.assertFalse(any(c.startswith("add-roles ") for c in calls))
        self.assertTrue(any(c.startswith("create clients/uuid-jarvis-echo/scope-mappings/realm") for c in calls))
        self.assertFalse(any(c.startswith("create roles") for c in calls))
        client = state["clients"]["jarvis-echo"]
        self.assertEqual("false", client["fullScopeAllowed"])
        self.assertEqual([REVIEWED_ROLE], client["scope_roles"])
        self.assertEqual([REVIEWED_ROLE, "default-roles-edani"], client["sa_roles"])

    def test_ensure_creates_the_client_on_a_fresh_realm(self):
        result, calls, state = _run("ensure", _state())
        self.assertEqual(0, result.returncode, result.stderr)
        creates = [c for c in calls if c.startswith("create clients ") and "clientId=jarvis-echo" in c]
        self.assertEqual(1, len(creates))
        self.assertIn("fullScopeAllowed=false", creates[0])
        self.assertTrue(any(c.startswith("add-roles ") and f"--rolename {REVIEWED_ROLE}" in c for c in calls))
        client = state["clients"]["jarvis-echo"]
        self.assertEqual([REVIEWED_ROLE], client["sa_roles"])
        self.assertEqual([REVIEWED_ROLE], client["scope_roles"])

    def test_ensure_is_idempotent_on_a_converged_client(self):
        result, calls, state = _run("ensure", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(any(c.startswith("create clients ") for c in calls))
        self.assertFalse(any(c.startswith("add-roles") for c in calls))
        self.assertFalse(any(c.startswith("create clients/uuid-jarvis-echo/scope-mappings") for c in calls))
        # Steady state: the owned flag is already false, so no update may
        # touch it (INFRA-45 discipline: an idempotent run flips nothing).
        self.assertFalse(any("fullScopeAllowed" in c for c in calls if c.startswith("update ")))
        self.assertEqual("false", state["clients"]["jarvis-echo"]["fullScopeAllowed"])

    def test_ensure_refuses_to_run_before_the_read_role_exists(self):
        result, calls, state = _run("ensure", _state(role_present=False))
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-read:workspace is missing; the agentgateway-read-grants hook owns it", result.stderr)
        self.assertFalse(any(c.startswith("create") for c in calls))
        self.assertEqual({}, state["clients"])

    def test_ensure_fails_when_the_service_account_holds_a_write_role(self):
        # INFRA-477: security approved read-only calendar access. The
        # umbrella role and any write domain fail closed.
        for extra in ("agentgateway-write", "agentgateway-write:workspace"):
            client = _converged_client(sa_roles=[REVIEWED_ROLE, "default-roles-edani", extra])
            result, _, _ = _run("ensure", _state(client=client))
            self.assertEqual(1, result.returncode, extra)
            self.assertIn(f"unreviewed AgentGateway role: {extra}", result.stderr)

    def test_ensure_fails_when_the_service_account_holds_a_sibling_read_role(self):
        client = _converged_client(sa_roles=[REVIEWED_ROLE, "agentgateway-read:gsc", "default-roles-edani"])
        result, _, _ = _run("ensure", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("unreviewed AgentGateway role: agentgateway-read:gsc", result.stderr)

    def test_post_flip_off_matrix_token_restores_fullscope_and_aborts(self):
        # The flip is the live step: if the token with the flag off is
        # off-matrix, the flag goes back to true (read-back + confirmation
        # mint) before the abort, so the Alexa skill never loses its token.
        result, calls, state = _run(
            "ensure", _state(client=_existing_client()),
            {"FAKE_FORCE_BAD_OFF_TOKEN": "1"},
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("restored to true and confirmed", result.stderr)
        self.assertEqual("true", state["clients"]["jarvis-echo"]["fullScopeAllowed"])
        self.assertTrue(any(c.startswith("update clients/uuid-jarvis-echo ") and "fullScopeAllowed=true" in c for c in calls))

    def test_steady_state_off_matrix_token_fails_without_mutation(self):
        # Flag already false and the minted token is off-matrix: that is
        # drift or an attack, not a flip candidate — the flag is owned
        # steady state and must not be touched (INFRA-45 discipline).
        result, calls, _ = _run(
            "ensure", _state(client=_converged_client()),
            {"FAKE_FORCE_BAD_OFF_TOKEN": "1"},
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("flag unchanged by this run", result.stderr)
        self.assertFalse(any("fullScopeAllowed" in c for c in calls if c.startswith("update ")))

    def test_extra_scope_mapping_fails_closed_before_the_live_flip(self):
        # A second role mapped into the client scope widens the reviewed
        # matrix the moment the service account is granted it: fail closed,
        # additive reconciliation never removes and never flips.
        client = _converged_client(scope_roles=[REVIEWED_ROLE, "agentgateway-write"])
        result, calls, _ = _run("ensure", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("scope has unexpected role agentgateway-write; it widens the reviewed matrix", result.stderr)
        self.assertFalse(any("fullScopeAllowed" in c for c in calls if c.startswith("update ")))
        self.assertFalse(any(c.startswith("add-roles") for c in calls))

    def test_missing_scope_mapping_is_repaired_not_fatal(self):
        # The empty scope of the hand-created client (measured 2026-10-04)
        # is drift this hook repairs by ADDING the reviewed role, then
        # converges the flag.
        client = _converged_client(scope_roles=[])
        result, calls, state = _run("ensure", _state(client=client))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(c.startswith("create clients/uuid-jarvis-echo/scope-mappings/realm") for c in calls))
        self.assertEqual([REVIEWED_ROLE], state["clients"]["jarvis-echo"]["scope_roles"])

    def test_audit_passes_on_the_converged_client(self):
        result, calls, _ = _run("audit", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"token_verified":true', result.stdout)
        self.assertFalse(any(c.startswith("create") or c.startswith("update") or c.startswith("add-roles") for c in calls))

    def test_audit_fails_when_the_service_account_is_missing_the_role(self):
        client = _converged_client(sa_roles=["default-roles-edani"])
        result, _, _ = _run("audit", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("direct realm role missing: agentgateway-read:workspace", result.stderr)

    def test_rollback_deletes_the_client_and_retains_the_role(self):
        result, calls, state = _run("rollback", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_present":false,"role_retained":true', result.stdout)
        self.assertTrue(any(c.startswith("delete clients/uuid-jarvis-echo ") for c in calls))
        self.assertFalse(any(c.startswith("delete roles") for c in calls))
        self.assertIn(REVIEWED_ROLE, state["roles"])
        self.assertEqual({}, state["clients"])

    def test_manifest_is_a_hardened_postsync_without_external_secret(self):
        manifest = (BASE / "jarvis-echo-client.yaml").read_text()
        # Unlike chat-agentgateway-client.yaml: no ExternalSecret, no
        # 1Password reference — the secret is not managed here and the hook
        # must never block on an unseeded secretKeyRef (INFRA-477).
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("onepassword", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("argocd.argoproj.io/hook-delete-policy: BeforeHookCreation", manifest)
        self.assertIn('argocd.argoproj.io/sync-wave: "24"', manifest)
        self.assertIn("name: CLIENT_ID, value: jarvis-echo", manifest)
        self.assertIn("name: READ_ROLE_NAME, value: agentgateway-read:workspace", manifest)
        self.assertIn('name: MAPPER_NAME, value: aud-mcp', manifest)
        self.assertIn('synapse.e-dani.com/agentgateway-m2m-client: "true"', manifest)
        self.assertIn("activeDeadlineSeconds: 1800", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertNotIn("CLIENT_SECRET", manifest)

    def test_kustomization_owns_job_and_script_and_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "jarvis-echo-client-rollback-job.yaml").read_text()
        self.assertIn("jarvis-echo-client.yaml", kustomization)
        self.assertIn("scripts/jarvis-echo-client.sh", kustomization)
        self.assertNotIn("manual/jarvis-echo-client-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)
        # INFRA-477 consistency: the rollback job pins the URL like the sync job.
        self.assertIn("KEYCLOAK_URL", rollback)

    def test_reconcile_library_is_mounted_for_every_reconciler_that_sources_it(self):
        # A sourced helper that is not in the ConfigMap would break the
        # PostSync hook at runtime, so every entrypoint that loads the library
        # must ship it in its own ConfigMap generator.
        kustomization = (BASE / "kustomization.yaml").read_text()
        for generator in (
            "keycloak-agentgateway-domain-roles",
            "keycloak-chat-agentgateway-client",
            "keycloak-agentgateway-chat-mcp-client",
            "keycloak-jarvis-echo-client",
        ):
            block = kustomization.split("name: " + generator, 1)[1].split("  - name:", 1)[0]
            self.assertIn("keycloak-reconcile-lib.sh=scripts/keycloak-reconcile-lib.sh", block, generator)
        for name in (
            "agentgateway-domain-roles.sh",
            "chat-agentgateway-client.sh",
            "agentgateway-chat-mcp-client.sh",
            "jarvis-echo-client.sh",
        ):
            script = (BASE / "scripts" / name).read_text()
            self.assertIn('. "$(dirname "$0")/keycloak-reconcile-lib.sh"', script, name)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(
            ["kubectl", "kustomize", str(BASE)],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("keycloak-jarvis-echo-client", result.stdout)
        # The library must survive into the built ConfigMaps, not just the
        # generator list: four data keys (domain-roles, chat, chat-mcp, jarvis).
        self.assertGreaterEqual(result.stdout.count("keycloak-reconcile-lib.sh: |"), 4)


if __name__ == "__main__":
    unittest.main()
