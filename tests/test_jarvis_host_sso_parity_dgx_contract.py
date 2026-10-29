"""DGX-829 (security, F3 de DGX-821): jarvis.e-dani.com y dgx.e-dani.com sirven el mismo backend
(control-nexus/dgx-dashboard-ui) y deben exigir sesión en las mismas rutas desde LAN, tailnet o un pod.

Medido el 12-10-2026: GET https://jarvis.e-dani.com/api/company/control y /api/litellm/keys daban 200
sin sesión, mientras dgx.e-dani.com daba 302 al SSO — el bypass de ClientIP de jarvis (300) no llevaba
el control set que dgx puso tras sso-chain (400) en SC-1192/DGX-809. Este contrato no busca cadenas:
evalúa las reglas de Traefik v3 de los dos hosts, elige la de más prioridad que casa (como Traefik) y
exige que la cadena de middlewares ganadora sea idéntica en ambos para toda petición de la lista.
DGX-1314 (Dani, 27-10): desde casa ya no hay SSO en ninguno de los dos (LAN = Dani, su identidad
estampada); la paridad sigue: misma cadena en los dos hosts.
"""
import pathlib
import unittest

from tests.traefik_rules import cadena as _cadena, gana as _gana, rutas as _rutas_compartidas

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rutas(fichero, nombre):
    return _rutas_compartidas(ROOT, fichero, nombre)

JARVIS = ("networking/traefik-lan/public-panels-lan.yaml", "lan-jarvis-public-host", "jarvis.e-dani.com")
DGX = ("networking/traefik-lan/dgx-public-host-lan.yaml", "lan-dgx-dashboard-public-host", "dgx.e-dani.com")

# LAN, tailnet y pod: los orígenes del bypass.
DE_CASA = ("192.168.50.23", "100.101.102.103", "10.42.3.4")

# Control set: lecturas que dgx ya protege (regla 400 de lan-dgx-dashboard-public-host).
CONTROL_SET = [("GET", p) for p in (
    "/api/company/control", "/api/company/entregas", "/api/litellm/keys", "/api/litellm/config",
    "/api/messages", "/api/autoreply", "/api/claude-sessions", "/api/hermes-sessions",
    "/api/app/secure/x",
    "/api/app/pagos/lista", "/api/app/alarma/estado", "/api/app/push/token", "/api/email/state",
    "/entregas", "/static/entregas/app.js", "/api/model-routing", "/api/hermes-panel",
    "/api/secretaria/despacho/temas", "/despacho-secretaria",
)]
# Escrituras del backend (regla 350): solo por POST; los GET de esas rutas se compran abajo, abiertos.
ESCRITURAS = [("POST", p) for p in (
    "/api/cluster/apply", "/api/cluster/refresh", "/api/compute/mode", "/api/activity/power",
    "/api/llm/uncensored", "/api/llm/dgx3/mode",
    "/api/litellm/background-consumers/aurora-rca/block",
    "/api/litellm/background-consumers/aurora-rca/unblock",
)]
# Máquina a máquina con HMAC propio: debe seguir cayendo en el bypass en los dos hosts.
MAQUINA = [
    ("POST", "/api/secretaria/despacho/escalar"),
    ("POST", "/api/secretaria/despacho/secretaria-dani/escalar"),
    ("POST", "/api/alarma/estado"), ("POST", "/api/pagos/x"),
    ("POST", "/api/activity/claude/refresh"),  # F1: extensión vscode-claude-cuenta, sin sesión
]
# Lecturas que la app usa sin sesión (fixtures de dgx-infra): abiertas en los dos hosts.
LECTURAS_ABIERTAS = [("GET", p) for p in (
    "/api/activity", "/api/activity/stream", "/api/compute/mode", "/api/llm/uncensored",
    "/api/llm/dgx3/mode",
    "/api/litellm/consumers", "/api/litellm/models",
    "/api/litellm/background-consumers", "/api/cluster/llm/resident-profile",
    "/api/hud/jarvis", "/api/jarvis/latency", "/api/service-health",
)]
# INFRA-732: rutas internas — 404 en el borde (edge-static-server) en los dos hosts, nunca al backend.
INTERNO = [("GET", "/api/interno/ping")]


class ParidadJarvisConDgx(unittest.TestCase):
    def _peticiones(self):
        rutas_j = _rutas(*JARVIS[:2])
        rutas_d = _rutas(*DGX[:2])
        for ip in DE_CASA:
            for method, path in CONTROL_SET + ESCRITURAS + MAQUINA + LECTURAS_ABIERTAS + INTERNO:
                yield (f"{method} {path} desde {ip}",
                       _gana(rutas_j, JARVIS[2], ip, method, path),
                       _gana(rutas_d, DGX[2], ip, method, path))

    def test_misma_cadena_de_middlewares_que_dgx(self):
        """Lo que en dgx va tras sso-chain va tras sso-chain en jarvis; lo abierto, abierto en los dos.

        Sobre el mismo service en los dos hosts (el backend compartido dgx-dashboard-ui, o el
        edge-static-server de /api/interno) la cadena ganadora debe ser idéntica. Donde dgx enruta a un
        service propio (/api/messages → dgx-messages, regla 460) se exige que los dos hosts lleven la
        identidad de Dani y ninguno sso-chain: la paridad es de protección, no de enrutado."""
        for caso, ruta_j, ruta_d in self._peticiones():
            with self.subTest(caso):
                self.assertIsNotNone(ruta_j, caso)
                self.assertIsNotNone(ruta_d, caso)
                if ruta_j.get("services") == ruta_d.get("services"):
                    self.assertEqual(_cadena(ruta_j), _cadena(ruta_d),
                                     f"{caso}: jarvis y dgx no sirven la misma cadena")
                else:
                    for ruta in (ruta_j, ruta_d):
                        self.assertIn(("dgx-lan-identidad-dani", "traefik-lan"), _cadena(ruta), caso)
                        self.assertNotIn(("sso-chain", "keycloak"), _cadena(ruta), caso)

    def test_lecturas_del_hallazgo_van_como_dani_desde_casa(self):
        """DGX-829 las puso tras sso-chain; DGX-1314: desde casa, con la identidad de Dani y sin login."""
        rutas = _rutas(*JARVIS[:2])
        for ip in DE_CASA:
            for path in ("/api/company/control", "/api/litellm/keys"):
                with self.subTest(f"{path} desde {ip}"):
                    cadena = _cadena(_gana(rutas, JARVIS[2], ip, "GET", path))
                    self.assertEqual(cadena, [("dgx-lan-identidad-dani", "traefik-lan"),
                                              ("dgx-edge-proof", "traefik-lan")])

    def test_el_hud_sigue_sin_sesion(self):
        """El HUD de jarvis (la 400) es lo único propio del host: sigue abierto, con strip y prueba."""
        rutas = _rutas(*JARVIS[:2])
        for path in ("/", "/jarvis", "/jarvis.html"):
            with self.subTest(path):
                ruta = _gana(rutas, JARVIS[2], "192.168.50.23", "GET", path)
                self.assertEqual(ruta.get("priority"), 400)
                self.assertNotIn(("sso-chain", "keycloak"), _cadena(ruta))


if __name__ == "__main__":
    unittest.main()
