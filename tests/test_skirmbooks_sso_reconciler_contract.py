"""SKIRM-15: el reconciler del SSO de skirmbooks es un guion fino sobre
sso-app-common.sh (antes lo compartía con alphalink, que pasó a su realm en
SC-2822). Lo que hace seguro desplegarlo: que el ConfigMap del Job monte el común
y que los literales del guion sigan siendo los que declara el Job (si difieren,
el Job muere con «is immutable» y nadie entra). Muere con skirmbooks en su realm.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
KEYCLOAK = ROOT / "platform" / "keycloak-next"


class ReconcilerSkirmbooks(unittest.TestCase):
    def test_el_configmap_del_job_lleva_el_comun(self):
        kust = yaml.safe_load((KEYCLOAK / "kustomization.yaml").read_text(encoding="utf-8"))
        gen = next(g for g in kust["configMapGenerator"] if g["name"] == "keycloak-skirmbooks-sso")
        self.assertIn("sso-app-common.sh", [f.split("=")[0] for f in gen["files"]])

    def test_el_guion_es_fino_y_declara_lo_de_su_job(self):
        guion = (KEYCLOAK / "scripts" / "skirmbooks-sso.sh").read_text(encoding="utf-8")
        self.assertIn('. "${0%/*}/sso-app-common.sh"', guion)
        job = next(d for d in yaml.safe_load_all((KEYCLOAK / "skirmbooks-sso.yaml").read_text(encoding="utf-8"))
                   if d and d["kind"] == "Job")
        env = {e["name"]: str(e["value"]) for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
        for variable, clave in (("EXPECT_REDIRECT_URI", "REDIRECT_URI"),
                                ("EXPECT_USER_GROUP", "USER_GROUP"),
                                ("EXPECT_ADMIN_GROUP", "ADMIN_GROUP")):
            self.assertIn(f"{variable}={env[clave]}", guion, f"skirmbooks-sso.sh y su Job no concuerdan en {clave}")


if __name__ == "__main__":
    unittest.main()
