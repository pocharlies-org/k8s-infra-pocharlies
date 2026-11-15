"""dgx.app.alarma.v1 (SC-5366): `/alarma` y `/api/app/alarma*` van tras sso-chain también en
traefik-lan (regla 415, por encima de la 300 sin login de DGX-1314), como Nova (420) y
`/api/identidad` (430). `guarda_app` lee la identidad solo del JWT verificado (DGX-807): con la
300, que estampa cabeceras, hasta Dani recibía 403. El borde ya la tenía en su control set (400)."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _ruta(path, name, priority):
    for doc in yaml.safe_load_all(path.read_text()):
        if doc and doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == name:
            for route in doc["spec"]["routes"]:
                if route.get("priority") == priority:
                    return route
    raise AssertionError(f"{path.name}: sin ruta {priority} en {name}")


class AlarmaSSOContract(unittest.TestCase):
    def test_lan_415_alarma_tras_sso_y_prueba_de_borde(self):
        path = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
        route = _ruta(path, "lan-dgx-dashboard-public-host", 415)
        self.assertIn("Path(`/alarma`)", route["match"])
        self.assertIn("PathPrefix(`/api/app/alarma`)", route["match"])
        self.assertNotIn("ClientIP(", route["match"], "vale para todos: también LAN/tailnet")
        self.assertEqual([(m["name"], m.get("namespace", "")) for m in route["middlewares"]],
                         [("dgx-strip-identity-headers", "traefik-lan"), ("sso-chain", "keycloak"),
                          ("dgx-edge-proof", "traefik-lan")])

    def test_borde_sigue_con_alarma_en_el_control_set(self):
        route = _ruta(ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml",
                      "edge-dgx-dashboard-public", 400)
        self.assertIn("PathPrefix(`/api/app/alarma`)", route["match"])


if __name__ == "__main__":
    unittest.main()
