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
            continue
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
        for name in ("onepassword-connect", "kubernetes-cnpg", "control-nexus-pagos"):
            path = STORES / f"cluster-secret-store-{name}.yaml"
            if not path.exists():
                continue
            for d in yaml.safe_load_all(path.read_text()):
                if d and d.get("kind") == "ClusterSecretStore":
                    self.assertLess(_wave(d), LAST, name)


if __name__ == "__main__":
    unittest.main()
