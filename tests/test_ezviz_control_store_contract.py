"""INFRA-717 fase 2: el store kubernetes que da al ezviz-gateway (ns `frigate`) SOLO el token del control que genera el
dashboard en control-nexus. Fija el alcance: un Role de `get` exacto sobre ese Secret, una SA, y solo `frigate` lo usa."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
FICHERO = ROOT / "platform/external-secrets/cluster-secret-store-control-nexus-ezviz.yaml"
SA = "eso-control-nexus-ezviz-reader"


class StoreEzvizControl(unittest.TestCase):
    def setUp(self):
        self.docs = [d for d in yaml.safe_load_all(FICHERO.read_text(encoding="utf-8")) if d]
        self.de = {d["kind"]: d for d in self.docs}

    def test_solo_store_sa_role_y_binding(self):
        self.assertEqual(sorted(d["kind"] for d in self.docs), ["ClusterSecretStore", "Role", "RoleBinding", "ServiceAccount"])

    def test_store_lee_control_nexus_y_solo_lo_usa_frigate(self):
        spec = self.de["ClusterSecretStore"]["spec"]
        self.assertEqual(spec["conditions"], [{"namespaces": ["frigate"]}])
        k = spec["provider"]["kubernetes"]
        self.assertEqual(k["auth"], {"serviceAccount": {"name": SA, "namespace": "frigate"}})
        self.assertEqual(k["remoteNamespace"], "control-nexus")

    def test_role_solo_get_del_token(self):
        role = self.de["Role"]
        self.assertEqual(role["metadata"]["namespace"], "control-nexus")
        (secretos,) = [r for r in role["rules"] if r.get("resources") == ["secrets"]]
        self.assertEqual(secretos, {"apiGroups": [""], "resources": ["secrets"],
                                    "resourceNames": ["dgx-dashboard-ezviz-control"], "verbs": ["get"]})
        self.assertEqual(len(role["rules"]), 2)

    def test_binding_une_solo_esa_sa(self):
        b = self.de["RoleBinding"]
        self.assertEqual(b["subjects"], [{"kind": "ServiceAccount", "name": SA, "namespace": "frigate"}])
        self.assertEqual(b["roleRef"]["name"], SA)

    def test_esta_en_el_build(self):
        self.assertIn("platform/external-secrets/cluster-secret-store-control-nexus-ezviz.yaml",
                      (ROOT / "kustomization.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
