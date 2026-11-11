"""dgx.app.pagos.v1 (03-10-2026): las rutas de la app DGX de pagos pasan SIEMPRE por
oauth2-proxy en el edge, y las de máquina se quedan públicas en LAN por diseño
(HMAC V2 propio, no SSO). DGX-1314 (Dani, 27-10): en LAN no hay SSO, LAN = Dani: la 300
estampa su identidad (dgx-lan-identidad-dani), que `es_dani` y guarda_cluster aceptan.

El backend exige `es_dani` sobre la cabecera `X-Auth-Request-Email`. Esa cabecera solo vale
si la estampa el forwardAuth de oauth2-proxy (`sso-forward-auth.authResponseHeaders`): en la
ruta abierta de prioridad 300 la cabecera viaja VACIADA por `dgx-strip-identity-headers`
(SC-1191), así que ni la app funciona por ahí ni un forged de identidad sirve. Este test fija
la cadena completa sobre los dos ficheros que poseen las rutas:

  - networking/traefik-lan/dgx-public-host-lan.yaml  (IngressRoute lan-dgx-dashboard-public-host)
  - networking/traefik-edge/dgx-dashboard-public.yaml (IngressRoute edge-dgx-dashboard-public)
"""
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAN = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
EDGE = ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml"
ROUTING = ROOT / "platform" / "keycloak-next" / "routing.yaml"

