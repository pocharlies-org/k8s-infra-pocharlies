"""DGX-1218 (PR-2 de la épica DGX-1209): las dos identidades del agente de casos de Postia.

correo-agente-lectura lee las rutas de los perfiles y no lleva ningún
agentgateway-write*; correo-ejecutor lleva el rol acotado
agentgateway-write:correo-ejecutor (order_shipping_line_replace,
order_returnable_lines_get, return_create y labels_pickup_create,
k8s-agentgateway-pocharlies#221) y agentgateway-read:shopify-admin, nunca el
agentgateway-write pelado (condición 3 de security, DGX-1209). El esqueleto del
contrato es el compartido de los scoped-clients
(tests/keycloak_scoped_client_testlib.py); aquí solo la política propia: la
exclusividad del rol de escritura del ejecutor y los catálogos.
"""
import importlib.util, pathlib, shutil, subprocess, sys, unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "correo-agente-client.sh"
SCRIPTS = BASE / "scripts"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402
from keycloak_scoped_client_testlib import ScopedClientContractMixin  # noqa: E402

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


class CorreoAgenteReconcilerTest(ScopedClientContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT
    SCRIPTS = SCRIPTS
    CLIENTS = CLIENTS
    GUARD_CASES = [
        ("correo-agente-lectura", {"CLIENT_ID": "correo-agente-escritura"}, "unsupported immutable client"),
        ("correo-ejecutor", {"MAPPER_NAME": "other"}, "MAPPER_NAME is immutable"),
    ]
    MISSING_CASES = [
        ("correo-ejecutor", EJECUTOR_ROLE, "the agentgateway-domain-roles hook owns it"),
        ("correo-agente-lectura", "agentgateway-read:picqer", "the agentgateway-read-grants hook owns it"),
    ]
    UNREVIEWED_CASES = [
        ("correo-agente-lectura", "agentgateway-write"),
        ("correo-agente-lectura", EJECUTOR_ROLE),
        ("correo-agente-lectura", "agentgateway-write:workspace-borrador"),
        ("correo-ejecutor", "agentgateway-write"),
        ("correo-ejecutor", "agentgateway-write:shopify"),
        ("correo-ejecutor", "agentgateway-read:workspace"),
    ]
    AUDIT_NO_MAPPER_CLIENT = "correo-agente-lectura"
    ROLLBACK_CLIENT = "correo-ejecutor"

    def _state(self, client_id, missing=(), client=None, write_users=(), write_groups=()):
        # Extensión del estado compartido: los titulares del rol de escritura
        # del ejecutor, para test_the_executor_role_has_no_other_holder.
        state = super()._state(client_id, missing, client)
        if EJECUTOR_ROLE in state["roles"]:
            state["roles"][EJECUTOR_ROLE].update(users=list(write_users), groups=list(write_groups))
        return state

    def fixed_scope_extra_checks(self, own, script):
        # The read identity's role set never names a write role.
        lectura = own.split("correo-agente-lectura)", 1)[1].split(";;", 1)[0]
        self.assertNotIn("agentgateway-write", lectura)

    def test_the_executor_role_has_no_other_holder(self):
        for kwargs, message in (
            ({"write_users": ["service-account-correo-agente-lectura"]}, f"{EJECUTOR_ROLE} has an unauthorized user"),
            ({"write_users": ["me@e-dani.com"]}, f"{EJECUTOR_ROLE} has an unauthorized user"),
            ({"write_groups": ["/edani-operators"]}, f"{EJECUTOR_ROLE} is mapped to a group"),
        ):
            result, calls, _ = self._run("correo-ejecutor", "ensure",
                                         self._state("correo-ejecutor", client=self._converged("correo-ejecutor"), **kwargs))
            self.assertEqual(1, result.returncode, kwargs)
            self.assertIn(message, result.stderr)
            self.assertFalse(any(c.startswith(("create", "update", "add-roles")) for c in calls))


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
