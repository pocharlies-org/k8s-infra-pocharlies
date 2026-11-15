"""DGX-1113: el logout del SSO del dashboard funciona en los hosts dgx.

La página 403 de oauth2-proxy enlaza «Sign Out» a /oauth2/sign_out del host actual.
En dgx.e-dani.com / dgx.lan.e-dani.com no existía ruta /oauth2: en LAN caía al bypass
(300) → dashboard → 404, y en el edge a la pública (100) → sso-chain → bucle. Sin salida
del 403, un login con la cuenta equivocada era irreversible. Además, sin prompt=login
Keycloak re-autenticaba en silencio con la misma sesión y se volvía al 403.

Este test fija, sobre los tres ficheros que poseen el arreglo:

  - networking/traefik-lan/dgx-public-host-lan.yaml   (ruta /oauth2 → keycloak/oauth2-proxy)
  - networking/traefik-edge/dgx-dashboard-public.yaml (ruta /oauth2 → edge-oauth2-proxy ExternalName)
  - platform/keycloak-next/oauth2-proxy.yaml          (login_url con prompt=login)
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAN = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
EDGE = ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml"
PROXY = ROOT / "platform" / "keycloak-next" / "oauth2-proxy.yaml"


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _oauth2_route(docs, route_name):
    for doc in docs:
        if doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == route_name:
            for route in doc["spec"]["routes"]:
                if "PathPrefix(`/oauth2`)" in route["match"]:
                    return route
    raise AssertionError(f"{route_name}: no route for /oauth2")


class DgxOauth2SignoutContract(unittest.TestCase):
    def test_lan_ruta_oauth2_sin_cadena_hacia_el_proxy(self):
        route = _oauth2_route(_docs(LAN), "lan-dgx-dashboard-public-host")
        self.assertNotIn("ClientIP", route["match"],
                         "el sign_out debe funcionar también desde internet por el host LAN")
        self.assertEqual(route.get("middlewares", []), [],
                         "/oauth2 con sso-chain = autenticarse exigiría estar autenticado")
        svc = route["services"][0]
        self.assertEqual((svc["name"], svc["namespace"], svc["port"]),
                         ("oauth2-proxy", "keycloak", 4180))
        self.assertGreater(route["priority"], 400, "debe quedar por delante del control set")

    def test_edge_ruta_oauth2_sin_cadena_hacia_el_proxy(self):
        docs = _docs(EDGE)
        route = _oauth2_route(docs, "edge-dgx-dashboard-public")
        self.assertEqual(route.get("middlewares", []), [])
        svc = route["services"][0]
        self.assertEqual(svc["name"], "edge-oauth2-proxy")
        self.assertGreater(route["priority"], 400)
        ext = [d for d in docs
               if d.get("kind") == "Service" and d["metadata"]["name"] == "edge-oauth2-proxy"]
        self.assertEqual(len(ext), 1, "el edge necesita el ExternalName del proxy compartido")
        self.assertEqual(ext[0]["spec"]["externalName"], "oauth2-proxy.keycloak.svc.cluster.local")

    def test_proxy_compartido_pide_credenciales_en_cada_login(self):
        docs = _docs(PROXY)
        cm = next(d for d in docs
                  if d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "oauth2-proxy-config")
        cfg = cm["data"]["oauth2_proxy.cfg"]
        login_line = [l for l in cfg.splitlines() if l.strip().startswith("login_url")]
        self.assertEqual(len(login_line), 1)
        self.assertIn("prompt=login", login_line[0],
                      "sin prompt=login Keycloak re-autentifica en silencio con la cuenta equivocada")

    def test_deployment_relee_el_cfg(self):
        """oauth2-proxy solo lee el .cfg al arrancar: el config-rev tiene que subir con él."""
        docs = _docs(PROXY)
        dep = next(d for d in docs if d.get("kind") == "Deployment")
        rev = dep["spec"]["template"]["metadata"]["annotations"]["e-dani.com/config-rev"]
        self.assertTrue(rev.startswith("2026-10-19"), f"config-rev sin subir: {rev}")


if __name__ == "__main__":
    unittest.main()
