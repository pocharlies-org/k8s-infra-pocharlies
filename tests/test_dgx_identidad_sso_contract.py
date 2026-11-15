"""DGX-1539: /api/identidad (con qué usuario está la sesión del panel) necesita el Bearer, y el
Bearer solo lo pone oauth2-proxy (sso-chain). En LAN la regla 300 de DGX-1314 estampa
cabeceras X-Auth-Request-* que el backend no cree (DGX-807: solo el JWT verificado autoriza),
así que sin esta ruta el chip de la app diría «cuenta» siempre. En el edge ya cubre la regla
100 (sso-chain sin lista). Como Nova (INFRA-1247): strip + sso-chain + prueba de borde.
"""
import pathlib
import unittest

import yaml


def _ruta(fichero, nombre_ingressroute, prioridad):
    ruta = pathlib.Path(__file__).resolve().parents[1] / fichero
    docs = [d for d in yaml.safe_load_all(ruta.read_text()) if d]
    for doc in docs:
        if doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == nombre_ingressroute:
            for route in doc["spec"]["routes"]:
                if route.get("priority") == prioridad:
                    return route, docs
    raise AssertionError(f"{nombre_ingressroute}@{prioridad} no encontrada")


class IdentidadSSOContract(unittest.TestCase):
    def test_lan_430_lleva_api_identidad_por_sso_chain(self):
        route, _ = _ruta("networking/traefik-lan/dgx-public-host-lan.yaml",
                         "lan-dgx-dashboard-public-host", 430)
        self.assertIn("Path(`/api/identidad`)", route["match"])
        self.assertEqual([(m["name"], m.get("namespace", "")) for m in route["middlewares"]],
                         [("dgx-strip-identity-headers", "traefik-lan"),
                          ("sso-chain", "keycloak"),
                          ("dgx-edge-proof", "traefik-lan")])
        self.assertEqual(route["services"][0]["name"], "dgx-dashboard-ui")

    def test_edge_100_cubre_api_identidad_sin_lista(self):
        """En el edge no hace falta regla propia: la 100 (sso-chain sin lista ni ClientIP) traga
        cualquier path de dgx.e-dani.com, /api/identidad incluido."""
        route, _ = _ruta("networking/traefik-edge/dgx-dashboard-public.yaml",
                         "edge-dgx-dashboard-public", 100)
        self.assertNotIn("ClientIP", route["match"])
        self.assertIn("sso-chain", [m["name"] for m in route["middlewares"]])


if __name__ == "__main__":
    unittest.main()
