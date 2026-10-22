"""DGX-1218 (PR-2 de la épica DGX-1209): las dos identidades del agente de casos de Postia.

correo-agente-lectura lee las rutas de los perfiles y no lleva ningún
agentgateway-write*; correo-ejecutor lleva el rol acotado
agentgateway-write:correo-ejecutor (order_shipping_line_replace,
order_returnable_lines_get, return_create y labels_pickup_create,
k8s-agentgateway-pocharlies#221) y agentgateway-read:shopify-admin, nunca el
agentgateway-write pelado (condición 3 de security, DGX-1209). Mismo molde que
tests/test_hermes_enviar_identity_contract.py: un reconciliador para los dos
clients contra el kcadm falso, y el catálogo comprobado por nombre.
"""
import functools, importlib.util, pathlib, shutil, subprocess, sys, unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "correo-agente-client.sh"
SCRIPTS = BASE / "scripts"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402
from kcadm_fake import run_reconciler  # noqa: E402

_spec = importlib.util.spec_from_file_location("verify_principals", SCRIPTS / "verify-principals.py")
verify_principals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_principals)

EJECUTOR_ROLE = "agentgateway-write:correo-ejecutor"
CLIENTS = {
    "correo-agente-lectura": [
        "agentgateway-read:brain", "agentgateway-read:picqer", "agentgateway-read:shopify",
        "agentgateway-read:shopify-admin", "agentgateway-read:skirmshop-plugins", "agentgateway-read:workspace",
    ],
    "correo-ejecutor": ["agentgateway-read:shopify-admin", EJECUTOR_ROLE],
}


def _run(client_id, mode, state, env=None):
    return run_reconciler(SCRIPT, client_id, mode, state, {"CLIENT_ID": client_id, **(env or {})})


def _state(client_id, missing=(), client=None, write_users=(), write_groups=()):
    state = {"clients": {}, "roles": {}}
    for role in sorted({r for roles in CLIENTS.values() for r in roles}):
        if role in missing:
            continue
        state["roles"][role] = {"id": f"role-{role}", "composite": False}
        if role == EJECUTOR_ROLE:
            state["roles"][role].update(users=list(write_users), groups=list(write_groups))
    if client is not None:
        state["clients"][client_id] = client
    return state


def _converged(client_id, **extra):
    roles = CLIENTS[client_id]
    client = {
        "clientId": client_id, "enabled": "true", "publicClient": "false",
        "standardFlowEnabled": "false", "directAccessGrantsEnabled": "false",
        "implicitFlowEnabled": "false", "serviceAccountsEnabled": "true",
        "fullScopeAllowed": "false", "secret": f"generated-{client_id}",
        "sa_roles": list(roles) + ["default-roles-edani"], "scope_roles": list(roles),
        "mappers": {"m1": {"name": "aud-mcp", "audience": "mcp.lan.e-dani.com"}},
    }
    client.update(extra)
    return client


