"""INFRA-676 (P4b de INFRA-480): the hermes-enviar identity, declared by GitOps.

hermes-enviar is the confidential client of the Hermes `enviar` plugin: the
only identity that may send or delete a Gmail draft through AgentGateway
/workspace (agentgateway-write:workspace-envio), plus the read role the shim
needs to reach the route (agentgateway-read:workspace). Same family as
tests/test_jarvis_echo_identity_contract.py: the reconciler runs against a
stateful stand-in for kcadm, and the catalog files (ROLES.yaml, PRINCIPALS.md)
are checked by name, so the client cannot land without its catalog entries.
"""
import functools, importlib.util, pathlib, shutil, subprocess, sys, unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "hermes-enviar-client.sh"
LIB = BASE / "scripts" / "keycloak-reconcile-lib.sh"
SCRIPTS = BASE / "scripts"

# The CI calls `python3 -m unittest tests/test_x.py` by path, so tests/ is not on sys.path.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402
from kcadm_fake import run_reconciler  # noqa: E402

_spec = importlib.util.spec_from_file_location("verify_principals", SCRIPTS / "verify-principals.py")
verify_principals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_principals)

READ_ROLE = "agentgateway-read:workspace"
WRITE_ROLE = "agentgateway-write:workspace-envio"
BORRADOR_ROLE = "agentgateway-write:workspace-borrador"
REVIEWED_ROLES = [READ_ROLE, WRITE_ROLE]
SA_USERNAME = "service-account-hermes-enviar"

# The stateful kcadm stand-in (fake state, call journal, minted-token semantics measured
# live in INFRA-44, FAKE_FORCE_BAD_OFF_TOKEN / FAKE_TOKEN_EXTRA_ROLES) is shared with the
# jarvis-echo test: tests/kcadm_fake.py.
_run = functools.partial(run_reconciler, SCRIPT, "hermes-enviar")


def _state(read_present=True, write_present=True, client=None, write_users=(), write_groups=()):
    state = {"clients": {}, "roles": {}}
    if read_present:
        state["roles"][READ_ROLE] = {"id": "role-read", "composite": False}
    if write_present:
        state["roles"][WRITE_ROLE] = {
            "id": "role-envio", "composite": False,
            "users": list(write_users), "groups": list(write_groups)}
    if client is not None:
        state["clients"]["hermes-enviar"] = client
    return state


def _converged_client(**extra):
    client = {
        "clientId": "hermes-enviar", "enabled": "true", "publicClient": "false",
        "standardFlowEnabled": "false", "directAccessGrantsEnabled": "false",
        "implicitFlowEnabled": "false", "serviceAccountsEnabled": "true",
        "fullScopeAllowed": "false", "secret": "generated-hermes-enviar",
        "sa_roles": list(REVIEWED_ROLES) + ["default-roles-edani"],
        "scope_roles": list(REVIEWED_ROLES),
        "mappers": {"m1": {"name": "aud-mcp", "audience": "mcp.lan.e-dani.com"}},
    }
    client.update(extra)
    return client


