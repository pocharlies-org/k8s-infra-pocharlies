"""INFRA-1189: la fixture de solo lectura del smoke de la frontera de escritura.

`scripts/smoke-write-role.sh` (k8s-agentgateway-pocharlies, C7 de la épica
INFRA-218) prueba la frontera con dos tokens: un ADMIN con el rol
`agentgateway-write` (el service-account-agentgateway-mcp compartido ya lo es)
y un OPERATOR que NO lo es: exactamente las dos lecturas que exigen las puertas
de ruta (/social: agentgateway-read:social; /workspace:
agentgateway-read:workspace) y ningún agentgateway-write*. Ningún principal del
realm tenía esa forma, así que el smoke no tenía operador: esta es esa fixture,
el client confidencial `agentgateway-smoke-operator`.

El esqueleto del contrato es el compartido de los scoped-clients
(tests/keycloak_scoped_client_testlib.py); aquí la política propia: la fixture
no porta ningún write ni puede llegar a portarlo, y las declaraciones (catálogo,
principales, allowlist del hook de lecturas) la revisan como un titular más.
"""
import importlib.util, pathlib, shutil, subprocess, sys, unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "agentgateway-smoke-operator-client.sh"
SCRIPTS = BASE / "scripts"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402
from keycloak_scoped_client_testlib import ScopedClientContractMixin  # noqa: E402

_spec = importlib.util.spec_from_file_location("verify_principals", SCRIPTS / "verify-principals.py")
verify_principals = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify_principals)

CLIENT = "agentgateway-smoke-operator"
ROLES = ["agentgateway-read:social", "agentgateway-read:workspace"]


class SmokeOperatorReconcilerTest(ScopedClientContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT
    SCRIPTS = SCRIPTS
    CLIENTS = {CLIENT: ROLES}
    GUARD_CASES = [
        (CLIENT, {"CLIENT_ID": "agentgateway-mcp"}, "unsupported immutable client"),
        (CLIENT, {"MAPPER_NAME": "other"}, "MAPPER_NAME is immutable"),
    ]
    MISSING_CASES = [
        (CLIENT, "agentgateway-read:social", "the agentgateway-read-grants hook owns it"),
        (CLIENT, "agentgateway-read:workspace", "the agentgateway-read-grants hook owns it"),
    ]
    UNREVIEWED_CASES = [
        (CLIENT, "agentgateway-write"),
        (CLIENT, "agentgateway-write:social"),
        (CLIENT, "agentgateway-read:brain"),
    ]
    AUDIT_NO_MAPPER_CLIENT = CLIENT
    ROLLBACK_CLIENT = CLIENT

    def fixed_scope_extra_checks(self, own, script):
        # The OPERATOR shape is the point: the reviewed set names no write role,
        # and the write-holder assertion of the shared library is inert here
        # (WRITE_ROLE_NAME empty, as in hindsight-reader-client.sh).
        reviewed = own.split(f"{CLIENT})", 1)[1].split(";;", 1)[0]
        self.assertNotIn("agentgateway-write", reviewed)
        self.assertIn('WRITE_ROLE_NAME=""', own)


class SmokeOperatorManifestContractTest(unittest.TestCase):
    def test_one_hardened_postsync_job(self):
        manifest = (BASE / "agentgateway-smoke-operator-client.yaml").read_text()
        # No ExternalSecret: Keycloak generates the secret and the smoke reads it
        # through the admin API (clients/<uuid>/client-secret), never argv.
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("secretKeyRef", manifest)
        self.assertIn("name: keycloak-agentgateway-smoke-operator-client", manifest)
        self.assertIn(f"name: CLIENT_ID, value: {CLIENT}", manifest)
        self.assertEqual(1, manifest.count("argocd.argoproj.io/hook: PostSync"))
        self.assertEqual(1, manifest.count('argocd.argoproj.io/sync-wave: "24"'))
        self.assertEqual(1, manifest.count("automountServiceAccountToken: false"))
        self.assertEqual(1, manifest.count("readOnlyRootFilesystem: true"))
        self.assertEqual(1, manifest.count('synapse.e-dani.com/agentgateway-m2m-client: "true"'))
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)

    def test_kustomization_owns_job_and_script(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("  - agentgateway-smoke-operator-client.yaml", kustomization)
        block = kustomization.split("name: keycloak-agentgateway-smoke-operator-client", 1)[1].split("  - name:", 1)[0]
        for entry in (f"agentgateway-smoke-operator-client.sh=scripts/agentgateway-smoke-operator-client.sh",
                      "kc-admin-common.sh=scripts/kc-admin-common.sh",
                      "keycloak-reconcile-lib.sh=scripts/keycloak-reconcile-lib.sh",
                      "keycloak-scoped-client-lib.sh=scripts/keycloak-scoped-client-lib.sh"):
            self.assertIn(entry, block)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(["kubectl", "kustomize", str(BASE)], check=True, text=True, capture_output=True)
        self.assertIn("keycloak-agentgateway-smoke-operator-client", result.stdout)


class SmokeOperatorCatalogContractTest(unittest.TestCase):
    def setUp(self):
        self.catalog = kc_rbac.load_role_catalog(BASE / "ROLES.yaml")
        self.principals = verify_principals.load_principals(BASE / "PRINCIPALS.md")

    def test_the_fixture_holds_exactly_its_two_reads(self):
        sa = f"service-account-{CLIENT}"
        entry = self.principals[sa]
        self.assertEqual(("sa", CLIENT, "activo"), (entry["type"], entry["client"], entry["status"]))
        self.assertIn("INFRA-1189", entry["source"])
        self.assertEqual(sorted(ROLES + ["default-roles-edani"]), sorted(entry["realm_roles"]))
        self.assertFalse([r for r in entry["realm_roles"] if r.startswith("agentgateway-write")])
        granted = sorted(name for name, role in self.catalog.items() if sa in role["grantees"])
        self.assertEqual(sorted(entry["realm_roles"]), granted)

    def test_read_grants_hook_reviews_the_fixture(self):
        script = (BASE / "scripts" / "agentgateway-read-grants.sh").read_text()
        self.assertIn(f'SMOKE_OPERATOR_SA_USERNAME="service-account-{CLIENT}"', script)
        self.assertIn("SMOKE_OPERATOR_READ_ROLE_NAMES is immutable", script)
        # Ten reviewed service accounts hold agentgateway-read:workspace now
        # (the smoke fixture is the tenth), so the exclusivity bound must be
        # one above them.
        self.assertIn("-q max=11", script)


if __name__ == "__main__":
    unittest.main()
