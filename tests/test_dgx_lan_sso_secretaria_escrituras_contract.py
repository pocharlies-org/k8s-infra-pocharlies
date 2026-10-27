"""DGX-809: qué ruta del backend del panel exige sesión cuando se llega desde LAN, tailnet o un pod.

Security H-2 (DGX-799): POST /api/activity/power, /api/llm/uncensored y /api/litellm/opencode/reload
llegaban al backend sin sesión por el bypass de ClientIP. POST /api/activity/claude/refresh se queda
abierto (F1 de security sobre la PR #277: lo llama sin sesión la extensión vscode-claude-cuenta del x86).
Security S1 (DGX-800): /api/secretaria entera y la página /despacho-secretaria igual, salvo
POST /api/secretaria/despacho[/<perfil>]/escalar (máquina a máquina con HMAC V2).

El test no busca cadenas: evalúa las reglas de Traefik v3 de cada IngressRoute que sirve el backend
con bypass (dgx y s3 en LAN y edge, y jarvis en LAN) para una petición concreta, elige la de más
prioridad que casa, como Traefik, y mira su cadena de middlewares. Así cubre el método, la negación
de /escalar y que las lecturas que la app usa sin sesión siguen cayendo en el bypass.
Toda cadena acaba en dgx-edge-proof (DGX-729): la prueba de borde va en cada ruta al dashboard.
"""
import pathlib
import unittest

from tests.traefik_rules import gana as _gana, rutas as _rutas_compartidas

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _rutas(fichero, nombre):
    return _rutas_compartidas(ROOT, fichero, nombre)

# (fichero, IngressRoute, hosts, namespace de dgx-strip-identity-headers)
RUTAS = (
    ("networking/traefik-lan/dgx-public-host-lan.yaml", "lan-dgx-dashboard-public-host",
     ("dgx.e-dani.com", "dgx.lan.e-dani.com"), "traefik-lan"),
    ("networking/traefik-lan/dgx-public-host-lan.yaml", "lan-dgx-s3-media-public-host",
     ("s3.e-dani.com",), "traefik-lan"),
    ("networking/traefik-edge/dgx-dashboard-public.yaml", "edge-dgx-dashboard-public",
     ("dgx.e-dani.com",), "traefik-edge"),
    ("networking/traefik-edge/s3-media-public.yaml", "edge-dgx-s3-media-public",
     ("s3.e-dani.com",), "traefik-edge"),
    ("networking/traefik-lan/public-panels-lan.yaml", "lan-jarvis-public-host",
     ("jarvis.e-dani.com",), "traefik-lan"),
)
# LAN, tailnet y pod: los orígenes del bypass.
DE_CASA = ("192.168.50.23", "100.101.102.103", "10.42.3.4")
PERFILES = ("secretaria", "secretaria-dani", "secretaria-leila", "secretaria-casa")

ESCRITURAS = [("POST", p) for p in ("/api/activity/power", "/api/llm/uncensored",
                                     "/api/llm/dgx3/mode")]  # DGX-1054: el mando LLM|creative de dgx3
SECRETARIA = [
    ("GET", "/despacho-secretaria"),
    ("GET", "/api/secretaria/despacho/temas"),
    ("GET", "/api/secretaria/despacho/resumen"),
    ("GET", "/api/secretaria/despacho/temas/resolver"),
    ("POST", "/api/secretaria/despacho/chat"),
    ("GET", "/api/secretaria/despacho/acciones"),
    ("POST", "/api/secretaria/despacho/acciones"),
    ("POST", "/api/secretaria/despacho/acciones/ACC-1/sesion/ver"),
    ("POST", "/api/secretaria/despacho/acciones/ACC-1/respuesta"),
    # «acciones» no es un perfil: la excepción de /escalar no la cubre.
    ("POST", "/api/secretaria/despacho/acciones/escalar"),
] + [m_p for perfil in PERFILES for m_p in (
    ("GET", f"/api/secretaria/despacho/{perfil}/temas"),
    ("GET", f"/api/secretaria/despacho/{perfil}/temas/sid-1/mensajes"),
    ("PATCH", f"/api/secretaria/despacho/{perfil}/temas/sid-1"),
    ("DELETE", f"/api/secretaria/despacho/{perfil}/temas/sid-1"),
    ("POST", f"/api/secretaria/despacho/{perfil}/adjuntos"),
)]
# INFRA-832 (#280): POST block/unblock de background-consumers tras SSO en las tres IngressRoute que
# tocó (dgx en LAN y edge, s3 en LAN); su GET sigue abierto. Aquí para que un merge no las pierda.
INFRA_832 = ("lan-dgx-dashboard-public-host", "lan-dgx-s3-media-public-host", "edge-dgx-dashboard-public")
BACKGROUND_CONSUMERS = [("POST", f"/api/litellm/background-consumers/aurora-rca/{a}") for a in ("block", "unblock")]
ESCALAR = [("POST", "/api/secretaria/despacho/escalar")] + [
    ("POST", f"/api/secretaria/despacho/{perfil}/escalar") for perfil in PERFILES]

