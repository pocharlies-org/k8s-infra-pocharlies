"""dgx.nova.panel.v1 (INFRA-1247): /api/nova entra en el control set (prioridad 400, tras sso-chain) de las dos
IngressRoute de traefik-edge que sirven el dashboard. Todos los métodos, no solo POST: el backend pone
ESCRITURA_CLUSTER también en el GET (la transcripción de la reunión) y en el DELETE (sacar a Nova), y sin sso-chain
el JWT no llega y hasta un admin recibe 403 (security, INFRA-1247)."""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUTAS = [(ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml", "edge-dgx-dashboard-public"),
         (ROOT / "networking" / "traefik-edge" / "s3-media-public.yaml", None)]


def _ruta_400(path, name):
    for doc in yaml.safe_load_all(path.read_text()):
        if doc and doc.get("kind") == "IngressRoute" and (name is None or doc["metadata"]["name"] == name):
            for route in doc["spec"]["routes"]:
                if route.get("priority") == 400:
                    return route
    raise AssertionError(f"{path.name}: sin ruta de prioridad 400")


class NovaPanelSSOContract(unittest.TestCase):
    def test_api_nova_va_entera_tras_sso_chain(self):
        for path, name in RUTAS:
            route = _ruta_400(path, name)
            self.assertIn("PathPrefix(`/api/nova`)", route["match"], path.name)
            self.assertNotIn("Method(", route["match"], f"{path.name}: el control set no filtra por método")
            chain = [m["name"] for m in route["middlewares"]]
            self.assertLess(chain.index("dgx-strip-identity-headers"), chain.index("sso-chain"), path.name)


if __name__ == "__main__":
    unittest.main()
