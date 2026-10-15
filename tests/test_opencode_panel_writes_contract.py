"""SC-2312 (security, 15-10-2026): las escrituras del panel de cuentas de
opencode-claude (:8799, code.e-dani.com/claude) no pueden llegar al backend sin
autenticar.

Medido el 11-10: la ruta LAN code.e-dani.com/claude (prioridad 400) no llevaba
sso-chain, y el plugin dejaba pasar cualquier petición sin cabecera Origin
(curl desde la LAN, la tailnet o un pod) a POST /accounts, DELETE /accounts/<id>
y compañía. Desde un pod del clúster se podía añadir, borrar o re-defaultar una
cuenta de suscripción.

Este test fija, sobre los dos manifiestos del panel:
  * toda ruta que NO sea el bypass GET-only documentado de claude.e-dani.com
    lleva sso-chain (namespace keycloak) — sin sesión no hay escritura;
  * y lleva dgx-edge-proof (DGX-729): el plugin (src/proxy.ts,
    authorizeMutation) rechaza con 401 toda mutación cuyo socket no sea
    loopback si no trae la prueba, y Traefik la inyecta por forwardAuth;
  * el bypass de lectura sigue siendo GET-only (Method(`GET`) en el match), que
    es lo que garantiza que ninguna escritura se lo lleva por delante.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
PANELS = {
    "traefik-lan": ROOT / "networking" / "traefik-lan" / "opencode-claude-panel-lan.yaml",
    "traefik-edge": ROOT / "networking" / "traefik-edge" / "opencode-claude-panel-public.yaml",
}


def _ingressroutes(path):
    return [
        d
        for d in yaml.safe_load_all(path.read_text())
        if d and d.get("kind") == "IngressRoute"
    ]


def _mw_names(route):
    return [(m.get("namespace", ""), m["name"]) for m in route.get("middlewares", [])]


class OpencodePanelWritesContract(unittest.TestCase):
    def test_toda_ruta_de_escritura_lleva_sso_y_prueba(self):
        for ns, path in PANELS.items():
            routes = [
                r
                for ir in _ingressroutes(path)
                for r in ir["spec"]["routes"]
            ]
            self.assertTrue(routes, f"{ns}: el panel tiene rutas")
            for route in routes:
                match = route["match"]
                names = _mw_names(route)
                get_only = "Method(`GET`)" in match
                if not get_only:
                    self.assertIn(
                        ("keycloak", "sso-chain"),
                        names,
                        f"{ns}: ruta sin sso-chain (escrituras sin sesión): {match}",
                    )
                    # El bypass GET-only no la necesita: el plugin solo exige la
                    # prueba en mutaciones (authorizeMutation).
                    self.assertIn(
                        ("", "dgx-edge-proof"),
                        names,
                        f"{ns}: ruta sin prueba de borde DGX-729: {match}",
                    )

    def test_bypass_de_lectura_sigue_get_only(self):
        routes = [
            r
            for ir in _ingressroutes(PANELS["traefik-lan"])
            for r in ir["spec"]["routes"]
            if "Method(`GET`)" in r["match"]
        ]
        self.assertTrue(routes, "el bypass GET-only de cuota sigue existiendo")
        for route in routes:
            self.assertNotIn(
                "sso-chain",
                str(route.get("middlewares", [])),
                "el bypass es de lectura; si aceptara escrituras necesita sso-chain",
            )


if __name__ == "__main__":
    unittest.main()