# Lo que se usa sin sesión desde casa y DGX-809 no toca: los GET de las escrituras (A4, A9, A10 de
# nota-security-escrituras-app.md), POST /api/activity/claude/refresh (F1) y las rutas abiertas de
# services/dashboard/tests/fixtures/app_endpoints.json de dgx-infra (master 8f0605ec). Las del
# fixture que ya iban tras SSO (/api/company, /api/claude-sessions, /api/messages…) no están.
LECTURAS_ABIERTAS = [("GET", p) for p in (
    "/api/llm/uncensored", "/api/activity", "/api/activity/stream", "/api/activity/claude",
    "/api/alibaba/accounts", "/api/alibaba/catalog", "/api/alibaba/quota",
    "/api/alibaba/uso-clase", "/api/app/build", "/api/app/screens", "/api/app/screens/inferencia",
    "/api/cluster/llm/resident-profile", "/api/compute/batch", "/api/compute/mode",
    "/api/llm/dgx3/mode",  # DGX-1054: el GET del mando sigue abierto
    "/api/creative/images", "/api/creative/jobs", "/api/hud/jarvis", "/api/image/queue-size",
    "/api/inference/traffic", "/api/inference/traffic/alibaba", "/api/jarvis/latency",
    "/api/litellm/consumers", "/api/litellm/openrouter/account", "/api/litellm/uso-perfiles",
    "/api/litellm/models", "/api/llm/company", "/api/llm/hold-preguntas", "/api/llm/live",
    "/api/llm/refusal-rates", "/api/llm/refusal-rates/series", "/api/llm/series", "/api/llm/sessions",
    "/api/pages", "/api/service-health", "/api/studio/gallery",
    "/api/litellm/background-consumers",  # INFRA-832: el GET sigue abierto
)] + [("POST", "/api/alarma/estado"), ("POST", "/api/pagos/x"),  # máquina con HMAC: siguen abiertas
      ("POST", "/api/llm/dgx3/mode/machine"),  # DGX-1095: la ventana de dgx3 sin navegador (HMAC V2); el web, tras SSO
      ("POST", "/api/activity/claude/refresh")]  # F1: extensión vscode-claude-cuenta, sin sesión


class SecretariaYEscriturasTrasSSO(unittest.TestCase):
    def _cada_peticion(self, peticiones, ips=DE_CASA, solo=None):
        for fichero, nombre, hosts, ns in RUTAS:
            if solo and nombre not in solo:
                continue
            rutas = _rutas(fichero, nombre)
            for host in hosts:
                for ip in ips:
                    for method, path in peticiones:
                        ruta = _gana(rutas, host, ip, method, path)
                        yield f"{nombre} {host} {ip} {method} {path}", ruta, ns

    def _cadena(self, ruta):
        return [(m["name"], m.get("namespace", "")) for m in (ruta or {}).get("middlewares", [])]

    def test_escrituras_y_secretaria_exigen_sesion_desde_casa(self):
        for caso, ruta, ns in [*self._cada_peticion(ESCRITURAS + SECRETARIA),
                               *self._cada_peticion(BACKGROUND_CONSUMERS, solo=INFRA_832)]:
            with self.subTest(caso):
                self.assertIsNotNone(ruta, caso)
                self.assertEqual(self._cadena(ruta), [("dgx-strip-identity-headers", ns), ("sso-chain", "keycloak"),
                                                      ("dgx-edge-proof", ns)],
                                 f"{caso}: primero se vacía la identidad, luego sso-chain y al final la prueba de borde")

    def test_escalar_de_maquina_cae_en_el_bypass(self):
        for caso, ruta, ns in self._cada_peticion(ESCALAR):
            with self.subTest(caso):
                self.assertEqual(self._cadena(ruta), [("dgx-strip-identity-headers", ns), ("dgx-edge-proof", ns)], caso)

    def test_lecturas_de_la_app_sin_sesion_siguen_abiertas(self):
        for caso, ruta, ns in self._cada_peticion(LECTURAS_ABIERTAS):
            with self.subTest(caso):
                self.assertEqual(self._cadena(ruta), [("dgx-strip-identity-headers", ns), ("dgx-edge-proof", ns)], caso)

    def test_desde_fuera_todo_sigue_tras_sso(self):
        """Por el edge, desde una IP pública, todo va a la regla 100 (sso-chain), /escalar incluida."""
        for fichero, nombre, hosts, ns in RUTAS:
            if "traefik-edge" not in fichero:
                continue
            rutas = _rutas(fichero, nombre)
            for method, path in ESCRITURAS + BACKGROUND_CONSUMERS + SECRETARIA + ESCALAR + LECTURAS_ABIERTAS:
                with self.subTest(f"{nombre} {method} {path}"):
                    ruta = _gana(rutas, hosts[0], "203.0.113.9", method, path)
                    self.assertEqual(ruta.get("priority"), 100)
                    self.assertIn(("sso-chain", "keycloak"), self._cadena(ruta))


if __name__ == "__main__":
    unittest.main()
