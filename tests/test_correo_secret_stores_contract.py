"""DGX-880 (P10 de la épica DGX-870, security S20): los dos ClusterSecretStore kubernetes que dan a `hermes` y a
`synapse` SOLO los secretos HMAC de su propio productor del núcleo de correo (`correo-core`, ns `correo`), sin pasar
por 1Password. Molde: tests/test_pagos_hermes_reader_contract.py.

El núcleo no genera nada aquí: k8s-correo-pocharlies (P8) crea en `correo` un Secret HMAC por productor y por
suscriptor (clave `password`). Cada store lleva el Role de `get` por resourceNames de UN consumidor:

  - Hermes (P13, ya en producción): `correo-productor-hermes` y `correo-suscriptor-hermes`.
  - Synapse (P12): `correo-productor-synapse`, y nada más.

Lo que hace segura la apertura es el alcance y este test lo fija: `get` exacto y nada más, esos nombres y ningún otro
Secret (los de Gmail y APNs viven en el mismo ns y quedan fuera), una sola identidad por store y un store que solo
puede usar el ns de su consumidor. Un `list`/`watch`, un resourceNames suelto, un ClusterRole o una segunda SA
vinculada son escándalo.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
KUSTOMIZATION = ROOT / "kustomization.yaml"
OLA = "argocd.argoproj.io/sync-wave"
RUTA_STORES = "platform/external-secrets/"


def _docs(ruta):
    return [d for d in yaml.safe_load_all(ruta.read_text(encoding="utf-8")) if d]


def _role_secretos(ruta):
    (role,) = [d for d in _docs(ROOT / ruta) if d["kind"] == "Role"]
    (regla,) = [r for r in role["rules"] if r.get("resources") == ["secrets"]]
    return set(regla["resourceNames"])


class _ContratoDelStore:
    """Lo que fija el store de UN consumidor; cada subclase dice quién es."""

    FICHERO = None       # platform/external-secrets/cluster-secret-store-correo-<consumidor>.yaml
    STORE = None         # nombre del ClusterSecretStore (lo usan los ExternalSecret del consumidor)
    SA = None            # ServiceAccount del store, también nombre del Role y del RoleBinding
    NS = None            # ns del consumidor: donde vive la SA y el único que puede usar el store
    SECRETOS = None      # Secrets del ns `correo` que puede leer, y ninguno más

    def setUp(self):
        self.docs = _docs(ROOT / self.FICHERO)

    def _uno(self, kind):
        (doc,) = [d for d in self.docs if d["kind"] == kind]
        return doc

    def test_el_fichero_trae_solo_el_store_su_identidad_y_su_rbac(self):
        # ni ClusterRole ni ClusterRoleBinding ni un segundo Role: el alcance es un Role en `correo`
        self.assertEqual(sorted(d["kind"] for d in self.docs),
                         ["ClusterSecretStore", "Role", "RoleBinding", "ServiceAccount"])

    def test_store_kubernetes_lee_del_ns_correo_como_la_sa_de_su_consumidor(self):
        store = self._uno("ClusterSecretStore")
        self.assertEqual(store["apiVersion"], "external-secrets.io/v1")
        self.assertEqual(store["metadata"]["name"], self.STORE)
        self.assertEqual(store["metadata"]["annotations"][OLA], "-4")
        self.assertEqual(list(store["spec"]["provider"]), ["kubernetes"])
        k = store["spec"]["provider"]["kubernetes"]
        self.assertEqual(k["auth"], {"serviceAccount": {"name": self.SA, "namespace": self.NS}})
        self.assertEqual(k["remoteNamespace"], "correo")
        self.assertEqual(k["server"]["url"], "kubernetes.default")
        self.assertEqual(k["server"]["caProvider"], {"type": "ConfigMap", "name": "kube-root-ca.crt",
                                                     "namespace": "correo", "key": "ca.crt"})

    def test_solo_el_ns_del_consumidor_puede_usar_el_store(self):
        # un ClusterSecretStore sin `conditions` lo puede nombrar un ExternalSecret de cualquier ns: Synapse
        # leería el HMAC de Hermes. Con `conditions` el otro ns recibe «not allowed» de ESO.
        store = self._uno("ClusterSecretStore")
        self.assertEqual(store["spec"]["conditions"], [{"namespaces": [self.NS]}])

    def test_role_solo_get_por_resourcenames_sobre_los_secretos_de_su_consumidor(self):
        role = self._uno("Role")
        self.assertEqual((role["metadata"]["name"], role["metadata"]["namespace"]), (self.SA, "correo"))
        secretos = [r for r in role["rules"] if r.get("resources") == ["secrets"]]
        self.assertEqual(len(secretos), 1)
        (regla,) = secretos
        self.assertEqual(regla["apiGroups"], [""])
        self.assertEqual(regla["verbs"], ["get"])                                   # ni list, ni watch, ni create
        self.assertEqual(sorted(regla["resourceNames"]), sorted(self.SECRETOS))    # solo los suyos
        self.assertFalse([n for n in regla["resourceNames"] if "gmail" in n or "apns" in n])
        demas = [r for r in role["rules"] if r.get("resources") != ["secrets"]]
        self.assertEqual([(r["apiGroups"], r["resources"], r["verbs"]) for r in demas],
                         [(["authorization.k8s.io"], ["selfsubjectrulesreviews"], ["create"])])  # validación del store

    def test_una_sola_identidad_y_un_solo_vinculo(self):
        sa = self._uno("ServiceAccount")
        self.assertEqual((sa["metadata"]["name"], sa["metadata"]["namespace"]), (self.SA, self.NS))
        binding = self._uno("RoleBinding")
        self.assertEqual((binding["metadata"]["name"], binding["metadata"]["namespace"]), (self.SA, "correo"))
        self.assertEqual(binding["roleRef"], {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role",
                                              "name": self.SA})
        self.assertEqual(binding["subjects"], [{"kind": "ServiceAccount", "name": self.SA,
                                                "namespace": self.NS}])  # la del store y ninguna otra

    def test_sa_y_rbac_van_antes_que_el_store_en_las_oleadas_de_argocd(self):
        # 04-10-2026: sin la SA y su RBAC el store no queda sano y k8s-infra no pasa de su oleada.
        def ola(d):
            return int((d["metadata"].get("annotations") or {}).get(OLA, "0"))
        store = self._uno("ClusterSecretStore")
        for kind in ("ServiceAccount", "Role", "RoleBinding"):
            self.assertLess(ola(self._uno(kind)), ola(store), kind)

    def test_el_fichero_entra_por_el_kustomization(self):
        resources = yaml.safe_load(KUSTOMIZATION.read_text(encoding="utf-8"))["resources"]
        self.assertIn(self.FICHERO, resources)


class CorreoHermesStoreContract(_ContratoDelStore, unittest.TestCase):
    FICHERO = RUTA_STORES + "cluster-secret-store-correo-hermes.yaml"
    STORE = "kubernetes-correo-hermes"
    SA = "eso-correo-hermes-reader"
    NS = "hermes"
    SECRETOS = ["correo-productor-hermes", "correo-suscriptor-hermes"]


class CorreoSynapseStoreContract(_ContratoDelStore, unittest.TestCase):
    FICHERO = RUTA_STORES + "cluster-secret-store-correo-synapse.yaml"
    STORE = "kubernetes-correo-synapse"
    SA = "eso-correo-synapse-reader"
    NS = "synapse"
    SECRETOS = ["correo-productor-synapse"]


class CorreoLosStoresNoSeCruzan(unittest.TestCase):
    def test_ninguno_lee_un_secreto_del_otro(self):
        hermes = _role_secretos(CorreoHermesStoreContract.FICHERO)
        synapse = _role_secretos(CorreoSynapseStoreContract.FICHERO)
        self.assertEqual(hermes & synapse, set())
        # la clave de productor de uno no firma por el otro: Synapse no ve nada de Hermes y Hermes no ve la de Synapse
        self.assertNotIn("correo-productor-synapse", hermes)


if __name__ == "__main__":
    unittest.main()