class CorreoAgenteReconcilerTest(unittest.TestCase):
    def test_reconciler_is_fixed_scope_and_never_touches_the_secret(self):
        own = SCRIPT.read_text()
        self.assertIn('. "$(dirname "$0")/keycloak-scoped-client-lib.sh"', own)
        script = own + (SCRIPTS / "keycloak-scoped-client-lib.sh").read_text()
        self.assertIn("unsupported immutable client", script)
        self.assertIn('. "$(dirname "$0")/keycloak-reconcile-lib.sh"', script)
        self.assertIn('ensure_role_in_client_scope "${role}"', script)
        self.assertIn('client_secret_via_admin "${CLIENT_UUID}"', script)
        self.assertNotIn("redirectUris", script)
        self.assertNotIn("create roles", script)
        self.assertNotIn("-s secret=", script)
        self.assertNotIn("set -x", script)
        # The read identity's role set never names a write role.
        lectura = own.split("correo-agente-lectura)", 1)[1].split(";;", 1)[0]
        self.assertNotIn("agentgateway-write", lectura)

    def test_guards_are_immutable_before_any_call(self):
        for client_id, env, message in (
            ("correo-agente-lectura", {"CLIENT_ID": "correo-agente-escritura"}, "unsupported immutable client"),
            ("correo-ejecutor", {"MAPPER_NAME": "other"}, "MAPPER_NAME is immutable"),
        ):
            result, calls, _ = _run(client_id, "ensure", _state(client_id), env)
            self.assertEqual(1, result.returncode, env)
            self.assertIn(message, result.stderr)
            self.assertEqual([], calls)

    def test_ensure_creates_each_client_with_exactly_its_roles(self):
        for client_id, roles in CLIENTS.items():
            result, calls, state = _run(client_id, "ensure", _state(client_id))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f'"client_id":"{client_id}","realm_roles":"{" ".join(roles)}","present":true', result.stdout)
            self.assertIn('"fullscope_allowed":false,"token_verified":true', result.stdout)
            creates = [c for c in calls if c.startswith("create clients ") and f"clientId={client_id}" in c]
            self.assertEqual(1, len(creates))
            for flag in ("serviceAccountsEnabled=true", "publicClient=false", "standardFlowEnabled=false",
                         "directAccessGrantsEnabled=false", "implicitFlowEnabled=false", "fullScopeAllowed=false"):
                self.assertIn(flag, creates[0])
            client = state["clients"][client_id]
            self.assertEqual(roles, client["sa_roles"])
            self.assertEqual(roles, client["scope_roles"])
            self.assertEqual(["aud-mcp"], [m["name"] for m in client["mappers"].values()])
            self.assertFalse(any(c.startswith("create roles") for c in calls))
            self.assertFalse(any("secret=" in c for c in calls if c.startswith(("create", "update"))))

    def test_ensure_is_idempotent_and_audit_mutates_nothing(self):
        for client_id in CLIENTS:
            result, calls, _ = _run(client_id, "ensure", _state(client_id, client=_converged(client_id)))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(any(c.startswith(("create clients ", "add-roles")) for c in calls))
            result, calls, _ = _run(client_id, "audit", _state(client_id, client=_converged(client_id)))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(any(c.startswith(("create", "update", "add-roles", "delete")) for c in calls))

    def test_ensure_refuses_to_run_before_the_roles_exist(self):
        result, calls, _ = _run("correo-ejecutor", "ensure", _state("correo-ejecutor", missing=(EJECUTOR_ROLE,)))
        self.assertEqual(1, result.returncode)
        self.assertIn(f"{EJECUTOR_ROLE} is missing; the agentgateway-domain-roles hook owns it", result.stderr)
        self.assertFalse(any(c.startswith("create") for c in calls))
        result, calls, _ = _run("correo-agente-lectura", "ensure",
                                _state("correo-agente-lectura", missing=("agentgateway-read:picqer",)))
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-read:picqer is missing; the agentgateway-read-grants hook owns it", result.stderr)
        self.assertFalse(any(c.startswith("create") for c in calls))

    def test_the_executor_role_has_no_other_holder(self):
        for kwargs, message in (
            ({"write_users": ["service-account-correo-agente-lectura"]}, f"{EJECUTOR_ROLE} has an unauthorized user"),
            ({"write_users": ["me@e-dani.com"]}, f"{EJECUTOR_ROLE} has an unauthorized user"),
            ({"write_groups": ["/edani-operators"]}, f"{EJECUTOR_ROLE} is mapped to a group"),
        ):
            result, calls, _ = _run("correo-ejecutor", "ensure",
                                    _state("correo-ejecutor", client=_converged("correo-ejecutor"), **kwargs))
            self.assertEqual(1, result.returncode, kwargs)
            self.assertIn(message, result.stderr)
            self.assertFalse(any(c.startswith(("create", "update", "add-roles")) for c in calls))

    def test_unreviewed_roles_fail_closed(self):
        # The read identity never holds a write role; the executor never the bare one.
        for client_id, extra in (
            ("correo-agente-lectura", "agentgateway-write"),
            ("correo-agente-lectura", EJECUTOR_ROLE),
            ("correo-agente-lectura", "agentgateway-write:workspace-borrador"),
            ("correo-ejecutor", "agentgateway-write"),
            ("correo-ejecutor", "agentgateway-write:shopify"),
            ("correo-ejecutor", "agentgateway-read:workspace"),
        ):
            client = _converged(client_id, sa_roles=CLIENTS[client_id] + ["default-roles-edani", extra])
            result, _, _ = _run(client_id, "ensure", _state(client_id, client=client))
            self.assertEqual(1, result.returncode, (client_id, extra))
            self.assertIn(f"unreviewed AgentGateway role: {extra}", result.stderr)
            client = _converged(client_id, scope_roles=CLIENTS[client_id] + [extra])
            result, _, _ = _run(client_id, "ensure", _state(client_id, client=client))
            self.assertEqual(1, result.returncode, (client_id, extra))
            self.assertIn(f"client role scope has unexpected role {extra}", result.stderr)

    def test_minted_token_must_be_exact(self):
        for client_id in CLIENTS:
            state = _state(client_id, client=_converged(client_id))
            result, _, _ = _run(client_id, "ensure", state, {"FAKE_TOKEN_EXTRA_ROLES": "agentgateway-write"})
            self.assertEqual(1, result.returncode)
            self.assertIn("minted token contains a forbidden agentgateway-write role", result.stderr)
            result, _, _ = _run(client_id, "ensure", state, {"FAKE_TOKEN_EXTRA_ROLES": "offline_access"})
            self.assertEqual(1, result.returncode)
            self.assertIn(f"minted {client_id} token realm roles are not exactly", result.stderr)
        result, _, _ = _run("correo-agente-lectura", "audit",
                            _state("correo-agente-lectura", client=_converged("correo-agente-lectura", mappers={})))
        self.assertEqual(1, result.returncode)
        self.assertIn("audience mapper missing", result.stderr)

    def test_rollback_deletes_the_client_and_retains_the_roles(self):
        result, calls, state = _run("correo-ejecutor", "rollback",
                                    _state("correo-ejecutor", client=_converged("correo-ejecutor")))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_present":false,"roles_retained":true', result.stdout)
        self.assertFalse(any(c.startswith("delete roles") for c in calls))
        self.assertIn(EJECUTOR_ROLE, state["roles"])
        self.assertEqual({}, state["clients"])


