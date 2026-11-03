"""SC-4304 S6: las tres identidades de lectura de bancos Hindsight.

jarvis-hindsight y synapse-hindsight-tienda leen el banco `tienda`
(agentgateway-read:hindsight-tienda); socialmedia-hindsight lee el banco
`personal` (agentgateway-read:hindsight-personal). Un principal por (servicio,
banco) por veredicto de security de 02-11: una credencial filtrada abre
exactamente un banco. Ninguna identidad lleva rol de escritura alguno (las
rutas hindsight son de solo lectura por diseño). El esqueleto del contrato es
el compartido de los scoped-clients (tests/keycloak_scoped_client_testlib.py,
el mismo que usan hermes-enviar y correo-agente); aquí solo la política
propia: la tabla de roles sin escritura y los catálogos.
"""
import importlib.util, pathlib, shutil, subprocess, sys, unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "hindsight-reader-client.sh"
SCRIPTS = BASE / "scripts"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402
from keycloak_scoped_client_testlib import ScopedClientContractMixin  # noqa: E402

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


class HindsightReaderReconcilerTest(ScopedClientContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT
    SCRIPTS = SCRIPTS
    CLIENTS = CLIENTS
    GUARD_CASES = [
        ("jarvis-hindsight", {"CLIENT_ID": "jarvis-hindsight-escritura"}, "unsupported immutable client"),
        ("socialmedia-hindsight", {"MAPPER_NAME": "other"}, "MAPPER_NAME is immutable"),
    ]
    MISSING_CASES = [
        ("jarvis-hindsight", TIENDA_ROLE, "the agentgateway-read-grants hook owns it"),
        ("socialmedia-hindsight", PERSONAL_ROLE, "the agentgateway-read-grants hook owns it"),
    ]
    UNREVIEWED_CASES = [
        ("jarvis-hindsight", "agentgateway-write"),
        ("jarvis-hindsight", PERSONAL_ROLE),
        ("synapse-hindsight-tienda", "agentgateway-write:workspace-borrador"),
        ("socialmedia-hindsight", "agentgateway-write"),
        ("socialmedia-hindsight", TIENDA_ROLE),
    ]
    AUDIT_NO_MAPPER_CLIENT = "jarvis-hindsight"
    ROLLBACK_CLIENT = "socialmedia-hindsight"

    def fixed_scope_extra_checks(self, own, script):
        # Ningún conjunto revisado nombra un rol de escritura: las rutas
        # hindsight son de solo lectura por diseño (analysis del config vivo).
        table = own.split('case "${CLIENT_ID}" in', 1)[1].split("esac", 1)[0]
        self.assertNotIn("agentgateway-write", table)


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
