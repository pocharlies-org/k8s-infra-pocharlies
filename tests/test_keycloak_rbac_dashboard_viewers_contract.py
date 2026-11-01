"""/dashboard-viewers: acceso de SOLO VER al panel (01-11-2026, lección del acceso temporal de Jordi).

El proxy compartido del panel deja entrar a este grupo, pero no le abre ninguna escritura: los POST
del panel siguen exigiendo sesión por el borde (sso-chain) y el backend pide `/edani-admins`
(guarda_cluster.py de dgx-infra). Desde casa las escrituras caen en la cadena LAN_DANI (DGX-1314:
LAN = Dani), que tampoco depende de este grupo.

Dos bordes del contrato:
* `allowed_groups` del proxy = exactamente admins + operators + dashboard-viewers (la puerta de login);
* el grupo no aparece en ningún otro manifiesto (no puede acabar habilitando nada más), y las
  escrituras desde fuera siguen detrás de sso-chain igual que sin él.
"""
import pathlib
import unittest

import yaml

from tests.traefik_rules import gana as _gana, rutas as _rutas_compartidas
from tests.test_dgx_lan_sso_secretaria_escrituras_contract import BACKGROUND_CONSUMERS, ESCRITURAS

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROXY = "platform/keycloak-next/oauth2-proxy.yaml"
# (fichero, IngressRoute, host) del borde público del panel.
EDGE = (
    ("networking/traefik-edge/dgx-dashboard-public.yaml", "edge-dgx-dashboard-public", "dgx.e-dani.com"),
    ("networking/traefik-edge/s3-media-public.yaml", "edge-dgx-s3-media-public", "s3.e-dani.com"),
)


def _cfg():
    docs = yaml.safe_load_all((ROOT / PROXY).read_text(encoding="utf-8"))
    for d in docs:
        if d and d.get("kind") == "ConfigMap" and d["metadata"]["name"] == "oauth2-proxy-config":
            cfg = {}
            for line in d["data"]["oauth2_proxy.cfg"].splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    cfg[key.strip()] = value.strip()
            return cfg
    raise AssertionError(f"{PROXY}: falta el ConfigMap oauth2-proxy-config")


class DashboardViewers(unittest.TestCase):
    def test_allowed_groups_del_proxy_incluye_el_grupo_de_lectura(self):
        self.assertEqual(_cfg()["allowed_groups"],
                         '[ "/edani-admins", "/edani-operators", "/dashboard-viewers" ]')

    def test_el_grupo_no_habilita_nada_fuera_del_proxy(self):
        """Drift: /dashboard-viewers solo puede vivir en el cfg del proxy. Un grep en cualquier otro
        manifiesto (middlewares, whitelists, chains) significaría que alguien le dio un permiso más."""
        for path in sorted((ROOT / "networking").rglob("*.yaml")) + sorted((ROOT / "platform").rglob("*.yaml")):
            if path.relative_to(ROOT).as_posix() == PROXY:
                continue
            with self.subTest(path.relative_to(ROOT).as_posix()):
                self.assertNotIn("/dashboard-viewers", path.read_text(encoding="utf-8"),
                                 f"{path}: el grupo de solo ver aparece fuera del oauth2-proxy")

    def test_escrituras_siguen_exigiendo_sesion_desde_fuera(self):
        """Con viewers en allowed_groups, un POST público sigue cayendo en la regla 100 con sso-chain:
        la sesión no basta — el backend pide /edani-admins (guarda_cluster)."""
        for fichero, nombre, host in EDGE:
            rutas = _rutas_compartidas(ROOT, fichero, nombre)
            for method, path in ESCRITURAS + BACKGROUND_CONSUMERS:
                with self.subTest(f"{nombre} {method} {path}"):
                    ruta = _gana(rutas, host, "203.0.113.9", method, path)
                    self.assertEqual(ruta.get("priority"), 100)
                    self.assertIn(("sso-chain", "keycloak"),
                                  [(m["name"], m.get("namespace", "")) for m in ruta["middlewares"]])


if __name__ == "__main__":
    unittest.main()
