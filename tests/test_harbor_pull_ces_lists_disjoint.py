"""SC-3089: un namespace va en UNA de las dos listas del CES harbor-runtime-pull.

photos-mcp estuvo en las dos (SC-4311 la metió en la de Merge, SC-4315 en la de
Owner): los dos ExternalSecret hijos peleaban por el Secret `harbor-pull` y el
de Merge quedaba permanentemente SecretSyncedError "target is owned by another
ExternalSecret". Este test es el guardaje: falla si cualquier namespace vuelve
a aparecer en ambas listas.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
FILE = ROOT / "platform" / "external-secrets" / "runtime-credentials.yaml"


def ces_by_name():
    docs = yaml.safe_load_all(FILE.read_text())
    return {
        d["metadata"]["name"]: d["spec"].get("namespaces", [])
        for d in docs
        if d and d.get("kind") == "ClusterExternalSecret"
    }


class TestHarborPullLists(unittest.TestCase):
    def test_merge_and_bootstrap_lists_are_disjoint(self):
        ces = ces_by_name()
        merge = set(ces["harbor-runtime-pull"])
        bootstrap = set(ces["harbor-runtime-pull-bootstrap"])
        overlap = sorted(merge & bootstrap)
        self.assertEqual(
            overlap, [],
            f"namespaces en las dos listas de harbor-runtime-pull (pelea por el "
            f"mismo Secret, SC-3089): {overlap}",
        )

    def test_no_duplicate_namespace_within_a_list(self):
        for name in ("harbor-runtime-pull", "harbor-runtime-pull-bootstrap"):
            ns = ces_by_name()[name]
            dup = sorted({n for n in ns if ns.count(n) > 1})
            self.assertEqual(dup, [], f"duplicados en {name}: {dup}")


if __name__ == "__main__":
    unittest.main()
