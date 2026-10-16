"""SC-2495 (16-10-2026): el planificador de AlphaLink en `horarios.alphalinkcrossfit.com`
solo se sirve detrás de su oauth2-proxy propio, y la exportación para el detector de
fichajes NO sale a internet.

Lo que fija este test es la cadena completa sobre los cuatro ficheros que la poseen,
porque cada uno se puede romper solo:

  - networking/traefik-edge/horarios-alphalink-public.yaml  (Certificate + IngressRoute)
  - platform/keycloak-next/oauth2-proxy-alphalink.yaml      (cookie, grupos, whitelist)
  - platform/keycloak-next/alphalink-sso.yaml               (Job que reconcilia grupos)
  - networking/cert-manager/cluster-issuers.yaml            (solver del dominio del cliente)

Si el middleware desaparece de la ruta del host, los horarios de unos empleados de un
cliente quedan públicos. Si el Job reconcilia un grupo distinto del que declara el
proxy, Dom entra y recibe 403 en bucle.
"""
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTE = ROOT / "networking" / "traefik-edge" / "horarios-alphalink-public.yaml"
PROXY = ROOT / "platform" / "keycloak-next" / "oauth2-proxy-alphalink.yaml"
JOB = ROOT / "platform" / "keycloak-next" / "alphalink-sso.yaml"
ISSUERS = ROOT / "networking" / "cert-manager" / "cluster-issuers.yaml"
KUSTOMIZATION = ROOT / "kustomization.yaml"
PLATFORM_KUSTOMIZATION = ROOT / "platform" / "keycloak-next" / "kustomization.yaml"

HOST = "horarios.alphalinkcrossfit.com"
GRUPO = "/alphalink-horarios-users"
REDIRECT = f"https://{HOST}/oauth2/callback"


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
        self.assertEqual((svc["name"], svc["namespace"], svc["port"]),
                         ("horarios-alphalink", "alphalink", 8080))

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


class ProxyContract(unittest.TestCase):
    def setUp(self):
        cm = next(by_kind(PROXY, "ConfigMap"))
        self.cfg = cm["data"]["oauth2_proxy.cfg"]

    def test_cookie_y_grupos_propios(self):
        # Sin cookie_domains: la sesión de Dom no se mezcla con `_edani_sso`.
        self.assertIn('cookie_name = "_alphalink_horarios_sso"', self.cfg)
        lineas = [l.strip() for l in self.cfg.splitlines() if not l.strip().startswith("#")]
        self.assertFalse([l for l in lineas if l.startswith("cookie_domains")])
        grupos = re.search(r"allowed_groups\s*=\s*\[(.*?)\]", self.cfg).group(1)
        self.assertEqual([g.strip().strip('"') for g in grupos.split(",")],
                         ["/alphalink-horarios-users", "/alphalink-horarios-admins"])

    def test_solo_entran_cuentas_del_cliente(self):
        self.assertIn('whitelist_domains = [ ".alphalinkcrossfit.com" ]', self.cfg)
        self.assertIn(f'redirect_url = "{REDIRECT}"', self.cfg)

    def test_forward_auth_apunta_al_proxy_propio(self):
        mw = next(by_kind(PROXY, "Middleware", "sso-alphalink-forward-auth"))
        self.assertEqual(
            mw["spec"]["forwardAuth"]["address"],
            f"http://oauth2-proxy-alphalink.keycloak.svc.cluster.local:4180/oauth2/auth")
        self.assertIn("X-Auth-Request-Email", mw["spec"]["forwardAuth"]["authResponseHeaders"])
        # Solo 401: reescribir el 403 mete en bucle a quien entre sin grupo.
        err = next(by_kind(PROXY, "Middleware", "sso-alphalink-errors"))
        self.assertEqual(err["spec"]["errors"]["status"], ["401"])

    def test_el_proxy_esta_declarado_en_la_cadena_de_keycloak(self):
        res = yaml.safe_load(PLATFORM_KUSTOMIZATION.read_text(encoding="utf-8"))["resources"]
        self.assertIn("oauth2-proxy-alphalink.yaml", res)
        self.assertIn("alphalink-sso.yaml", res)
        gen = yaml.safe_load(PLATFORM_KUSTOMIZATION.read_text(encoding="utf-8"))["configMapGenerator"]
        self.assertIn("alphalink-sso.sh=scripts/alphalink-sso.sh",
                      next(g for g in gen if g["name"] == "keycloak-alphalink-sso")["files"])


