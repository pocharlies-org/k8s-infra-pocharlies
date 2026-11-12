"""INFRA-1321: las escrituras del panel que autorizan con el JWT verificado necesitan sso-chain
también desde la LAN.

Medido el 12-11-2026: PUT /api/company/control/cuenta-reset desde la LAN → 403
`not_company_operator`. La ruta ClientIP (300) estampa la identidad en cabeceras planas
(`dgx-lan-identidad-dani`) y no lleva Bearer; desde DGX-807 el backend autoriza solo con el JWT
que inyecta sso-chain. DGX-1539 (Dani, 12-11): las lecturas de control suben también — GET
/api/company/control devuelve `puede_operar` y sin Bearer sale false para todos: el configurador
se apagaba entero («tu usuario solo puede mirar»). La telemetría (/api/activity…) sigue en la 300.
"""
import pathlib
import unittest

from tests.traefik_rules import cadena as _cadena, gana as _gana, rutas as _rutas

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOSTS = (
    ("networking/traefik-lan/dgx-public-host-lan.yaml", "lan-dgx-dashboard-public-host", "dgx.e-dani.com"),
    ("networking/traefik-lan/public-panels-lan.yaml", "lan-jarvis-public-host", "jarvis.e-dani.com"),
)
DE_CASA = ("192.168.50.23", "100.101.102.103", "10.42.3.4")
ESCRITURAS = [("PUT", "/api/company/control/cuenta-reset"), ("POST", "/api/company/control/on"),
              ("POST", "/api/model-routing/override")]
SSO = [("dgx-strip-identity-headers", "traefik-lan"), ("sso-chain", "keycloak"),
       ("dgx-edge-proof", "traefik-lan")]
ESTAMPA = [("dgx-lan-identidad-dani", "traefik-lan"), ("dgx-edge-proof", "traefik-lan")]


class EscriturasDelPanelDesdeCasa(unittest.TestCase):
    def test_escrituras_del_panel_van_tras_sso_chain(self):
        for fichero, nombre, host in HOSTS:
            rutas = _rutas(ROOT, fichero, nombre)
            for ip in DE_CASA:
                for method, path in ESCRITURAS:
                    with self.subTest(f"{nombre} {method} {path} desde {ip}"):
                        self.assertEqual(_cadena(_gana(rutas, host, ip, method, path)), SSO)

    def test_las_lecturas_de_telemetria_siguen_sin_login(self):
        """DGX-1314 sigue para lo que no autoriza: la telemetría no pide sesión desde casa. Las
        lecturas de control subieron con DGX-1539 (llevan `puede_operar`, solo del Bearer)."""
        for fichero, nombre, host in HOSTS:
            rutas = _rutas(ROOT, fichero, nombre)
            for ip in DE_CASA:
                for path in ("/api/company/control", "/api/model-routing"):
                    with self.subTest(f"{nombre} GET {path} desde {ip}"):
                        self.assertEqual(_cadena(_gana(rutas, host, ip, "GET", path)), SSO)
                for path in ("/api/activity",):
                    with self.subTest(f"{nombre} GET {path} desde {ip}"):
                        self.assertEqual(_cadena(_gana(rutas, host, ip, "GET", path)), ESTAMPA)