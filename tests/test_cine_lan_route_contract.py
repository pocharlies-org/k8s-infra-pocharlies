"""DGX-1675 (épica DGX-1674, Dani 17-11 «Backlot original solo en casa»): la puerta del tablero Backlot.

Lo que la hace segura, y lo que este test fija:

  - un solo host, `cine.lan.e-dani.com`, y solo desde las redes de confianza de la casa (LAN, tailnet,
    pods y servicios del clúster); desde cualquier otra la regla no casa;
  - ninguna ruta pública: ni un host `cine` en traefik-edge, ni clase de ingreso que el borde procese, ni
    el ns `paseo` en el allowlist del borde;
  - el único middleware es el que reescribe el Host a `localhost` (el TrustedHostMiddleware upstream de
    Backlot no admite otro) y quita Cookie y Authorization (la cookie SSO no va a un tablero sin login, security
    DGX-1677 §9.3). Ninguna escritura llega aquí: Backlot es de solo lectura y las acciones van
    por el dashboard tras sso-chain.
"""
import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUTA = "networking/traefik-lan/cine-lan.yaml"
HOST = "cine.lan.e-dani.com"
TRUSTED = ("192.168.50.0/24", "100.64.0.0/10", "10.42.0.0/16", "10.43.0.0/16")


def _docs(ruta):
    return [d for d in yaml.safe_load_all(ruta.read_text(encoding="utf-8")) if d]


class CineLanRouteContract(unittest.TestCase):
    def setUp(self):
        docs = {d["kind"]: d for d in _docs(ROOT / RUTA)}
        self.mw, self.route = docs["Middleware"], docs["IngressRoute"]
        (self.regla,) = self.route["spec"]["routes"]

    def test_una_ingressroute_de_traefik_lan_que_el_borde_no_procesa(self):
        self.assertEqual(self.route["metadata"]["namespace"], "traefik-lan")
        self.assertEqual(self.route["spec"]["entryPoints"], ["websecure"])
        self.assertNotIn("ingressClassName", self.route["spec"])
        self.assertNotIn("kubernetes.io/ingress.class", self.route["metadata"].get("annotations") or {})

    def test_un_solo_host_y_solo_desde_las_redes_de_confianza(self):
        desde = " || ".join(f"ClientIP(`{cidr}`)" for cidr in TRUSTED)
        self.assertEqual(self.regla["match"], f"Host(`{HOST}`) && ({desde})")

    def test_el_unico_middleware_reescribe_el_host_y_quita_la_cookie_sso(self):
        self.assertEqual(self.mw["metadata"]["namespace"], "traefik-lan")
        self.assertEqual(self.mw["spec"], {"headers": {"customRequestHeaders": {"Host": "localhost", "Cookie": "", "Authorization": ""}}})
        self.assertEqual(self.regla["middlewares"], [{"name": self.mw["metadata"]["name"], "namespace": "traefik-lan"}])

    def test_al_service_backlot_del_ns_paseo(self):
        self.assertEqual(self.regla["services"], [{"name": "backlot", "namespace": "paseo", "port": 19913}])

    def test_certificado_de_la_casa(self):
        self.assertEqual(self.route["spec"]["tls"], {"store": {"name": "default", "namespace": "traefik-lan"}})

    def test_el_fichero_entra_por_el_kustomization(self):
        resources = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))["resources"]
        self.assertIn(RUTA, resources)


class CineNoSePublicaFueraDeLaLan(unittest.TestCase):
    def test_traefik_edge_no_sirve_el_tablero(self):
        vistos = 0
        for ruta in sorted((ROOT / "networking" / "traefik-edge").glob("*.yaml")):
            for doc in _docs(ruta):
                vistos += 1
                texto = json.dumps(doc)
                self.assertNotIn(HOST, texto, ruta)
                self.assertIsNone(re.search(r'"name": "backlot"', texto), ruta)
        self.assertGreater(vistos, 0, "el barrido no encontró nada: el glob se rompió")

    def test_el_allowlist_del_borde_no_incluye_el_ns_paseo(self):
        values = yaml.safe_load((ROOT / "networking/traefik-edge/values.yaml").read_text(encoding="utf-8"))
        for proveedor in ("kubernetesCRD", "kubernetesIngress"):
            allowlist = values["providers"][proveedor]["namespaces"]
            self.assertTrue(allowlist, proveedor)
            self.assertNotIn("paseo", allowlist, proveedor)


if __name__ == "__main__":
    unittest.main()
