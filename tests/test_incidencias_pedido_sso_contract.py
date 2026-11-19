"""DGX-1707: la tarjeta del pedido de /incidencias exige identidad, y solo esa ruta.

El dashboard no guarda credencial de Shopify: reenvía al BFF del Control Panel la identidad del
token VERIFICADO. Esa identidad solo existe en una petición que pasó por oauth2-proxy, así que el
prefijo del pedido entra en el control set (prioridad 400) de los dos ficheros que poseen las rutas
del host: el transcript y su SSE siguen en el bypass abierto, a propósito.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAN = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
EDGE = ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml"
PREFIX = "PathPrefix(`/api/skirmshop/incidencias/caso/pedido`)"


def _route(path, name, priority):
    for doc in yaml.safe_load_all(path.read_text()):
        if doc and doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == name:
            for route in doc["spec"]["routes"]:
                if route.get("priority") == priority:
                    return route
    raise AssertionError(f"route {name}@{priority} not found")


class PedidoSSOContract(unittest.TestCase):
    def test_lan_y_edge_400_protegen_el_pedido(self):
        for path, name in ((LAN, "lan-dgx-dashboard-public-host"),
                           (EDGE, "edge-dgx-dashboard-public")):
            route = _route(path, name, 400)
            self.assertIn(PREFIX, route["match"])
            chain = [m["name"] for m in route["middlewares"]]
            self.assertEqual(chain, ["dgx-strip-identity-headers", "sso-chain", "dgx-edge-proof"],
                             f"{name}@400: strip, sso-chain y prueba de borde")

    def test_el_transcript_sigue_abierto(self):
        """La página y su API de caso NO entran en el control set: se usa desde la LAN sin login."""
        for path, name in ((LAN, "lan-dgx-dashboard-public-host"),
                           (EDGE, "edge-dgx-dashboard-public")):
            match = _route(path, name, 400)["match"]
            self.assertNotIn("/api/skirmshop/incidencias/caso/messages", match)
            self.assertNotIn("PathPrefix(`/api/skirmshop/incidencias`)", match)
