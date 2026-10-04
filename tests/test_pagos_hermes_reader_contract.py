"""dgx.app.pagos.v1 (aditivo 04-10-2026): el ClusterSecretStore kubernetes que da a Hermes los
secretos HMAC del dashboard de pagos, y su RBAC mínimo.

El plugin `confirmar-pago` (k8s-openclaw-qwen36-pocharlies) firma sus rutas de máquina con DOS
secretos que vive en `control-nexus`, generados in-cluster por el ESO del dashboard (nunca por
1Password):

  - `dgx-dashboard-pagos` (general)   → GET /esperar y POST /resultado
  - `dgx-dashboard-pagos-decision`    → SOLO POST /decision (veredicto del architect sobre
    dgx-infra#961: la secretaria, que recibe el general por pago-alerta, no puede autoaprobarse)

Este test fija el alcance, que es lo que hace segura la apertura: `get` exacto y nada más, esos
dos nombres y ningún otro Secret, y una sola identidad (la SA del store). Un `list`/`watch`, un
resourceNames suelto o una segunda SA vinculada son escándalo.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORE = ROOT / "platform" / "external-secrets" / "cluster-secret-store-control-nexus-pagos.yaml"
KUSTOMIZATION = ROOT / "kustomization.yaml"

SA = "eso-control-nexus-pagos-reader"
SECRETS = ["dgx-dashboard-pagos", "dgx-dashboard-pagos-decision"]


def _docs():
    return [d for d in yaml.safe_load_all(STORE.read_text()) if d]


def _kind(kind):
    return [d for d in _docs() if d["kind"] == kind]


class PagosHermesReaderContract(unittest.TestCase):
    def test_store_kubernetes_lee_de_control_nexus_como_sa_de_hermes(self):
        (store,) = _kind("ClusterSecretStore")
        self.assertEqual(store["metadata"]["name"], "kubernetes-control-nexus-pagos")
        self.assertEqual(store["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-4")
        k = store["spec"]["provider"]["kubernetes"]
        self.assertEqual(k["auth"]["serviceAccount"], {"name": SA, "namespace": "hermes"})
        self.assertEqual(k["remoteNamespace"], "control-nexus")
        self.assertEqual(k["server"]["url"], "kubernetes.default")
        self.assertEqual(k["server"]["caProvider"], {"type": "ConfigMap", "name": "kube-root-ca.crt",
                                                     "namespace": "control-nexus", "key": "ca.crt"})

    def test_role_solo_get_sobre_los_dos_secretos_y_nada_mas(self):
        (role,) = _kind("Role")
        self.assertEqual(role["metadata"]["namespace"], "control-nexus")
        secretos = [r for r in role["rules"] if r.get("resources") == ["secrets"]]
        self.assertEqual(len(secretos), 1)
        (regla,) = secretos
        self.assertEqual(regla["verbs"], ["get"])                       # ni list, ni watch, ni create
        self.assertEqual(sorted(regla["resourceNames"]), sorted(SECRETS))  # solo estos dos
        self.assertEqual(regla["apiGroups"], [""])
        demas = [r for r in role["rules"] if r.get("resources") != ["secrets"]]
        self.assertEqual([(r["apiGroups"], r["resources"], r["verbs"]) for r in demas],
                         [(["authorization.k8s.io"], ["selfsubjectrulesreviews"], ["create"])])  # validación del store

    def test_una_sola_identidad_y_un_solo_vinculo(self):
        (sa,) = _kind("ServiceAccount")
        self.assertEqual((sa["metadata"]["name"], sa["metadata"]["namespace"]), (SA, "hermes"))
        (binding,) = _kind("RoleBinding")
        self.assertEqual(binding["metadata"]["namespace"], "control-nexus")
        self.assertEqual(binding["roleRef"]["name"], SA)
        self.assertEqual(binding["subjects"], [{"kind": "ServiceAccount", "name": SA,
                                                "namespace": "hermes"}])  # la del store y ninguna otra

    def test_el_fichero_entra_por_el_kustomization(self):
        rel = "platform/external-secrets/cluster-secret-store-control-nexus-pagos.yaml"
        resources = yaml.safe_load(KUSTOMIZATION.read_text())["resources"]
        self.assertIn(rel, resources)


if __name__ == "__main__":
    unittest.main()
