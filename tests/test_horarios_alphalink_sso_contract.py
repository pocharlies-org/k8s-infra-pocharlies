"""SC-2495 (16-10-2026): el planificador de AlphaLink en `horarios.alphalinkcrossfit.com`
solo se sirve detrás de su oauth2-proxy propio, y la exportación para el detector de
fichajes NO sale a internet.

Lo que fija este test es la cadena completa sobre los tres ficheros que la poseen,
porque cada uno se puede romper solo:

  - networking/traefik-edge/horarios-alphalink-public.yaml  (Certificate + IngressRoute)
  - platform/keycloak-sso/realms.yaml                       (realm, grupos y personas; SC-2822)
  - networking/cert-manager/cluster-issuers.yaml            (solver del dominio del cliente)

Si el middleware desaparece de la ruta del host, los horarios de unos empleados de un
cliente quedan públicos. Si los grupos de una persona no son los que admite el proxy,
Dom entra y recibe 403 en bucle.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTE = ROOT / "networking" / "traefik-edge" / "horarios-alphalink-public.yaml"
REALMS = ROOT / "platform" / "keycloak-sso" / "realms.yaml"
ISSUERS = ROOT / "networking" / "cert-manager" / "cluster-issuers.yaml"
KUSTOMIZATION = ROOT / "kustomization.yaml"

HOST = "horarios.alphalinkcrossfit.com"


def docs(path):
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def by_kind(path, kind, name=None):
    for d in docs(path):
        if d.get("kind") == kind and (name is None or d["metadata"]["name"] == name):
            yield d


class RouteContract(unittest.TestCase):
    def setUp(self):
        self.route = next(by_kind(ROUTE, "IngressRoute"))
        self.rules = {r["match"]: r for r in self.route["spec"]["routes"]}

    def test_la_ruta_del_host_va_por_la_cadena_propia(self):
        regla = self.rules[f"Host(`{HOST}`)"]
        self.assertIn(("sso-alphalink-chain", "keycloak"),
                      [(m["name"], m["namespace"]) for m in regla["middlewares"]])
        svc = regla["services"][0]
        # SC-2532: el backend es el ExternalName de traefik-edge hacia la app.
        self.assertEqual((svc["name"], svc.get("namespace"), svc["port"]),
                         ("edge-horarios-alphalink", None, 8080))

    def test_las_dos_rutas_vacian_las_cabeceras_de_identidad(self):
        # security: la app se fía de X-Auth-Request-Email; si llega de la calle,
        # es un forged. Se vacía SIEMPRE, y antes de la cadena (después borrase
        # lo que inyecta el proxy y no entra nadie).
        for match, cadena in ((f"Host(`{HOST}`)", True),
                             (f"Host(`{HOST}`) && PathPrefix(`/oauth2`)", False)):
            mw = [(m["name"], m["namespace"]) for m in self.rules[match]["middlewares"]]
            self.assertEqual(mw[0], ("alphalink-strip-identity-headers", "traefik-edge"), match)
            self.assertEqual(("sso-alphalink-chain", "keycloak") in mw, cadena, match)

    def test_el_callback_del_proxy_no_va_por_forward_auth(self):
        # forward-auth sobre /oauth2/callback = bucle de login (precedente skirmbooks).
        regla = self.rules[f"Host(`{HOST}`) && PathPrefix(`/oauth2`)"]
        self.assertEqual(regla["services"][0]["name"], "oauth2-proxy-alphalink")

    def test_la_exportacion_no_es_publica(self):
        # Devuelve nombres y horas de empleados: solo por DNS interno del clúster.
        matches = [r["match"] for r in self.route["spec"]["routes"]]
        self.assertTrue(all("exportacion" not in m for m in matches))

    def test_el_certificado_es_para_el_host_del_cliente(self):
        cert = next(by_kind(ROUTE, "Certificate"))
        self.assertEqual(cert["spec"]["dnsNames"], [HOST])
        self.assertEqual(cert["spec"]["issuerRef"]["name"], "letsencrypt-prod")
        self.assertEqual(self.route["spec"]["tls"]["secretName"], cert["spec"]["secretName"])

    def test_la_ruta_esta_declarada_en_el_kustomization(self):
        res = yaml.safe_load(KUSTOMIZATION.read_text(encoding="utf-8"))["resources"]
        self.assertIn("networking/traefik-edge/horarios-alphalink-public.yaml", res)


class RealmContract(unittest.TestCase):
    """SC-2822: el planificador tiene su realm `alphalink` (platform/keycloak-sso).
    Lo genérico (cookie pegada al host, issuer del realm, solo 401) lo fija
    test_keycloak_realm_per_web_contract; aquí, lo de este cliente."""

    def setUp(self):
        self.realm = next(r for r in yaml.safe_load(REALMS.read_text(encoding="utf-8"))["realms"]
                          if r["name"] == "alphalink")

    def test_solo_el_host_del_cliente(self):
        self.assertEqual(self.realm["hosts"], [HOST])

    def test_grupos_y_personas(self):
        # Si los grupos de allowedGroups no son los que tienen los usuarios, Dom
        # entra y recibe 403 en bucle.
        self.assertEqual(self.realm["allowedGroups"],
                         ["alphalink-horarios-users", "alphalink-horarios-admins"])
        personas = {u["email"]: u["groups"] for u in self.realm["users"]}
        self.assertEqual(personas, {
            "daniel.ibanez@alphalinkcrossfit.com": ["alphalink-horarios-users", "alphalink-horarios-admins"],
            "dom.greco@alphalinkcrossfit.com": ["alphalink-horarios-users"],
        })

    def test_entra_con_google_del_dominio_del_cliente(self):
        self.assertTrue(self.realm["google"])
        self.assertEqual(self.realm["googleHostedDomain"], "alphalinkcrossfit.com")


class IssuerContract(unittest.TestCase):
    def test_ambos_issuers_tienen_solver_para_el_dominio_del_cliente(self):
        for issuer in by_kind(ISSUERS, "ClusterIssuer"):
            zones = [z for s in issuer["spec"]["acme"]["solvers"] for z in s["selector"]["dnsZones"]]
            self.assertIn("alphalinkcrossfit.com", zones,
                          f"{issuer['metadata']['name']} no puede emitir para el host del cliente")


class DatabaseContract(unittest.TestCase):
    def test_la_base_y_el_rol_estan_declarados(self):
        databases = list(by_kind(ROOT / "databases/postgres-shared/app-databases.yaml", "Database"))
        ours = next(d for d in databases if d["metadata"]["name"] == "horarios")
        self.assertEqual((ours["spec"]["name"], ours["spec"]["owner"]), ("horarios", "horarios"))
        cluster = yaml.safe_load((ROOT / "databases/postgres-shared/cluster.yaml").read_text())
        roles = {r["name"]: r for r in cluster["spec"]["managed"]["roles"]}
        self.assertEqual(roles["horarios"]["passwordSecret"]["name"], "horarios-db-credentials")
        self.assertEqual(roles["horarios"]["connectionLimit"], 5)
        secrets = list(by_kind(ROOT / "databases/postgres-shared/app-credentials.yaml",
                               "ExternalSecret"))
        ours_secret = next(s for s in secrets if s["metadata"]["name"] == "horarios-db-credentials")
        self.assertEqual([d["secretKey"] for d in ours_secret["spec"]["data"]],
                         ["username", "password"])


if __name__ == "__main__":
    unittest.main()