# DGX-674 (security C1): /api/app/alarma* (SSO + lista de emails en el backend) entra igual que
# pagos; /api/alarma* es la ruta de maquina (HMAC V2) y NO entra, como /api/pagos*.
# SC-2175 (security): /api/hermes-panel* (dgx.panel.hermes.v1) entra igual: su backend da 401 sin la cabecera.
APP_PREFIXES = ("PathPrefix(`/api/app/pagos`)", "PathPrefix(`/api/app/push`)",
                "PathPrefix(`/api/app/alarma`)", "PathPrefix(`/api/hermes-panel`)")


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
        self.assertNotIn("PathPrefix(`/api/alarma`)", match)
        self.assertNotIn("Path(`/api/alarma`)", match)
        # DGX-729: la prueba de borde va al final de la cadena; el strip solo vacía las
        # 7 de identidad, nunca X-Edge-Proof, así que el proof sobrevive al strip.
        chain = [(m["name"], m.get("namespace", "")) for m in route["middlewares"]]
        self.assertEqual(chain, [("dgx-strip-identity-headers", ns), ("sso-chain", "keycloak"),
                                 ("dgx-edge-proof", ns)],
                         f"{name}@{priority}: strip first, then sso-chain, then edge-proof")

    def test_lan_300_estampa_la_identidad_de_dani(self):
        """DGX-1314: sin control set en LAN; la 300 lleva la identidad de Dani y la prueba de borde."""
        docs = _docs(LAN)
        route = _route(docs, "lan-dgx-dashboard-public-host", 300)
        chain = [(m["name"], m.get("namespace", "")) for m in route["middlewares"]]
        self.assertEqual(chain, [("dgx-lan-identidad-dani", "traefik-lan"), ("dgx-edge-proof", "traefik-lan")])
        mw = next(d for d in docs if d.get("kind") == "Middleware" and d["metadata"]["name"] == "dgx-lan-identidad-dani")
        cab = mw["spec"]["headers"]["customRequestHeaders"]
        self.assertEqual(cab["X-Auth-Request-Email"], "me@e-dani.com")  # en SECRETARIA_DANI_EMAILS (es_dani)
        self.assertIn("/edani-admins", cab["X-Auth-Request-Groups"].split(","))  # guarda_cluster
        # sobrescribe las mismas 7 cabeceras que vacía el strip: nada forjado pasa tal cual
        strip = next(d for d in docs if d.get("kind") == "Middleware" and d["metadata"]["name"] == "dgx-strip-identity-headers")
        self.assertEqual(set(cab), set(strip["spec"]["headers"]["customRequestHeaders"]))

    def test_edge_400_protege_app_pagos_push_y_alarma(self):
        self._assert_protected(_docs(EDGE), "edge-dgx-dashboard-public", 400, "traefik-edge")

    def test_ninguna_ruta_de_mas_prioridad_cubre_api_app(self):
        """Arriba del 400 ninguna regla puede llevarse /api/app/* SIN exigir sesión.

        Lo que se prohíbe es el bypass: una regla de más prioridad que se lleve la superficie de la
        app sin `sso-chain` la dejaría en la 300 de DGX-1314 (identidad estampada, sin JWT). SC-5366
        añade la 415 de la LAN, que cubre `/api/app/alarma` justamente para exigir sso-chain (su
        guarda lee solo el JWT verificado, DGX-807): no sombrea el control set, lo refuerza."""
        for docs, name in ((_docs(LAN), "lan-dgx-dashboard-public-host"),
                           (_docs(EDGE), "edge-dgx-dashboard-public")):
            for doc in docs:
                if doc.get("kind") != "IngressRoute" or doc["metadata"]["name"] != name:
                    continue
                for route in doc["spec"]["routes"]:
                    if route.get("priority", 0) > 400:
                        if "sso-chain" in [m["name"] for m in route.get("middlewares", [])]:
                            continue
                        for prefix in ("/api/app", "/api/hermes-panel"):
                            self.assertNotIn(prefix, route["match"],
                                             f"{name}@{route.get('priority')} would shadow the control set")

    def test_edge_publico_cae_en_sso_chain(self):
        """Un caller sin IP LAN/tailnet/cluster que entre por dgx.e-dani.com cae en la regla
        100, que es sso-chain sin lista: /api/app/pagos también queda protegida fuera de casa."""
        route = _route(_docs(EDGE), "edge-dgx-dashboard-public", 100)
        self.assertNotIn("ClientIP", route["match"])
        self.assertIn("sso-chain", [m["name"] for m in route["middlewares"]])

    def test_api_alarma_de_maquina_cae_en_el_bypass_lan_y_en_sso_por_el_borde(self):
        """/api/alarma* (HMAC) no tiene regla propia: desde LAN/tailnet/cluster llega al backend
        por la 300 de la LAN (LAN = Dani, DGX-1314; la guarda pide HMAC). DGX-809 (spec PM
        04-11): el borde ya no tiene bypass de casa (fuera la 200), asi que por el borde
        /api/alarma pide sesion desde cualquier IP; la maquina de casa llama por AdGuard ->
        traefik-lan o por el Service interno."""
        path = "/api/alarma/estado"
        docs, name, bypass = _docs(LAN), "lan-dgx-dashboard-public-host", 300
        self.assertNotIn("Path", _route(docs, name, bypass)["match"], f"{name}@{bypass} is the open bypass")
        for doc in docs:
            if doc.get("kind") != "IngressRoute" or doc["metadata"]["name"] != name:
                continue
            for route in doc["spec"]["routes"]:
                if route.get("priority", 0) <= bypass:
                    continue
                m = route["match"]
                for prefix in re.findall(r"PathPrefix\(`([^`]+)`\)", m):
                    self.assertFalse(path.startswith(prefix),
                                     f"{name}@{route['priority']} captures {path} via {prefix}")
                for exact in re.findall(r"\bPath\(`([^`]+)`\)", m):
                    self.assertNotEqual(path, exact, f"{name}@{route['priority']} captures {path}")
                for rx in re.findall(r"PathRegexp\(`([^`]+)`\)", m):
                    self.assertIsNone(re.search(rx, path), f"{name}@{route['priority']} captures {path}")
        # DGX-809: en el borde no queda ninguna regla de bypass y la ganadora es la 100 con sso-chain.
        for doc in _docs(EDGE):
            if doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == "edge-dgx-dashboard-public":
                self.assertNotIn(200, [r.get("priority") for r in doc["spec"]["routes"]],
                                 "DGX-809: el borde ya no tiene bypass de casa (200)")

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
