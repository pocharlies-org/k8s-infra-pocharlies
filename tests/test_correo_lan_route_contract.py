"""DGX-880 (P10 de la épica DGX-870, security S20): la puerta LAN/tailnet del núcleo de correo (`correo-core`).

El núcleo valida el JWT él mismo y no lee ningún dato de identidad de una cabecera, así que la ruta no lleva
`sso-chain` ni la prueba de borde (`dgx-edge-proof`) ni el borrado de cabeceras de identidad. Lo que sí fija este
test es lo que la hace segura:

  - un solo host, `correo.lan.e-dani.com` (Cloudflare resuelve `*.lan.e-dani.com` al VIP de traefik-lan y el
    certificado por defecto de ese store es `*.lan.e-dani.com`), y solo desde las redes de confianza de la casa;
  - dos destinos (DGX-882 P4): `/v1`, `/v2/casos`, `/v2/clientes` (DGX-1213) y `/healthz` van al Service HUMANO `correo:80` del núcleo, con prioridad
    explícita, y el resto del host a la web `correo-web:80`, sin access log porque la vuelta del login
    (`/auth/callback?code=…`) lleva el `code` en la query; el de máquina (`correo-machine`, el de
    `correo.ingest.v1`, solo interno) no se publica en ninguna ruta;
  - ninguna ruta pública por sauvage: ni un host de correo en traefik-edge ni el ns `correo` en el allowlist del
    borde, y la ruta de LAN no lleva clase de ingreso que el borde procese.
"""
import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUTA = "networking/traefik-lan/correo-lan.yaml"
HOST = "correo.lan.e-dani.com"
TRUSTED = ("192.168.50.0/24", "100.64.0.0/10", "10.42.0.0/16", "10.43.0.0/16")   # LAN, tailnet, pods y servicios


def _docs(ruta):
    return [d for d in yaml.safe_load_all(ruta.read_text(encoding="utf-8")) if d]


class CorreoLanRouteContract(unittest.TestCase):
    def setUp(self):
        (self.route,) = _docs(ROOT / RUTA)
        self.api, self.web = self.route["spec"]["routes"]

    def test_una_ingressroute_de_traefik_lan_que_el_borde_no_procesa(self):
        self.assertEqual((self.route["kind"], self.route["metadata"]["namespace"]), ("IngressRoute", "traefik-lan"))
        self.assertEqual(self.route["spec"]["entryPoints"], ["websecure"])
        # el edge observa traefik-lan pero solo procesa las rutas con su clase: esta no la lleva
        self.assertNotIn("ingressClassName", self.route["spec"])
        self.assertNotIn("kubernetes.io/ingress.class", self.route["metadata"].get("annotations") or {})

    def test_un_solo_host_y_solo_desde_las_redes_de_confianza(self):
        desde = " || ".join(f"ClientIP(`{cidr}`)" for cidr in TRUSTED)
        self.assertEqual(self.api["match"], f"Host(`{HOST}`) && (PathPrefix(`/v1`) || PathPrefix(`/v2/casos`) || PathPrefix(`/v2/clientes`) || Path(`/healthz`)) && ({desde})")
        self.assertEqual(self.web["match"], f"Host(`{HOST}`) && ({desde})")

    def test_de_v2_solo_salen_casos_y_clientes(self):
        """DGX-1213: `/v2` entero no se publica; `/v2/inbound` y `/v2/buzones` son de máquina."""
        reglas = " ".join(r["match"] for r in self.route["spec"]["routes"])
        self.assertNotIn("PathPrefix(`/v2`)", reglas)
        self.assertNotIn("/v2/inbound", reglas)
        self.assertNotIn("/v2/buzones", reglas)
        self.assertNotIn("/v2", self.web["match"])

    def test_sin_sso_chain_ni_prueba_de_borde_ni_ningun_middleware(self):
        for regla in (self.api, self.web):
            self.assertEqual(regla["kind"], "Rule")
            self.assertNotIn("middlewares", regla)

    def test_la_api_al_service_humano_y_el_resto_a_la_web(self):
        self.assertEqual(self.api["services"], [{"name": "correo", "namespace": "correo", "port": 80}])
        self.assertEqual(self.web["services"], [{"name": "correo-web", "namespace": "correo", "port": 80}])

    def test_la_api_gana_a_la_web_aunque_cambie_la_longitud_de_las_reglas(self):
        # sin `priority`, Traefik usa la longitud de la regla: una red de confianza más en la de la web le daría `/v1`
        self.assertGreater(self.api["priority"], len(self.web["match"]) + 100)
        self.assertNotIn("priority", self.web)

    def test_la_web_no_deja_el_code_del_login_en_el_access_log(self):
        # security (DGX-882, 33631): `/auth/callback?code=…` es de la web, y traefik-lan guarda la query en `RequestPath`
        self.assertEqual(self.web["observability"], {"accessLogs": False})
        self.assertNotIn("observability", self.api)

    def test_certificado_de_la_casa(self):
        self.assertEqual(self.route["spec"]["tls"], {"store": {"name": "default", "namespace": "traefik-lan"}})

    def test_el_fichero_entra_por_el_kustomization(self):
        resources = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))["resources"]
        self.assertIn(RUTA, resources)


class CorreoNoSePublicaFueraDeLaLan(unittest.TestCase):
    def test_ninguna_ruta_ni_servicio_de_networking_nombra_el_service_de_maquina(self):
        vistos = 0
        for ruta in sorted((ROOT / "networking").rglob("*.yaml")):
            for doc in _docs(ruta):
                vistos += 1
                self.assertNotIn("correo-machine", json.dumps(doc), ruta)
        self.assertGreater(vistos, 0, "el barrido no encontró nada: el glob se rompió")

    def test_traefik_edge_no_sirve_nada_de_correo(self):
        vistos = 0
        for ruta in sorted((ROOT / "networking" / "traefik-edge").glob("*.yaml")):
            for doc in _docs(ruta):
                vistos += 1
                # `\bcorreo\b` no casa con `correos-express`, el transportista
                self.assertIsNone(re.search(r"\bcorreo\b", json.dumps(doc)), ruta)
        self.assertGreater(vistos, 0, "el barrido no encontró nada: el glob se rompió")

    def test_el_allowlist_del_borde_no_incluye_el_ns_correo(self):
        values = yaml.safe_load((ROOT / "networking/traefik-edge/values.yaml").read_text(encoding="utf-8"))
        for proveedor in ("kubernetesCRD", "kubernetesIngress"):
            allowlist = values["providers"][proveedor]["namespaces"]
            self.assertTrue(allowlist, proveedor)
            self.assertNotIn("correo", allowlist, proveedor)


if __name__ == "__main__":
    unittest.main()
