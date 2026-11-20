"""DGX-1742 (security S-3, nota-security-cine-panel.md §15.8 en dgx-infra): el preflight CORS de Backlot.

Backlot (https://cine.lan.e-dani.com) escribe en https://dgx.e-dani.com/api/cine/* con fetch(credentials: 'include').
El navegador manda antes un OPTIONS sin cookie; tras sso-chain recibía un 302 a Keycloak y el POST no salía. La regla
`Host(dgx.e-dani.com) && Method(OPTIONS) && PathPrefix(/api/cine)` entra a 450 SIN sso-chain en las dos IngressRoute del
host (edge y su gemela LAN, que es donde cae el navegador de casa por el rewrite de AdGuard). Este test fija:

  * existe una sola, en las dos, con ese match exacto (solo OPTIONS, solo /api/cine, solo el host del panel);
  * prioridad 450, por encima de la regla con sso-chain que lleva /api/cine (400 en el edge, 420 en LAN), y por debajo de
    /api/interno (500) y /oauth2 (600);
  * sin sso-chain, con strip de identidad antes y prueba de borde (DGX-729), y al dashboard;
  * la regla con sso-chain de /api/cine sigue sin filtrar por método: el GET/POST de detrás pasa por sso-chain;
  * ninguna otra regla sin sso-chain del host deja pasar /api/cine.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
EDGE = (ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml", "edge-dgx-dashboard-public", "traefik-edge", 400)
LAN = (ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml", "lan-dgx-dashboard-public-host", "traefik-lan", 420)
MATCH = "Host(`dgx.e-dani.com`) && Method(`OPTIONS`) && PathPrefix(`/api/cine`)"


def _rutas(path, name):
    for doc in yaml.safe_load_all(path.read_text()):
        if doc and doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == name:
            return doc["spec"]["routes"]
    raise AssertionError(f"{path.name}: sin IngressRoute {name}")


def _mws(ruta):
    return [(m["name"], m.get("namespace", "")) for m in ruta.get("middlewares", [])]


class CinePreflightContract(unittest.TestCase):
    def test_regla_options_450_sin_sso_en_edge_y_lan(self):
        for path, name, ns, _ in (EDGE, LAN):
            rutas = _rutas(path, name)
            preflight = [r for r in rutas if "Method(`OPTIONS`)" in r["match"]]
            self.assertEqual(len(preflight), 1, f"{path.name}: una sola regla de preflight")
            r = preflight[0]
            self.assertEqual(r["match"], MATCH, path.name)
            self.assertEqual(r["priority"], 450, path.name)
            self.assertEqual(_mws(r), [("dgx-strip-identity-headers", ns), ("dgx-edge-proof", ns)], path.name)
            self.assertEqual([s["name"] for s in r["services"]], ["dgx-dashboard-ui"], path.name)

    def test_por_encima_de_la_regla_sso_de_cine_y_por_debajo_de_interno_y_oauth2(self):
        for path, name, _, prio_sso in (EDGE, LAN):
            rutas = _rutas(path, name)
            cine_sso = [r for r in rutas if "PathPrefix(`/api/cine`)" in r["match"]
                        and "sso-chain" in [m for m, _ in _mws(r)]]
            self.assertEqual([r["priority"] for r in cine_sso], [prio_sso], path.name)
            self.assertNotIn("Method(", cine_sso[0]["match"], f"{path.name}: el GET/POST de /api/cine sigue tras sso-chain")
            por_prio = {r["priority"]: r["match"] for r in rutas}
            self.assertIn("/api/interno", por_prio[500], path.name)
            self.assertIn("/oauth2", por_prio[600], path.name)
            self.assertGreater(450, prio_sso)

    def test_ninguna_otra_regla_sin_sso_abre_api_cine(self):
        for path, name, _, _ in (EDGE, LAN):
            for r in _rutas(path, name):
                if "sso-chain" in [m for m, _ in _mws(r)] or r["match"] == MATCH:
                    continue
                self.assertNotIn("/api/cine", r["match"], f"{path.name}: /api/cine sin sso-chain fuera del preflight")


if __name__ == "__main__":
    unittest.main()
