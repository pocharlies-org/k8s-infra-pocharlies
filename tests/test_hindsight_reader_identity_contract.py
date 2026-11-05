"""SC-4304 S6: la identidad de lectura de bancos Hindsight que queda.

socialmedia-hindsight lee el banco `personal` (agentgateway-read:hindsight-personal).
Un principal por (servicio, banco) por veredicto de security de 02-11: una
credencial filtrada abre exactamente un banco. La identidad no lleva rol de
escritura alguno (las rutas hindsight son de solo lectura por diseño). El
veredicto de 05-11 retiró las otras dos que este PR traía: jarvis-hindsight
(banco `tienda`: pedidos y correo de clientes con datos personales; el TTS de
Alexa los diría a Amazon y un correo hostil podría dirigir al agente de voz) y
synapse-hindsight-tienda (lookup_supplier_history lee de Skirmbooks): el test
fija que no existen en ninguna parte. El esqueleto del contrato es el
compartido de los scoped-clients (tests/keycloak_scoped_client_testlib.py, el
mismo que usan hermes-enviar y correo-agente); aquí solo la política propia:
la tabla de roles sin escritura y los catálogos.
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
    "socialmedia-hindsight": [PERSONAL_ROLE],
}
# Retiradas por el veredicto de security de 05-11-2026: no deben existir.
REFUSED_CLIENTS = ("jarvis-hindsight", "synapse-hindsight-tienda")


class HindsightReaderReconcilerTest(ScopedClientContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT
    SCRIPTS = SCRIPTS
    CLIENTS = CLIENTS
    GUARD_CASES = [
        ("socialmedia-hindsight", {"CLIENT_ID": "socialmedia-hindsight-escritura"}, "unsupported immutable client"),
        ("socialmedia-hindsight", {"CLIENT_ID": "jarvis-hindsight"}, "unsupported immutable client"),
        ("socialmedia-hindsight", {"CLIENT_ID": "synapse-hindsight-tienda"}, "unsupported immutable client"),
        ("socialmedia-hindsight", {"MAPPER_NAME": "other"}, "MAPPER_NAME is immutable"),
    ]
    MISSING_CASES = [
        ("socialmedia-hindsight", PERSONAL_ROLE, "the agentgateway-read-grants hook owns it"),
    ]
    UNREVIEWED_CASES = [
        ("socialmedia-hindsight", "agentgateway-write"),
        ("socialmedia-hindsight", TIENDA_ROLE),
    ]
    AUDIT_NO_MAPPER_CLIENT = "socialmedia-hindsight"
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
        self.assertEqual(len(CLIENTS), manifest.count("argocd.argoproj.io/hook: PostSync"))
        self.assertEqual(len(CLIENTS), manifest.count('argocd.argoproj.io/sync-wave: "24"'))
        self.assertEqual(len(CLIENTS), manifest.count("automountServiceAccountToken: false"))
        self.assertEqual(len(CLIENTS), manifest.count("readOnlyRootFilesystem: true"))
        self.assertEqual(len(CLIENTS), manifest.count('synapse.e-dani.com/agentgateway-m2m-client: "true"'))
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)

    def test_hook_limits_are_the_two_cpu_of_the_other_keycloak_hooks(self):
        # SC-4611 (#455): kcadm in a 500m Job is throttled to 99% and drags the
        # k8s-infra sync out by tens of minutes. Every client hook gets 2 CPU.
        manifest = (BASE / "hindsight-reader-clients.yaml").read_text()
        self.assertEqual(len(CLIENTS), manifest.count('limits: { cpu: "2", memory: 512Mi }'))
        self.assertNotIn("cpu: 500m", manifest)

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

    def test_personal_grants_hook_reviews_the_socialmedia_holder(self):
        # The role's COMPLETE direct holder set belongs to the wave-25 hook; an
        # SA outside its reviewed set would be revoked on every sync.
        script = (BASE / "scripts" / "agentgateway-hindsight-personal-grants.sh").read_text()
        self.assertIn("service-account-socialmedia-hindsight", script.split("REVIEWED_SERVICE_ACCOUNTS=", 1)[1].split("\n", 1)[0])

    def test_refused_identities_exist_nowhere(self):
        # Security's ruling of 05-11-2026: `tienda` holds customer orders and
        # email with personal data; the voice surface does not read it, and
        # synapse-tools-mcp reads Skirmbooks instead of a bank.
        live = [
            BASE / "hindsight-reader-clients.yaml",
            BASE / "scripts" / "hindsight-reader-client.sh",
            BASE / "scripts" / "agentgateway-read-grants.sh",
            BASE / "kustomization.yaml",
        ]
        for path in live:
            text = path.read_text()
            for client_id in REFUSED_CLIENTS:
                for line in text.splitlines():
                    if client_id in line:
                        self.assertTrue(line.lstrip().startswith("#"), f"{client_id} outside a comment in {path.name}: {line}")
        for client_id in REFUSED_CLIENTS:
            sa = f"service-account-{client_id}"
            self.assertNotIn(sa, self.principals)
            for name, role in self.catalog.items():
                self.assertNotIn(sa, role["grantees"], name)


if __name__ == "__main__":
    unittest.main()
