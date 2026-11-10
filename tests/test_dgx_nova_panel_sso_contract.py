"""dgx.nova.panel.v1 (INFRA-1247): /api/nova entra en el control set (prioridad 400, tras sso-chain) de las dos
IngressRoute de traefik-edge que sirven el dashboard, y en LAN/tailnet (traefik-lan) /nova y /api/nova tienen su propia
regla 420 tras sso-chain por encima de la 300 sin login (Dani, 10-11: DGX-807 dejó la 300 sin JWT). Todos los métodos, no solo POST: el backend pone
ESCRITURA_CLUSTER también en el GET (la transcripción de la reunión) y en el DELETE (sacar a Nova), y sin sso-chain
el JWT no llega y hasta un admin recibe 403 (security, INFRA-1247)."""
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


class NovaPanelSSOContract(unittest.TestCase):
    def test_api_nova_va_entera_tras_sso_chain(self):
        for path, name in RUTAS:
            route = _ruta(path, name)
            self.assertIn("PathPrefix(`/api/nova`)", route["match"], path.name)
            self.assertNotIn("Method(", route["match"], f"{path.name}: el control set no filtra por método")
            chain = [m["name"] for m in route["middlewares"]]
            self.assertLess(chain.index("dgx-strip-identity-headers"), chain.index("sso-chain"), path.name)

    def test_lan_420_nova_tras_sso_y_prueba_de_borde(self):
        path = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
        route = _ruta(path, "lan-dgx-dashboard-public-host", 420)
        self.assertIn("Path(`/nova`)", route["match"])
        self.assertIn("PathPrefix(`/api/nova`)", route["match"])
        self.assertNotIn("ClientIP(", route["match"], "vale para todos: también LAN/tailnet")
        chain = [(m["name"], m.get("namespace", "")) for m in route["middlewares"]]
        self.assertEqual(chain, [("dgx-strip-identity-headers", "traefik-lan"), ("sso-chain", "keycloak"),
                                 ("dgx-edge-proof", "traefik-lan")])


if __name__ == "__main__":
    unittest.main()
