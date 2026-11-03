"""SC-4304 S6: las tres identidades de lectura de bancos Hindsight.

jarvis-hindsight y synapse-hindsight-tienda leen el banco `tienda`
(agentgateway-read:hindsight-tienda); socialmedia-hindsight lee el banco
`personal` (agentgateway-read:hindsight-personal). Un principal por (servicio,
banco) por veredicto de security de 02-11: una credencial filtrada abre
exactamente un banco. Ninguna identidad lleva rol de escritura alguno (las
rutas hindsight son de solo lectura por diseño). Mismo molde que
tests/test_correo_agente_identity_contract.py: un reconciliador para los tres
clients contra el kcadm falso, y el catálogo comprobado por nombre.
"""
import functools, importlib.util, pathlib, shutil, subprocess, sys, unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "hindsight-reader-client.sh"
SCRIPTS = BASE / "scripts"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402
from kcadm_fake import run_reconciler  # noqa: E402

_spec = importlib.util.spec_from_file_location("verify_principals", SCRIPTS / "verify-principals.py")
verify_principals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_principals)

TIENDA_ROLE = "agentgateway-read:hindsight-tienda"
PERSONAL_ROLE = "agentgateway-read:hindsight-personal"
CLIENTS = {
    "jarvis-hindsight": [TIENDA_ROLE],
    "synapse-hindsight-tienda": [TIENDA_ROLE],
    "socialmedia-hindsight": [PERSONAL_ROLE],
}


def _run(client_id, mode, state, env=None):
    return run_reconciler(SCRIPT, client_id, mode, state, {"CLIENT_ID": client_id, **(env or {})})


def _state(client_id, missing=(), client=None):
    state = {"clients": {}, "roles": {}}
    for role in sorted({r for roles in CLIENTS.values() for r in roles}):
        if role in missing:
            continue
        state["roles"][role] = {"id": f"role-{role}", "composite": False}
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


class HindsightReaderReconcilerTest(unittest.TestCase):
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
        # No reviewed role set names a write role (the routes are read-only).
        table = own.split("case \"${CLIENT_ID}\" in", 1)[1].split("esac", 1)[0]
        self.assertNotIn("agentgateway-write", table)

    def test_guards_are_immutable_before_any_call(self):
        for client_id, env, message in (
            ("jarvis-hindsight", {"CLIENT_ID": "jarvis-hindsight-escritura"}, "unsupported immutable client"),
            ("socialmedia-hindsight", {"MAPPER_NAME": "other"}, "MAPPER_NAME is immutable"),
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
        for client_id, role in (
            ("jarvis-hindsight", TIENDA_ROLE),
            ("socialmedia-hindsight", PERSONAL_ROLE),
        ):
            result, calls, _ = _run(client_id, "ensure", _state(client_id, missing=(role,)))
            self.assertEqual(1, result.returncode)
            self.assertIn(f"{role} is missing; the agentgateway-read-grants hook owns it", result.stderr)
            self.assertFalse(any(c.startswith("create") for c in calls))

    def test_unreviewed_roles_fail_closed(self):
        for client_id, extra in (
            ("jarvis-hindsight", "agentgateway-write"),
            ("jarvis-hindsight", PERSONAL_ROLE),
            ("synapse-hindsight-tienda", "agentgateway-write:workspace-borrador"),
            ("socialmedia-hindsight", "agentgateway-write"),
            ("socialmedia-hindsight", TIENDA_ROLE),
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
        result, _, _ = _run("jarvis-hindsight", "audit",
                            _state("jarvis-hindsight", client=_converged("jarvis-hindsight", mappers={})))
        self.assertEqual(1, result.returncode)
        self.assertIn("audience mapper missing", result.stderr)

    def test_rollback_deletes_the_client_and_retains_the_roles(self):
        result, calls, state = _run("socialmedia-hindsight", "rollback",
                                    _state("socialmedia-hindsight", client=_converged("socialmedia-hindsight")))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_present":false,"roles_retained":true', result.stdout)
        self.assertFalse(any(c.startswith("delete roles") for c in calls))
        self.assertIn(PERSONAL_ROLE, state["roles"])
        self.assertEqual({}, state["clients"])


class HindsightReaderManifestContractTest(unittest.TestCase):
    def test_one_hardened_postsync_job_per_client(self):
        manifest = (BASE / "hindsight-reader-clients.yaml").read_text()
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("secretKeyRef", manifest)
        for client_id in CLIENTS:
            self.assertIn(f"name: keycloak-{client_id}-client", manifest)
            self.assertIn(f"name: CLIENT_ID, value: {client_id}", manifest)
        self.assertEqual(3, manifest.count("argocd.argoproj.io/hook: PostSync"))
        self.assertEqual(3, manifest.count('argocd.argoproj.io/sync-wave: "24"'))
        self.assertEqual(3, manifest.count("automountServiceAccountToken: false"))
        self.assertEqual(3, manifest.count("readOnlyRootFilesystem: true"))
        self.assertEqual(3, manifest.count('synapse.e-dani.com/agentgateway-m2m-client: "true"'))
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)

    def test_kustomization_owns_jobs_and_script(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("  - hindsight-reader-clients.yaml", kustomization)
        block = kustomization.split("name: keycloak-hindsight-reader-client", 1)[1].split("  - name:", 1)[0]
        for entry in ("hindsight-reader-client.sh=scripts/hindsight-reader-client.sh",
                      "kc-admin-common.sh=scripts/kc-admin-common.sh",
                      "keycloak-reconcile-lib.sh=scripts/keycloak-reconcile-lib.sh",
                      "keycloak-scoped-client-lib.sh=scripts/keycloak-scoped-client-lib.sh"):
            self.assertIn(entry, block)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(["kubectl", "kustomize", str(BASE)], check=True, text=True, capture_output=True)
        for client_id in CLIENTS:
            self.assertIn(f"keycloak-{client_id}-client", result.stdout)


class HindsightReaderCatalogContractTest(unittest.TestCase):
    def setUp(self):
        self.catalog = kc_rbac.load_role_catalog(BASE / "ROLES.yaml")
        self.principals = verify_principals.load_principals(BASE / "PRINCIPALS.md")

    def test_each_principal_holds_exactly_its_roles(self):
        for client_id, roles in CLIENTS.items():
            sa = f"service-account-{client_id}"
            entry = self.principals[sa]
            self.assertEqual(("sa", client_id, "activo"), (entry["type"], entry["client"], entry["status"]))
            self.assertIn("SC-4304", entry["source"])
            self.assertEqual(sorted(roles + ["default-roles-edani"]), sorted(entry["realm_roles"]))
            self.assertNotIn("agentgateway-write", entry["realm_roles"])
            granted = sorted(name for name, role in self.catalog.items() if sa in role["grantees"])
            self.assertEqual(sorted(entry["realm_roles"]), granted)

    def test_read_grants_hook_reviews_the_two_tienda_holders(self):
        script = (BASE / "scripts" / "agentgateway-read-grants.sh").read_text()
        self.assertIn('JARVIS_HINDSIGHT_SA_USERNAME="service-account-jarvis-hindsight"', script)
        self.assertIn('SYNAPSE_HINDSIGHT_SA_USERNAME="service-account-synapse-hindsight-tienda"', script)
        self.assertIn("JARVIS_HINDSIGHT_READ_ROLE_NAMES is immutable", script)
        self.assertIn("SYNAPSE_HINDSIGHT_READ_ROLE_NAMES is immutable", script)


if __name__ == "__main__":
    unittest.main()
