"""DGX-821: toda escritura POST /api/cluster/* del panel DGX pasa por sso-chain.

El backend (dgx-infra, services/dashboard/guarda_cluster.py) exige en todas las
escrituras de /api/cluster/* la prueba de borde y el grupo /edani-admins. Si el borde
solo pide SSO para apply, scale/restart y sync/rollback, el botón «refresh» de ArgoCD
(POST /api/cluster/argocd/<app>/refresh) y las acciones docker llegan sin identidad y
el backend responde 403. Aquí se fija que la regla de escrituras (priority 350) de cada
host del panel cubra el prefijo entero, solo para POST y con sso-chain.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
FICHEROS = [
    ROOT / "networking/traefik-edge/dgx-dashboard-public.yaml",
    ROOT / "networking/traefik-edge/s3-media-public.yaml",
    ROOT / "networking/traefik-lan/dgx-public-host-lan.yaml",
]
PREFIJO = "PathPrefix(`/api/cluster/`)"


def _rutas():
    for f in FICHEROS:
        for doc in yaml.safe_load_all(f.read_text()):
            if not doc or doc.get("kind") != "IngressRoute":
                continue
            for ruta in doc["spec"].get("routes", []):
                servicios = {s.get("name") for s in ruta.get("services", [])}
                if "dgx-dashboard-ui" in servicios:
                    yield f.name, ruta


def _middlewares(ruta):
    return {m["name"] for m in ruta.get("middlewares", [])}


class EscriturasDeClusterPorSSO(unittest.TestCase):
    def test_cada_host_del_panel_pide_sso_para_todo_post_de_cluster(self):
        reglas = [(f, r) for f, r in _rutas() if PREFIJO in r["match"]]
        # dgx.e-dani.com (edge), s3.e-dani.com (edge), dgx+dgx.lan y s3 (LAN)
        self.assertEqual(len(reglas), 4, [f for f, _ in reglas])
        for f, ruta in reglas:
            with self.subTest(fichero=f, priority=ruta.get("priority")):
                self.assertIn("Method(`POST`)", ruta["match"])
                self.assertIn("sso-chain", _middlewares(ruta))
                self.assertIn("dgx-strip-identity-headers", _middlewares(ruta))

    def test_ninguna_regla_deja_fuera_refresh_ni_docker(self):
        for f, ruta in _rutas():
            with self.subTest(fichero=f, priority=ruta.get("priority")):
                self.assertNotIn("(sync|rollback)$", ruta["match"])
                self.assertNotIn("PathPrefix(`/api/cluster/apply`)", ruta["match"])


if __name__ == "__main__":
    unittest.main()
