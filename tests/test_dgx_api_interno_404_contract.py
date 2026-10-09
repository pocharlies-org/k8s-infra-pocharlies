"""INFRA-732 (P6a-2): /api/interno/* es una ruta interna del dashboard que solo debe
alcanzar el forwardAuth interno de Traefik, por el Service del clúster
(control-nexus/dgx-dashboard-ui), nunca por una IngressRoute. Sin una regla propia,
/api/interno caía en el bypass (edge 200 / lan 300) o en la pública (100) y llegaba al
backend. Este test fija la regla 404 en las DOS rutas del dashboard:

  - networking/traefik-edge/dgx-dashboard-public.yaml  (IngressRoute edge-dgx-dashboard-public)
  - networking/traefik-lan/dgx-public-host-lan.yaml     (IngressRoute lan-dgx-dashboard-public-host)

C1: la regla existe en las DOS rutas, su prioridad es mayor que 450 (precede a las de
200/400/450) y NO reenvía al backend. Un solo prefijo cubre las rutas internas futuras.
La regla de /api/app/alarma (DGX-695) no se toca: se comprueba que sigue en el control
set (400) de ambos ficheros.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAN = ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml"
EDGE = ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml"

LAN_IR = "lan-dgx-dashboard-public-host"
EDGE_IR = "edge-dgx-dashboard-public"

INTERNO = "PathPrefix(`/api/interno`)"
BACKEND = "dgx-dashboard-ui"


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _ingressroute(docs, name):
    for doc in docs:
        if doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == name:
            return doc
    raise AssertionError(f"IngressRoute {name} not found")


def _interno_routes(ir):
    return [r for r in ir["spec"]["routes"] if INTERNO in r["match"]]


class ApiInterno404Contract(unittest.TestCase):
    def _assert_rule(self, docs, name):
        ir = _ingressroute(docs, name)
        routes = ir["spec"]["routes"]
        cands = _interno_routes(ir)
        self.assertEqual(len(cands), 1,
                         f"{name}: exactly one /api/interno rule expected, got {len(cands)}")
        rule = cands[0]

        # C1a: prioridad mayor que 450 (por encima de /messages y del control set).
        prio = rule.get("priority", 0)
        self.assertGreater(prio, 450, f"{name}: /api/interno priority must be > 450, got {prio}")

        # C1b: precede a TODAS las demás rutas de la IngressRoute (es la de mayor prioridad).
        others = [r.get("priority", 0) for r in routes if r is not rule]
        self.assertGreater(prio, max(others),
                           f"{name}: /api/interno must be the highest-priority rule "
                           f"(precede 200/400/450); others={sorted(others)}")

        # C1c: no reenvía al backend del dashboard.
        svc_names = [s.get("name") for s in rule.get("services", [])]
        self.assertNotIn(BACKEND, svc_names,
                         f"{name}: /api/interno must NOT forward to the dashboard backend")
        self.assertTrue(svc_names, f"{name}: /api/interno rule needs a service to answer 404")

        # no pasa por sso-chain (no se autentica contra el backend: se corta en el borde).
        mw_names = [m.get("name") for m in rule.get("middlewares", [])]
        self.assertNotIn("sso-chain", mw_names,
                         f"{name}: /api/interno 404 must be served at the edge, not behind sso-chain")

    def test_edge_404_rule(self):
        self._assert_rule(_docs(EDGE), EDGE_IR)

    def test_lan_404_rule(self):
        self._assert_rule(_docs(LAN), LAN_IR)

    def test_alarma_de_dgx695_sigue_en_el_control_set(self):
        """La regla /api/app/alarma (DGX-695) no se toca: sigue en la 400 de ambos ficheros."""
        for docs, name in ((_docs(EDGE), EDGE_IR), (_docs(LAN), LAN_IR)):
            ir = _ingressroute(docs, name)
            r400 = next(r for r in ir["spec"]["routes"] if r.get("priority") == 400)
            self.assertIn("PathPrefix(`/api/app/alarma`)", r400["match"],
                          f"{name}: DGX-695 /api/app/alarma must remain in the 400 control set")


if __name__ == "__main__":
    unittest.main()
