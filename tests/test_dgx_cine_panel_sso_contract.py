"""dgx.cine.producciones.v1 (DGX-1676): /api/cine entra entero, todos los métodos, en el control set (prioridad 400, tras
sso-chain) de las dos IngressRoute de traefik-edge que sirven el dashboard, y en LAN/tailnet (traefik-lan) /cine y /api/cine
van en la regla 420 tras sso-chain, la de Nova, por encima de la 300 sin login. El backend pone ESCRITURA_CLUSTER en todo
el router (crea agentes en paseo-0, lee sus guiones y su actividad), y sin sso-chain el JWT no llega y hasta un admin
recibe 403 (DGX-807). El tablero Backlot no se publica por aquí: es cine.lan (tests/test_cine_lan_route_contract.py)."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUTAS = [(ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml", "edge-dgx-dashboard-public"),
         (ROOT / "networking" / "traefik-edge" / "s3-media-public.yaml", None)]


def _ruta(path, name, priority=400):
    for doc in yaml.safe_load_all(path.read_text()):
        if doc and doc.get("kind") == "IngressRoute" and (name is None or doc["metadata"]["name"] == name):
            for route in doc["spec"]["routes"]:
                if route.get("priority") == priority:
                    return route
    raise AssertionError(f"{path.name}: sin ruta de prioridad {priority}")


class CinePanelSSOContract(unittest.TestCase):
    def test_api_cine_va_entera_tras_sso_chain_en_el_borde(self):
        for path, name in RUTAS:
            route = _ruta(path, name)
            self.assertIn("PathPrefix(`/api/cine`)", route["match"], path.name)
            self.assertNotIn("Method(", route["match"], f"{path.name}: el control set no filtra por método")
            chain = [m["name"] for m in route["middlewares"]]
            self.assertLess(chain.index("dgx-strip-identity-headers"), chain.index("sso-chain"), path.name)
            self.assertIn("dgx-edge-proof", chain, path.name)

    def test_lan_420_cine_tras_sso_y_prueba_de_borde(self):
        path = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
        route = _ruta(path, "lan-dgx-dashboard-public-host", 420)
        self.assertIn("Path(`/cine`)", route["match"])
        self.assertIn("PathPrefix(`/api/cine`)", route["match"])
        self.assertNotIn("ClientIP(", route["match"], "vale para todos: también LAN/tailnet")
        chain = [(m["name"], m.get("namespace", "")) for m in route["middlewares"]]
        self.assertEqual(chain, [("dgx-strip-identity-headers", "traefik-lan"), ("sso-chain", "keycloak"),
                                 ("dgx-edge-proof", "traefik-lan")])


if __name__ == "__main__":
    unittest.main()
