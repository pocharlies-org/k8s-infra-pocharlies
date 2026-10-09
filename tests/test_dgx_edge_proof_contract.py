"""DGX-729 (security, 09-10-2026): prueba de borde X-Edge-Proof en TODO lo que sirve el
dashboard.

El backend solo se fía de `x-auth-request-email` (es_dani / alarma / pantallas seguras) si la
petición trae `X-Edge-Proof` (services/dashboard/edge_proof.py en dgx-infra). El secreto NO
vive en el YAML (hallazgo del juez de PR): cada instancia Traefik tiene un servicio mínimo
(python:3.12-alpine, gema edge/lan, patrón firecrawl-edge-auth) que responde 200 con la
cabecera y Traefik la copia vía forwardAuth.authResponseHeaders; el valor llega al pod por
env desde un ExternalSecret Connect a la SecureNote dgx-edge-proof (campo proof) del vault
k8s-pocharlies — el MISMO valor que lee el backend (dgx-dashboard-edge-proof, repo dgx-infra).

Este test fija:
  * el middleware forwardAuth existe UNA VEZ por instancia y apunta al servicio de su ns, con
    authResponseHeaders [X-Edge-Proof];
  * el secreto no aparece en claro en ningún YAML del repo;
  * el servicio gemelo: Deployment + Service + ExternalSecret Connect (key=dgx-edge-proof,
    property=proof) por ns, env desde secretKeyRef dgx-edge-proof/proof;
  * que toda ruta que reenvía a `dgx-dashboard-ui` lleva el middleware (exención única: las
    de redirectRegex, que no llegan al backend);
  * que el servicio solo es alcanzable desde su propio namespace (si no, cualquier pod leería
    el proof en la respuesta y volvería a poder forjarlo) y que el strip no toca X-Edge-Proof
    ni pierde ninguna de las 7 cabeceras de identidad.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
TWINS = {
    "traefik-edge": ROOT / "networking" / "traefik-edge" / "dgx-edge-proof.yaml",
    "traefik-lan": ROOT / "networking" / "traefik-lan" / "dgx-edge-proof.yaml",
}
STRIP_TWINS = {
    "traefik-edge": ROOT / "networking" / "traefik-edge" / "dgx-dashboard-public.yaml",
    "traefik-lan": ROOT / "networking" / "traefik-lan" / "dgx-public-host-lan.yaml",
}
IDENTIDAD = ["X-Auth-Request-User", "X-Auth-Request-Email", "X-Auth-Request-Groups",
             "X-Auth-Request-Preferred-Username", "X-Forwarded-User", "X-Forwarded-Email",
             "X-Forwarded-Groups"]


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _by_kind(docs, kind, name=None):
    return [d for d in docs if d.get("kind") == kind
            and (name is None or d["metadata"]["name"] == name)]


class DgxEdgeProofContract(unittest.TestCase):
    def test_middleware_forwardauth_uno_por_instancia(self):
        for ns, path in TWINS.items():
            mws = _by_kind(_docs(path), "Middleware", "dgx-edge-proof")
            self.assertEqual(len(mws), 1, f"{ns}: dgx-edge-proof definido una sola vez")
            self.assertEqual(mws[0]["metadata"]["namespace"], ns)
            fa = mws[0]["spec"]["forwardAuth"]
            self.assertEqual(fa["address"], f"http://dgx-edge-proof.{ns}.svc.cluster.local:8080/")
            self.assertEqual(fa["authResponseHeaders"], ["X-Edge-Proof"])

    def test_el_secreto_no_aparece_en_el_repo(self):
        """Nada de hex de 32 bytes ni cabeceras X-Edge-Proof con valor en los manifiestos:
        el valor solo vive en 1Password y en el Secret del clúster."""
        import re
        for path in (ROOT / "networking").rglob("*.yaml"):
            text = path.read_text()
            self.assertNotIn("X-Edge-Proof: ", text,
                             f"{path.name}: X-Edge-Proof con valor hardcodeado")
            self.assertIsNone(re.search(r"[0-9a-f]{64}", text),
                              f"{path.name}: parece un secreto de 32 bytes en claro")

    def test_servicio_gemelo_con_secret_desde_1password(self):
        for ns, path in TWINS.items():
            docs = _docs(path)
            dep = _by_kind(docs, "Deployment", "dgx-edge-proof")
            self.assertEqual(len(dep), 1, f"{ns}: Deployment dgx-edge-proof")
            env = {e["name"]: e for e in dep[0]["spec"]["template"]["spec"]["containers"][0]["env"]}
            ref = env["EDGE_PROOF"]["valueFrom"]["secretKeyRef"]
            self.assertEqual((ref["name"], ref["key"]), ("dgx-edge-proof", "proof"))
            self.assertEqual(len(_by_kind(docs, "Service", "dgx-edge-proof")), 1, f"{ns}: Service")
            es = _by_kind(docs, "ExternalSecret", "dgx-edge-proof")
            self.assertEqual(len(es), 1, f"{ns}: ExternalSecret")
            spec = es[0]["spec"]
            self.assertEqual(spec["secretStoreRef"],
                             {"kind": "ClusterSecretStore", "name": "onepassword-connect"})
            self.assertEqual(spec["refreshPolicy"], "OnChange")
            self.assertEqual(spec["data"][0]["secretKey"], "proof")
            remote = spec["data"][0]["remoteRef"]
            self.assertEqual(remote["key"], "dgx-edge-proof")   # forma Connect: key=item
            self.assertEqual(remote["property"], "proof")       # property=campo, nunca item/field
            self.assertEqual(es[0]["metadata"]["namespace"], ns)

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

    def test_la_prueba_solo_la_pide_traefik(self):
        """El servicio que publica el proof no puede ser alcanzable desde cualquier pod (leerlo
        por la respuesta equivale a forjarlo). En traefik-edge lo cubre default-deny +
        allow-same-namespace; en traefik-lan (sin default-deny) hace falta una policy propia."""
        edge = _docs(TWINS["traefik-edge"])
        self.assertTrue(any(d.get("kind") == "NetworkPolicy" and
                            d["metadata"]["name"] == "traefik-edge-allow-same-namespace"
                            for d in _docs(ROOT / "networking" / "traefik-edge" / "networkpolicy.yaml")))
        lan_pols = [d for d in _docs(TWINS["traefik-lan"]) if d.get("kind") == "NetworkPolicy"]
        self.assertEqual([d["metadata"]["name"] for d in lan_pols], ["dgx-edge-proof-allow-traefik-only"])
        pol = lan_pols[0]["spec"]
        self.assertEqual(pol["podSelector"], {"matchLabels": {"app.kubernetes.io/name": "dgx-edge-proof"}})
        self.assertEqual(pol["ingress"], [{"from": [{"podSelector": {}}]}])

    def test_strip_intacto_y_sin_la_prueba(self):
        """dgx-strip-identity-headers vacía las 7 de identidad y SOLO esas: ni X-Edge-Proof
        (la prueba debe sobrevivir al strip) ni ninguna de las 7 borrada (rework DGX-729: la
        gemela LAN perdió X-Forwarded-Groups con el cambio de la prueba)."""
        for ns, path in STRIP_TWINS.items():
            strip = next(d for d in _docs(path) if d.get("kind") == "Middleware"
                         and d["metadata"]["name"] == "dgx-strip-identity-headers")
            hdrs = strip["spec"]["headers"]["customRequestHeaders"]
            self.assertEqual(sorted(hdrs), sorted(IDENTIDAD), f"{ns}: strip debe vaciar las 7 y nada más")


if __name__ == "__main__":
    unittest.main()
