"""INFRA-533: el ClusterSecretStore `onepassword` (SDK) va en la ÚLTIMA wave de ArgoCD.

Con el cupo diario de 1Password agotado el store queda `InvalidProviderConfig`, nunca llega a Healthy y
ArgoCD no pasa de su wave: en wave 0 bloqueaba las waves 1 y 19-26 (policy `onchange`, reconciliadores
de Keycloak). Nada depende de su salud, así que va el último. Un recurso nuevo con wave > 30 rompe esto.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORES = ROOT / "platform" / "external-secrets"
WAVE = "argocd.argoproj.io/sync-wave"
LAST = 30


def _wave(doc):
    return int(((doc.get("metadata") or {}).get("annotations") or {}).get(WAVE, 0))


def _build(kustomization):
    """Documentos de un kustomization.yaml y, recursivamente, de sus resources locales."""
    docs = []
    for res in yaml.safe_load(kustomization.read_text()).get("resources", []):
        if "://" in res:
            raise AssertionError(f"resource remoto {res}: el test no puede medir sus waves")
        path = kustomization.parent / res
        if path.is_dir():
            docs += _build(path / "kustomization.yaml")
        else:
            docs += [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]
    return docs


def _store(name):
    (doc,) = [d for d in yaml.safe_load_all((STORES / f"cluster-secret-store-{name}.yaml").read_text())
              if d and d.get("kind") == "ClusterSecretStore"]
    return doc


class OnePasswordStoreWaveContract(unittest.TestCase):
    def test_el_store_onepassword_sigue_siendo_el_mismo_objeto(self):
        store = _store("onepassword")
        self.assertEqual(store["metadata"]["name"], "onepassword")
        self.assertIn("onepasswordSDK", store["spec"]["provider"])

    def test_wave_del_store_es_la_ultima(self):
        self.assertEqual(_wave(_store("onepassword")), LAST)

    def test_ningun_recurso_del_build_tiene_wave_posterior(self):
        docs = _build(ROOT / "kustomization.yaml")
        self.assertTrue(docs)
        otros = [(d["kind"], d["metadata"].get("name"), _wave(d)) for d in docs
                 if not (d["kind"] == "ClusterSecretStore" and d["metadata"].get("name") == "onepassword")]
        self.assertTrue([o for o in otros if o[2] > 0], "el build deja de cargar waves: el test no mide nada")
        self.assertEqual([o for o in otros if o[2] >= LAST], [])

    def test_los_otros_stores_no_van_en_la_ultima_wave(self):
        stores = {d["metadata"]["name"]: d for d in _build(ROOT / "kustomization.yaml")
                  if d["kind"] == "ClusterSecretStore"}
        # Estos dos viven en este repo: si faltan, el test falla (no se descartan en silencio).
        for name in ("onepassword-connect", "kubernetes-control-nexus-pagos"):
            self.assertIn(name, stores, f"el store {name} ya no está en el build de k8s-infra")
        for name, doc in stores.items():
            if name != "onepassword":
                self.assertLess(_wave(doc), LAST, name)

    def test_store_kubernetes_cnpg_no_esta_en_este_repo(self):
        stores = [d["metadata"]["name"] for d in _build(ROOT / "kustomization.yaml")
                  if d["kind"] == "ClusterSecretStore"]
        if "kubernetes-cnpg" not in stores:
            self.skipTest("kubernetes-cnpg no se define en k8s-infra (vive en otro repo): su wave no se puede medir aquí")
        self.assertLess(_wave(next(d for d in _build(ROOT / "kustomization.yaml")
                                   if d["metadata"].get("name") == "kubernetes-cnpg")), LAST)


if __name__ == "__main__":
    unittest.main()