class HermesEnviarReconcilerTest(unittest.TestCase):
    def test_reconciler_is_fixed_scope_and_never_touches_the_secret(self):
        script = SCRIPT.read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-hermes-enviar}"', script)
        self.assertIn('READ_ROLE_NAME="${READ_ROLE_NAME:-agentgateway-read:workspace}"', script)
        self.assertIn('WRITE_ROLE_NAME="${WRITE_ROLE_NAME:-agentgateway-write:workspace-envio}"', script)
        self.assertIn('EXPECTED_READ_ROLE_NAME="agentgateway-read:workspace"', script)
        self.assertIn('EXPECTED_WRITE_ROLE_NAME="agentgateway-write:workspace-envio"', script)
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', script)
        self.assertIn('MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"', script)
        self.assertIn("unsupported immutable client", script)
        self.assertIn("READ_ROLE_NAME is immutable", script)
        self.assertIn("WRITE_ROLE_NAME is immutable", script)
        # Service account only: no interactive flow, no redirect URI.
        self.assertIn("serviceAccountsEnabled=true", script)
        self.assertIn("standardFlowEnabled=false", script)
        self.assertIn("directAccessGrantsEnabled=false", script)
        self.assertIn("implicitFlowEnabled=false", script)
        self.assertNotIn("redirectUris", script)
        # Mechanical helpers (audience mapper upsert, mint, login) live in the
        # shared reconcile library; this file keeps only policy.
        self.assertIn('. "$(dirname "$0")/keycloak-reconcile-lib.sh"', script)
        self.assertIn("oidc-audience-mapper", LIB.read_text())
        # Mapping a role into the client scope is a library helper, not a copy
        # in the reconciler (the `duplicados` standard of the org).
        self.assertIn("ensure_role_in_client_scope()", LIB.read_text())
        self.assertIn('ensure_role_in_client_scope "${role}"', script)
        self.assertNotIn("scope-mappings/realm", script.replace('kget "clients/${CLIENT_UUID}/scope-mappings/realm"', ""))
        # Both roles are owned by other hooks: never created or deleted here,
        # and the reconciler refuses to run without them.
        self.assertIn("the agentgateway-read-grants hook owns it", script)
        self.assertIn("the agentgateway-domain-roles hook owns it", script)
        self.assertNotIn("create roles", script)
        self.assertNotIn('delete "roles/', script)
        self.assertNotIn("delete roles", script)
        # The secret is never written, rotated or printed: the hook only reads
        # it through the admin API to mint the verification token.
        self.assertNotIn("-s secret=", script)
        self.assertNotIn("client-secret --config", script)
        self.assertIn('client_secret_via_admin "${CLIENT_UUID}"', script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${client_secret}"', script)
        self.assertNotIn('echo "${token}"', script)

    def test_guards_are_immutable_before_any_call(self):
        for override, message in (
            ({"CLIENT_ID": "hermes-enviar-2"}, "unsupported immutable client"),
            ({"READ_ROLE_NAME": "agentgateway-read:gsc"}, "READ_ROLE_NAME is immutable"),
            ({"WRITE_ROLE_NAME": "agentgateway-write"}, "WRITE_ROLE_NAME is immutable"),
            ({"WRITE_ROLE_NAME": "agentgateway-write:workspace"}, "WRITE_ROLE_NAME is immutable"),
            ({"WRITE_ROLE_NAME": BORRADOR_ROLE}, "WRITE_ROLE_NAME is immutable"),
            ({"MAPPER_NAME": "other"}, "MAPPER_NAME is immutable"),
        ):
            result, calls, _ = _run("ensure", _state(), override)
            self.assertEqual(1, result.returncode, override)
            self.assertIn(message, result.stderr)
            self.assertEqual([], calls, override)

    def test_ensure_creates_the_client_on_a_fresh_realm(self):
        result, calls, state = _run("ensure", _state())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn(
            '"client_id":"hermes-enviar","realm_roles":"agentgateway-read:workspace agentgateway-write:workspace-envio","present":true',
            result.stdout)
        self.assertIn('"fullscope_allowed":false,"token_verified":true', result.stdout)
        creates = [c for c in calls if c.startswith("create clients ") and "clientId=hermes-enviar" in c]
        self.assertEqual(1, len(creates))
        for flag in ("serviceAccountsEnabled=true", "publicClient=false", "standardFlowEnabled=false",
                     "directAccessGrantsEnabled=false", "implicitFlowEnabled=false", "fullScopeAllowed=false"):
            self.assertIn(flag, creates[0])
        for role in REVIEWED_ROLES:
            self.assertTrue(any(c.startswith("add-roles ") and f"--rolename {role}" in c for c in calls), role)
        self.assertFalse(any(c.startswith("create roles") for c in calls))
        client = state["clients"]["hermes-enviar"]
        self.assertEqual("false", client["fullScopeAllowed"])
        self.assertEqual(REVIEWED_ROLES, client["sa_roles"])
        self.assertEqual(REVIEWED_ROLES, client["scope_roles"])
        self.assertEqual(["aud-mcp"], [m["name"] for m in client["mappers"].values()])
        self.assertEqual(["mcp.lan.e-dani.com"], [m["audience"] for m in client["mappers"].values()])

    def test_ensure_never_sends_a_secret_on_argv(self):
        _, calls, _ = _run("ensure", _state())
        creds = [c for c in calls if c.startswith("config credentials") and "--client hermes-enviar" in c]
        self.assertTrue(creds)
        # The mint reads the secret through the admin API (GET); no call
        # writes, rotates or POSTs one.
        self.assertTrue(any(c.startswith("get clients/uuid-hermes-enviar/client-secret") for c in calls))
        self.assertFalse(any("secret=" in c for c in calls if c.startswith(("create", "update"))))

    def test_ensure_is_idempotent_on_a_converged_client(self):
        result, calls, state = _run("ensure", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(any(c.startswith("create clients ") for c in calls))
        self.assertFalse(any(c.startswith("add-roles") for c in calls))
        self.assertFalse(any(c.startswith("create clients/uuid-hermes-enviar/scope-mappings") for c in calls))
        # Steady state: the owned flag is already false, so no update may
        # touch it.
        self.assertFalse(any("fullScopeAllowed" in c for c in calls if c.startswith("update ")))
        self.assertEqual("false", state["clients"]["hermes-enviar"]["fullScopeAllowed"])

    def test_ensure_refuses_to_run_before_the_roles_exist(self):
        result, calls, state = _run("ensure", _state(read_present=False))
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-read:workspace is missing; the agentgateway-read-grants hook owns it", result.stderr)
        self.assertFalse(any(c.startswith("create") for c in calls))
        self.assertEqual({}, state["clients"])
        result, calls, state = _run("ensure", _state(write_present=False))
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-write:workspace-envio is missing; the agentgateway-domain-roles hook owns it", result.stderr)
        self.assertFalse(any(c.startswith("create") for c in calls))
        self.assertEqual({}, state["clients"])

    def test_ensure_fails_closed_when_the_send_role_has_another_holder(self):
        # workspace-envio is the permission to send mail: a second holder, a
        # group, or a human is drift. Nothing is mutated before the check.
        for kwargs, message in (
            ({"write_users": ["service-account-hermes-secretaria"]}, f"{WRITE_ROLE} has an unauthorized user"),
            ({"write_users": ["me@e-dani.com"]}, f"{WRITE_ROLE} has an unauthorized user"),
            ({"write_groups": ["/edani-operators"]}, f"{WRITE_ROLE} is mapped to a group"),
        ):
            result, calls, _ = _run("ensure", _state(client=_converged_client(), **kwargs))
            self.assertEqual(1, result.returncode, kwargs)
            self.assertIn(message, result.stderr)
            self.assertFalse(any(c.startswith(("create", "update", "add-roles")) for c in calls), kwargs)

    def test_ensure_fails_when_the_service_account_holds_an_unreviewed_role(self):
        # The bare umbrella role, any other write domain (including the draft
        # role: it is a different identity's) and any sibling read route all
        # fail closed.
        for extra in ("agentgateway-write", "agentgateway-write:workspace", BORRADOR_ROLE,
                      "agentgateway-write:social", "agentgateway-read:gsc"):
            client = _converged_client(sa_roles=list(REVIEWED_ROLES) + ["default-roles-edani", extra])
            result, _, _ = _run("ensure", _state(client=client))
            self.assertEqual(1, result.returncode, extra)
            self.assertIn(f"unreviewed AgentGateway role: {extra}", result.stderr)

    def test_audit_fails_when_the_service_account_is_missing_a_role(self):
        # Audit never grants: a service account without the roles is drift.
        client = _converged_client(sa_roles=["default-roles-edani"])
        result, calls, _ = _run("audit", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("direct realm role missing", result.stderr)
        self.assertFalse(any(c.startswith(("create", "update", "add-roles")) for c in calls))

    def test_extra_scope_mapping_fails_closed(self):
        # A third role mapped into the client scope widens the reviewed matrix
        # the moment the service account is granted it. Additive reconciliation
        # never removes, so it fails closed before touching anything else.
        for extra in ("agentgateway-write", BORRADOR_ROLE):
            client = _converged_client(scope_roles=list(REVIEWED_ROLES) + [extra])
            result, calls, _ = _run("ensure", _state(client=client))
            self.assertEqual(1, result.returncode, extra)
            self.assertIn(f"client role scope has unexpected role {extra}; it widens the reviewed matrix", result.stderr)
            self.assertFalse(any(c.startswith("add-roles") for c in calls))
            self.assertFalse(any("fullScopeAllowed" in c for c in calls if c.startswith("update ")))

    def test_missing_scope_mapping_is_repaired_not_fatal(self):
        client = _converged_client(scope_roles=[READ_ROLE])
        result, calls, state = _run("ensure", _state(client=client))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(c.startswith("create clients/uuid-hermes-enviar/scope-mappings/realm") for c in calls))
        self.assertEqual(REVIEWED_ROLES, state["clients"]["hermes-enviar"]["scope_roles"])

    def test_drifted_fullscope_flag_converges_to_false_and_the_token_is_exact(self):
        # Someone set fullScopeAllowed=true by hand: the hook maps the scope
        # first, flips the flag, and only then verifies the exact token.
        client = _converged_client(fullScopeAllowed="true", scope_roles=[])
        result, calls, state = _run("ensure", _state(client=client))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("false", state["clients"]["hermes-enviar"]["fullScopeAllowed"])
        flips = [i for i, c in enumerate(calls) if c.startswith("update clients/uuid-hermes-enviar ") and "fullScopeAllowed=false" in c]
        maps = [i for i, c in enumerate(calls) if c.startswith("create clients/uuid-hermes-enviar/scope-mappings/realm")]
        self.assertTrue(flips and maps)
        self.assertLess(max(maps), min(flips), "the roles must be in the client scope before the flag goes off")
        self.assertIn('"token_verified":true', result.stdout)

    def test_off_matrix_token_fails_closed_and_the_flag_stays_false(self):
        # No consumer holds a token yet, so a token that is not exactly the
        # reviewed pair is never a reason to reopen the flag: fail closed.
        for client in (_converged_client(), _converged_client(fullScopeAllowed="true", scope_roles=[])):
            result, calls, state = _run("ensure", _state(client=client), {"FAKE_FORCE_BAD_OFF_TOKEN": "1"})
            self.assertEqual(1, result.returncode)
            self.assertIn("minted token has no realm_access roles claim", result.stderr)
            self.assertEqual("false", state["clients"]["hermes-enviar"]["fullScopeAllowed"])
            self.assertFalse(any("fullScopeAllowed=true" in c for c in calls))

    def test_token_with_a_bare_agentgateway_write_is_rejected(self):
        result, _, _ = _run("ensure", _state(client=_converged_client()), {"FAKE_TOKEN_EXTRA_ROLES": "agentgateway-write"})
        self.assertEqual(1, result.returncode)
        self.assertIn("minted token contains a forbidden agentgateway-write role", result.stderr)

    def test_token_with_any_extra_role_is_rejected(self):
        for extra in (BORRADOR_ROLE, "agentgateway-write:workspace", "agentgateway-read:gsc", "offline_access"):
            result, _, _ = _run("ensure", _state(client=_converged_client()), {"FAKE_TOKEN_EXTRA_ROLES": extra})
            self.assertEqual(1, result.returncode, extra)
            self.assertIn("minted hermes-enviar token realm roles are not exactly", result.stderr)

    def test_token_without_the_gateway_audience_is_rejected(self):
        # Without the aud-mcp audience the gateway answers 401 InvalidAudience:
        # the hook must catch it, not the first send.
        client = _converged_client(mappers={})
        result, _, _ = _run("audit", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("audience mapper missing", result.stderr)

    def test_audit_passes_on_the_converged_client_and_mutates_nothing(self):
        result, calls, _ = _run("audit", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"token_verified":true', result.stdout)
        self.assertFalse(any(c.startswith(("create", "update", "add-roles", "delete")) for c in calls))

    def test_audit_fails_on_interactive_flows(self):
        for field in ("standardFlowEnabled", "directAccessGrantsEnabled", "implicitFlowEnabled"):
            client = _converged_client(**{field: "true"})
            result, _, _ = _run("audit", _state(client=client))
            self.assertEqual(1, result.returncode, field)
            self.assertIn(f"client field {field} expected false", result.stderr)

    def test_rollback_deletes_the_client_and_retains_both_roles(self):
        result, calls, state = _run("rollback", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_present":false,"roles_retained":true', result.stdout)
        self.assertTrue(any(c.startswith("delete clients/uuid-hermes-enviar ") for c in calls))
        self.assertFalse(any(c.startswith("delete roles") for c in calls))
        for role in REVIEWED_ROLES:
            self.assertIn(role, state["roles"])
        self.assertEqual({}, state["clients"])


class HermesEnviarManifestContractTest(unittest.TestCase):
    def test_manifest_is_a_hardened_postsync_without_external_secret(self):
        manifest = (BASE / "hermes-enviar-client.yaml").read_text()
        # The secret is not managed here: no ExternalSecret, no 1Password
        # reference, no secretKeyRef the hook could block on.
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("onepassword", manifest)
        self.assertNotIn("CLIENT_SECRET", manifest)
        self.assertNotIn("secretKeyRef", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("argocd.argoproj.io/hook-delete-policy: BeforeHookCreation", manifest)
        # After the domain-roles (19) and read-grants (20) hooks that own both
        # roles and their holder allowlists.
        self.assertIn('argocd.argoproj.io/sync-wave: "24"', manifest)
        self.assertIn("name: CLIENT_ID, value: hermes-enviar", manifest)
        self.assertIn("name: READ_ROLE_NAME, value: agentgateway-read:workspace", manifest)
        self.assertIn("name: WRITE_ROLE_NAME, value: agentgateway-write:workspace-envio", manifest)
        self.assertIn("name: AGENTGATEWAY_AUDIENCE, value: mcp.lan.e-dani.com", manifest)
        self.assertIn("name: MAPPER_NAME, value: aud-mcp", manifest)
        self.assertIn('synapse.e-dani.com/agentgateway-m2m-client: "true"', manifest)
        self.assertIn("activeDeadlineSeconds: 1800", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)

    def test_kustomization_owns_job_and_script_and_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "hermes-enviar-client-rollback-job.yaml").read_text()
        self.assertIn("hermes-enviar-client.yaml", kustomization)
        self.assertIn("hermes-enviar-client.sh=scripts/hermes-enviar-client.sh", kustomization)
        self.assertNotIn("manual/hermes-enviar-client-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)
        self.assertIn("KEYCLOAK_URL", rollback)

    def test_reconcile_library_is_mounted_with_the_entrypoint(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        block = kustomization.split("name: keycloak-hermes-enviar-client", 1)[1].split("  - name:", 1)[0]
        self.assertIn("keycloak-reconcile-lib.sh=scripts/keycloak-reconcile-lib.sh", block)
        # OWU-76: the shared bootstrap ships with it, is sourced first, and
        # carries the bearer-token file into the shared EXIT trap.
        self.assertIn("kc-admin-common.sh=scripts/kc-admin-common.sh", block)
        script = (BASE / "scripts" / "hermes-enviar-client.sh").read_text()
        self.assertLess(
            script.index('. "${0%/*}/kc-admin-common.sh"'),
            script.index('. "$(dirname "$0")/keycloak-reconcile-lib.sh"'),
        )
        self.assertIn('KCADM_TMP_FILES="${CLIENT_CONFIG}"', script)
        self.assertNotIn("cleanup() {", script)
        self.assertNotIn("trap cleanup", script)
        for bootstrap_fn in ("fail()", "nonempty_lines()", "line_count()", "login_admin()", "kget()"):
            self.assertNotIn(bootstrap_fn, LIB.read_text())

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(["kubectl", "kustomize", str(BASE)], check=True, text=True, capture_output=True)
        self.assertIn("keycloak-hermes-enviar-client", result.stdout)
        # The library must survive into the built ConfigMaps: domain-roles,
        # chat, chat-mcp, jarvis and hermes-enviar.
        self.assertGreaterEqual(result.stdout.count("keycloak-reconcile-lib.sh: |"), 5)


class HermesEnviarCatalogContractTest(unittest.TestCase):
    """The client lands with its catalog entries, in the same PR (INFRA-219 rule)."""

    def setUp(self):
        self.catalog = kc_rbac.load_role_catalog(BASE / "ROLES.yaml")
        self.principals = verify_principals.load_principals(BASE / "PRINCIPALS.md")

    def test_roles_are_catalogued_with_their_grantees(self):
        envio = self.catalog[WRITE_ROLE]
        self.assertEqual("active", envio["status"])
        self.assertEqual([SA_USERNAME], envio["grantees"])
        self.assertTrue(envio["origin"].startswith("agentgateway-domain-roles.sh"), envio["origin"])
        borrador = self.catalog[BORRADOR_ROLE]
        self.assertEqual("active", borrador["status"])
        self.assertEqual(["service-account-hermes-secretaria-skirmshop"], borrador["grantees"])
        self.assertTrue(borrador["origin"].startswith("agentgateway-domain-roles.sh"), borrador["origin"])
        self.assertIn(SA_USERNAME, self.catalog[READ_ROLE]["grantees"])
        self.assertIn(SA_USERNAME, self.catalog["default-roles-edani"]["grantees"])

    def test_the_principal_holds_exactly_the_reviewed_roles(self):
        entry = self.principals[SA_USERNAME]
        self.assertEqual("sa", entry["type"])
        self.assertEqual("hermes-enviar", entry["client"])
        self.assertEqual("DevOps", entry["owner"])
        self.assertEqual("activo", entry["status"])
        self.assertIn("INFRA-676", entry["source"])
        self.assertEqual(sorted(REVIEWED_ROLES + ["default-roles-edani"]), sorted(entry["realm_roles"]))
        self.assertNotIn("agentgateway-write", entry["realm_roles"])
        # And the catalog grants it exactly those roles, nothing else.
        granted = sorted(name for name, role in self.catalog.items() if SA_USERNAME in role["grantees"])
        self.assertEqual(sorted(entry["realm_roles"]), granted)

    def test_domain_roles_hook_creates_both_roles_and_tolerates_only_the_reviewed_holder(self):
        script = (BASE / "scripts" / "agentgateway-domain-roles.sh").read_text()
        job = (BASE / "agentgateway-domain-roles-job.yaml").read_text()
        pair = f"{WRITE_ROLE}={SA_USERNAME}"
        for text in (script, job):
            self.assertIn(WRITE_ROLE, text)
            self.assertIn(BORRADOR_ROLE, text)
            self.assertIn(pair, text)
        # The draft role has exactly one reviewed holder, secretaria-skirmshop
        # (added after k8s-agentgateway-pocharlies#186 propagated: security
        # INFRA-640 condition 2). hermes-enviar never gets it.
        for text in (script, job):
            self.assertIn(f"{BORRADOR_ROLE}=service-account-hermes-secretaria-skirmshop", text)
            self.assertNotIn(f"{BORRADOR_ROLE}=service-account-hermes-enviar", text)

    def test_read_grants_hook_reviews_the_new_holder_of_the_shared_read_role(self):
        script = (BASE / "scripts" / "agentgateway-read-grants.sh").read_text()
        self.assertIn('ENVIAR_SA_USERNAME="service-account-hermes-enviar"', script)
        self.assertIn("ENVIAR_READ_ROLE_NAMES is immutable", script)
        # Eight reviewed holders of agentgateway-read:workspace: the bound of
        # the holder listing must exceed them so a ninth shows up.
        self.assertIn("-q max=9", script)


if __name__ == "__main__":
    unittest.main()
