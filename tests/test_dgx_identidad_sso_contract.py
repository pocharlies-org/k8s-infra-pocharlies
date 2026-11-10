"""DGX-1539: /api/identidad (con qué usuario está la sesión del panel) necesita el Bearer, y el
Bearer solo lo pone oauth2-proxy (sso-chain). En LAN la regla 300 de DGX-1314 estampa
cabeceras X-Auth-Request-* que el backend no cree (DGX-807: solo el JWT verificado autoriza),
así que sin esta ruta el chip de la app diría «cuenta» siempre. En el edge ya cubre la regla
100 (sso-chain sin lista). Como Nova (INFRA-1247): strip + sso-chain + prueba de borde.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAN = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
EDGE = ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml"


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _route(docs, name, priority):
    for doc in docs:
        if doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == name:
            for route in doc["spec"]["routes"]:
                if route.get("priority") == priority:
                    return route
    raise AssertionError(f"route {name}@{priority} not found")


class IdentidadSSOContract(unittest.TestCase):
    def test_lan_430_lleva_api_identidad_por_sso_chain(self):
        route = _route(_docs(LAN), "lan-dgx-dashboard-public-host", 430)
        self.assertIn("Path(`/api/identidad`)", route["match"])
        chain = [(m["name"], m.get("namespace", "")) for m in route["middlewares"]]
        self.assertEqual(chain, [("dgx-strip-identity-headers", "traefik-lan"),
                                 ("sso-chain", "keycloak"),
                                 ("dgx-edge-proof", "traefik-lan")])
        self.assertEqual(route["services"][0]["name"], "dgx-dashboard-ui")

    def test_edge_100_cubre_api_identidad_sin_lista(self):
        """En el edge no hace falta regla propia: la 100 (sso-chain sin lista ni ClientIP) traga
        cualquier path de dgx.e-dani.com, /api/identidad incluido."""
        route = _route(_docs(EDGE), "edge-dgx-dashboard-public", 100)
        self.assertNotIn("ClientIP", route["match"])
        self.assertIn("sso-chain", [m["name"] for m in route["middlewares"]])


if __name__ == "__main__":
    unittest.main()
