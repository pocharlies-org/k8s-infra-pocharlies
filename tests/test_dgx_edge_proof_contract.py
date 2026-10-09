"""DGX-729 (security, 09-10-2026): prueba de borde X-Edge-Proof en TODO lo que sirve el
dashboard.

El backend solo se fía de `x-auth-request-email` (es_dani / alarma / pantallas seguras) si la
petición trae `X-Edge-Proof` (services/dashboard/edge_proof.py en dgx-infra). Este test fija:

  * que el middleware `dgx-edge-proof` existe UNA VEZ por instancia Traefik (traefik-edge y
    traefik-lan, como dgx-strip-identity-headers) y que el valor estático de las dos gemelas
    es EXACTAMENTE el mismo (una rotación a medias es un 403 silencioso por la otra);
  * que toda ruta que reenvía a `dgx-dashboard-ui` (la UI hace de host del backend) lleva el
    middleware en la cadena — la única excepción es la de redirect (no llega al backend);
  * que el valor es un hex de 32 bytes (el mismo que dgx-infra monta vía ExternalSecret
    dgx-dashboard-edge-proof desde la SecureNote dgx-edge-proof de 1Password).
"""
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
TWINS = {
    "traefik-edge": ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml",
    "traefik-lan": ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml",
}


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _proof_middleware(path):
    return [d for d in _docs(path)
            if d.get("kind") == "Middleware" and d["metadata"]["name"] == "dgx-edge-proof"]


class DgxEdgeProofContract(unittest.TestCase):
    def test_un_middleware_por_instancia_y_mismo_valor(self):
        valores = {}
        for ns, path in TWINS.items():
            mws = _proof_middleware(path)
            self.assertEqual(len(mws), 1, f"{ns}: dgx-edge-proof definido una sola vez")
            self.assertEqual(mws[0]["metadata"]["namespace"], ns)
            valores[ns] = mws[0]["spec"]["headers"]["customRequestHeaders"]["X-Edge-Proof"]
        self.assertEqual(len(set(valores.values())), 1, "las gemelas edge/lan deben coincidir")
        valor = valores["traefik-edge"]
        self.assertRegex(valor, r"^[0-9a-f]{64}$", "32 bytes en hex, como el EDGE_PROOF_SECRET del backend")

    def test_toda_ruta_que_sirve_el_dashboard_lleva_la_prueba(self):
        """Cualquier IngressRoute que reenvíe a dgx-dashboard-ui (UI = host del backend) añade
        la prueba. Exención única: las de redirectRegex (no llegan al backend)."""
        vistas = 0
        for path in sorted((ROOT / "networking").rglob("*.yaml")):
            for doc in _docs(path):
                if doc.get("kind") != "IngressRoute":
                    continue
                for route in doc.get("spec", {}).get("routes", []):
                    svcs = [s.get("name") for s in route.get("services", []) or []]
                    if "dgx-dashboard-ui" not in svcs:
                        continue
                    nombres = [m["name"] for m in route.get("middlewares", [])]
                    if any("redirect" in n for n in nombres):
                        continue
                    vistas += 1
                    self.assertIn("dgx-edge-proof", nombres,
                                  f"{path.name}@{doc['metadata']['name']} prio {route.get('priority')}: "
                                  "ruta al dashboard sin prueba de borde (DGX-729)")
        self.assertGreaterEqual(vistas, 19, "se esperaban al menos las 19 rutas medidas del dashboard")

    def test_strip_no_toca_la_prueba(self):
        """dgx-strip-identity-headers vacía SOLO las 7 de identidad: X-Edge-Proof no puede
        aparecer en su lista (si algún día se añade, la prueba moriría en las rutas 200/300)."""
        for ns, path in TWINS.items():
            strip = next(d for d in _docs(path) if d.get("kind") == "Middleware"
                         and d["metadata"]["name"] == "dgx-strip-identity-headers")
            self.assertNotIn("X-Edge-Proof", strip["spec"]["headers"]["customRequestHeaders"])


if __name__ == "__main__":
    unittest.main()
