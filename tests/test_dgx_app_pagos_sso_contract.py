"""dgx.app.pagos.v1 (03-10-2026): las rutas de la app DGX de pagos pasan SIEMPRE por
oauth2-proxy, en LAN y en el edge, y las de máquina se quedan públicas en LAN por diseño
(HMAC V2 propio, no SSO).

El backend exige `es_dani` sobre la cabecera `X-Auth-Request-Email`. Esa cabecera solo vale
si la estampa el forwardAuth de oauth2-proxy (`sso-forward-auth.authResponseHeaders`): en la
ruta abierta de prioridad 300 la cabecera viaja VACIADA por `dgx-strip-identity-headers`
(SC-1191), así que ni la app funciona por ahí ni un forged de identidad sirve. Este test fija
la cadena completa sobre los dos ficheros que poseen las rutas:

  - networking/traefik-lan/dgx-public-host-lan.yaml  (IngressRoute lan-dgx-dashboard-public-host)
  - networking/traefik-edge/dgx-dashboard-public.yaml (IngressRoute edge-dgx-dashboard-public)
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAN = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
EDGE = ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml"
ROUTING = ROOT / "platform" / "keycloak-next" / "routing.yaml"

APP_PREFIXES = ("PathPrefix(`/api/app/pagos`)", "PathPrefix(`/api/app/push`)")


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _route(docs, name, priority):
    for doc in docs:
        if doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == name:
            for route in doc["spec"]["routes"]:
                if route.get("priority") == priority:
                    return route
    raise AssertionError(f"route {name}@{priority} not found")


class PagosSSOContract(unittest.TestCase):
    def _assert_protected(self, docs, name, priority, ns):
        route = _route(docs, name, priority)
        match = route["match"]
        for prefix in APP_PREFIXES:
            self.assertIn(prefix, match, f"{name}@{priority} must protect {prefix}")
        # y NUNCA la ruta de máquina /api/pagos (lleva HMAC, se queda en el bypass)
        self.assertNotIn("PathPrefix(`/api/pagos`)", match)
        self.assertNotIn("Path(`/api/pagos`)", match)
        chain = [(m["name"], m.get("namespace", "")) for m in route["middlewares"]]
        self.assertEqual(chain, [("dgx-strip-identity-headers", ns), ("sso-chain", "keycloak")],
                         f"{name}@{priority}: strip first, then sso-chain")

    def test_lan_400_protege_app_pagos_y_push(self):
        self._assert_protected(_docs(LAN), "lan-dgx-dashboard-public-host", 400, "traefik-lan")

    def test_edge_400_protege_app_pagos_y_push(self):
        self._assert_protected(_docs(EDGE), "edge-dgx-dashboard-public", 400, "traefik-edge")

    def test_ninguna_ruta_de_mas_prioridad_cubre_api_app(self):
        """Arriba del 400 solo vive la regla /messages (450): no puede tragar /api/app/*."""
        for docs, name in ((_docs(LAN), "lan-dgx-dashboard-public-host"),
                           (_docs(EDGE), "edge-dgx-dashboard-public")):
            for doc in docs:
                if doc.get("kind") != "IngressRoute" or doc["metadata"]["name"] != name:
                    continue
                for route in doc["spec"]["routes"]:
                    if route.get("priority", 0) > 400:
                        self.assertNotIn("/api/app", route["match"],
                                         f"{name}@{route.get('priority')} would shadow the control set")

    def test_edge_publico_cae_en_sso_chain(self):
        """Un caller sin IP LAN/tailnet/cluster que entre por dgx.e-dani.com cae en la regla
        100, que es sso-chain sin lista: /api/app/pagos también queda protegida fuera de casa."""
        route = _route(_docs(EDGE), "edge-dgx-dashboard-public", 100)
        self.assertNotIn("ClientIP", route["match"])
        self.assertIn("sso-chain", [m["name"] for m in route["middlewares"]])

    def test_sso_forward_auth_estampa_email_y_strip_la_vacia(self):
        docs = _docs(ROUTING)
        forward = next(d for d in docs if d.get("kind") == "Middleware"
                       and d["metadata"]["name"] == "sso-forward-auth")
        self.assertIn("X-Auth-Request-Email", forward["spec"]["forwardAuth"]["authResponseHeaders"])
        chain = next(d for d in docs if d.get("kind") == "Middleware"
                     and d["metadata"]["name"] == "sso-chain")
        self.assertEqual([m["name"] for m in chain["spec"]["chain"]["middlewares"]],
                         ["sso-errors", "sso-forward-auth"])
        strip = next(d for d in _docs(LAN) if d.get("kind") == "Middleware"
                     and d["metadata"]["name"] == "dgx-strip-identity-headers")
        self.assertEqual(strip["spec"]["headers"]["customRequestHeaders"]["X-Auth-Request-Email"], "")


if __name__ == "__main__":
    unittest.main()