class CorreoAgenteManifestContractTest(unittest.TestCase):
    def test_one_hardened_postsync_job_per_client(self):
        manifest = (BASE / "correo-agente-clients.yaml").read_text()
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("secretKeyRef", manifest)
        for client_id in CLIENTS:
            self.assertIn(f"name: keycloak-{client_id}-client", manifest)
            self.assertIn(f"name: CLIENT_ID, value: {client_id}", manifest)
        self.assertEqual(2, manifest.count("argocd.argoproj.io/hook: PostSync"))
        self.assertEqual(2, manifest.count('argocd.argoproj.io/sync-wave: "24"'))
        self.assertEqual(2, manifest.count("automountServiceAccountToken: false"))
        self.assertEqual(2, manifest.count("readOnlyRootFilesystem: true"))
        self.assertEqual(2, manifest.count('synapse.e-dani.com/agentgateway-m2m-client: "true"'))
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)

    def test_kustomization_owns_jobs_and_script(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("  - correo-agente-clients.yaml", kustomization)
        block = kustomization.split("name: keycloak-correo-agente-client", 1)[1].split("  - name:", 1)[0]
        for entry in ("correo-agente-client.sh=scripts/correo-agente-client.sh",
                      "kc-admin-common.sh=scripts/kc-admin-common.sh",
                      "keycloak-reconcile-lib.sh=scripts/keycloak-reconcile-lib.sh",
                      "keycloak-scoped-client-lib.sh=scripts/keycloak-scoped-client-lib.sh"):
            self.assertIn(entry, block)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(["kubectl", "kustomize", str(BASE)], check=True, text=True, capture_output=True)
        self.assertIn("keycloak-correo-ejecutor-client", result.stdout)
        self.assertIn("keycloak-correo-agente-lectura-client", result.stdout)


class CorreoAgenteCatalogContractTest(unittest.TestCase):
    def setUp(self):
        self.catalog = kc_rbac.load_role_catalog(BASE / "ROLES.yaml")
        self.principals = verify_principals.load_principals(BASE / "PRINCIPALS.md")

    def test_the_executor_role_is_catalogued_with_one_holder(self):
        role = self.catalog[EJECUTOR_ROLE]
        self.assertEqual("active", role["status"])
        self.assertEqual(["service-account-correo-ejecutor"], role["grantees"])
        self.assertTrue(role["origin"].startswith("agentgateway-domain-roles.sh"), role["origin"])

    def test_each_principal_holds_exactly_its_roles(self):
        for client_id, roles in CLIENTS.items():
            sa = f"service-account-{client_id}"
            entry = self.principals[sa]
            self.assertEqual(("sa", client_id, "activo"), (entry["type"], entry["client"], entry["status"]))
            self.assertIn("DGX-1218", entry["source"])
            self.assertEqual(sorted(roles + ["default-roles-edani"]), sorted(entry["realm_roles"]))
            self.assertNotIn("agentgateway-write", entry["realm_roles"])
            granted = sorted(name for name, role in self.catalog.items() if sa in role["grantees"])
            self.assertEqual(sorted(entry["realm_roles"]), granted)
        lectura = self.principals["service-account-correo-agente-lectura"]["realm_roles"]
        self.assertFalse([r for r in lectura if r.startswith("agentgateway-write")])

    def test_domain_roles_hook_creates_the_role_with_one_reviewed_holder(self):
        pair = f"{EJECUTOR_ROLE}=service-account-correo-ejecutor"
        for path in (BASE / "scripts" / "agentgateway-domain-roles.sh", BASE / "agentgateway-domain-roles-job.yaml"):
            text = path.read_text()
            self.assertIn(f",{EJECUTOR_ROLE}", text, path)
            self.assertIn(pair, text, path)
            self.assertNotIn(f"{EJECUTOR_ROLE}=service-account-correo-agente-lectura", text, path)

    def test_read_grants_hook_reviews_both_holders(self):
        script = (BASE / "scripts" / "agentgateway-read-grants.sh").read_text()
        self.assertIn('CORREO_LECTURA_SA_USERNAME="service-account-correo-agente-lectura"', script)
        self.assertIn('CORREO_EJECUTOR_SA_USERNAME="service-account-correo-ejecutor"', script)
        self.assertIn("CORREO_LECTURA_READ_ROLE_NAMES is immutable", script)
        self.assertIn("CORREO_EJECUTOR_READ_ROLE_NAMES is immutable", script)
        # Nine reviewed holders of agentgateway-read:workspace now: the bound must exceed them.
        self.assertIn("-q max=10", script)


if __name__ == "__main__":
    unittest.main()