class JobContract(unittest.TestCase):
    def setUp(self):
        job = next(by_kind(JOB, "Job"))
        self.env = {e["name"]: e["value"] for e in job["spec"]["template"]["spec"]
                    ["containers"][0]["env"]}

    def test_el_job_reconcilia_lo_mismo_que_declara_el_proxy(self):
        # Si estos cuatro valores se separan del ConfigMap, el login entra en bucle.
        self.assertEqual(self.env["REDIRECT_URI"], REDIRECT)
        self.assertEqual(self.env["USER_GROUP"], GRUPO)
        self.assertEqual(self.env["USER_EMAILS"].split(),
                         ["dom.greco@alphalinkcrossfit.com", "daniel.ibanez@alphalinkcrossfit.com"])
        self.assertEqual(self.env["ADMIN_EMAILS"].split(), ["daniel.ibanez@alphalinkcrossfit.com"])
        self.assertEqual(self.env["CLIENT_ID"], "oauth2-proxy")

    def test_el_job_no_puede_crearse_como_root(self):
        sc = next(by_kind(JOB, "Job"))["spec"]["template"]["spec"]["securityContext"]
        self.assertTrue(sc["runAsNonRoot"])
        self.assertEqual(next(by_kind(JOB, "Job"))["spec"]["template"]["spec"]
                         ["containers"][0]["securityContext"]["capabilities"]["drop"], ["ALL"])


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


class ReconcilerCompartido(unittest.TestCase):
    """El cuerpo del reconciler es UN fichero (sso-app-common.sh) que fuentean los
    dos guiones de app: duplicados no deja traer la copia, y el riesgo —pisar los
    redirect_uris de la cadena— es el mismo para las dos. Lo que hace seguro
    desplegarlo: que el ConfigMap de cada Job monte el común y que los literales del
    guion sigan siendo los que declara el Job (si difieren, el Job muere con
    «is immutable» y Dom no entra)."""

    SCRIPTS = ROOT / "platform" / "keycloak-next" / "scripts"

    def test_el_configmap_de_cada_job_lleva_el_comun(self):
        kust = yaml.safe_load(PLATFORM_KUSTOMIZATION.read_text(encoding="utf-8"))
        for nombre in ("keycloak-skirmbooks-sso", "keycloak-alphalink-sso"):
            gen = next(g for g in kust["configMapGenerator"] if g["name"] == nombre)
            self.assertIn("sso-app-common.sh", [f.split("=")[0] for f in gen["files"]],
                          f"{nombre} montaría un guion que fuentea un fichero que no está")

    def test_cada_guion_es_fino_y_declara_lo_de_su_job(self):
        for app in ("skirmbooks", "alphalink"):
            guion = (self.SCRIPTS / f"{app}-sso.sh").read_text(encoding="utf-8")
            self.assertIn('. "${0%/*}/sso-app-common.sh"', guion,
                          f"{app}-sso.sh no fuentea el común: volvería a ser una copia")
            env = {e["name"]: str(e["value"]) for e in
                   next(by_kind(ROOT / "platform" / "keycloak-next" / f"{app}-sso.yaml",
                                "Job"))["spec"]["template"]["spec"]["containers"][0]["env"]}
            for variable, clave in (("EXPECT_REDIRECT_URI", "REDIRECT_URI"),
                                    ("EXPECT_USER_GROUP", "USER_GROUP"),
                                    ("EXPECT_ADMIN_GROUP", "ADMIN_GROUP")):
                self.assertIn(f"{variable}={env[clave]}", guion,
                              f"{app}-sso.sh y su Job no concuerdan en {clave}")


if __name__ == "__main__":
    unittest.main()
