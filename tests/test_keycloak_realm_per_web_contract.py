"""SC-2822 (20-10-2026): un realm de Keycloak por web, siempre separado
(docs/sso-por-app.md).

Dani no podía estar en horarios.alphalinkcrossfit.com con la cuenta del gimnasio y
en dgx.e-dani.com con la suya a la vez: Keycloak guarda una sesión por realm y
navegador, y todas las webs compartían `edani`. Este test fija la norma sobre el
chart platform/keycloak-sso renderizado y sobre todas las IngressRoute del repo:

  - ningún host está en dos realms, y ningún realm nuevo se llama edani o master;
  - cada proxy apunta a SU realm, con cookie pegada al host (sin cookie_domains) y
    callbacks exactos (sin comodines);
  - una ruta que usa sso-<realm>-chain sirve solo hosts de ese realm;
  - las cadenas viejas del realm compartido (sso-chain y las dedicadas sobre
    `edani`) solo pueden ENCOGER: un host nuevo ahí rompe este test. Cuando una
    web se migra, sale de LEGACY en el mismo PR.
"""
import pathlib
import re
import shutil
import subprocess
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHART = ROOT / "platform" / "keycloak-sso"
REALMS = CHART / "realms.yaml"

# Hosts que aún entran por una cadena del realm compartido `edani`. Solo se borra.
LEGACY = {
    "sso-chain": {
        "adguard-setup.e-dani.com", "adguard.e-dani.com", "agentgateway-mcp-stg.e-dani.com",
        "alertmanager.e-dani.com", "argocd.e-dani.com", "aurora-api.e-dani.com",
        "aurora.e-dani.com", "brain-ingest-k8s.e-dani.com", "brain-k8s.e-dani.com",
        "code.lan.e-dani.com", "company.e-dani.com", "dgx.e-dani.com", "dgx.lan.e-dani.com",
        "grafana.e-dani.com", "ha-dashboard.e-dani.com", "home-assistant.e-dani.com",
        "jarvis.e-dani.com", "keep-api.e-dani.com", "keep.e-dani.com", "libreplay.e-dani.com",
        "longhorn.e-dani.com", "longhorn.lan.e-dani.com", "minio.e-dani.com",
        "oficinas.e-dani.com", "openclaw-k8s-webhooks.e-dani.com", "openclaw.e-dani.com",
        "paseo.e-dani.com", "paseocasa.e-dani.com", "paseocb.e-dani.com", "s3.e-dani.com",
        "skirmshop-s3-console.e-dani.com", "synapse.e-dani.com", "synapse.lan.e-dani.com",
        "teslamate.e-dani.com", "vm.e-dani.com", "whatsapp-pro.e-dani.com",
    },
    "sso-chat-chain": {"chat.e-dani.com"},
    "sso-hindsight-chain": {"hindsight.e-dani.com"},
    "sso-openclaw-readonly-chain": {"openclaw-k8s-readonly.e-dani.com"},
    "sso-skirmbooks-chain": {"skirmbooks.e-dani.com"},
    "sso-skirmshop-chain": {"admin.skirmshop.es"},
    "sso-messages-chain": {"messages.lan.e-dani.com"},
}


def render():
    helm = shutil.which("helm")
    if not helm:
        raise unittest.SkipTest("helm no está instalado")
    out = subprocess.run([helm, "template", "keycloak-sso", str(CHART), "-f", str(REALMS),
                          "--set", "google.item=test"],
                         check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def sso_routes():
    """(fichero, nombre del middleware, host) de cada ruta del repo con una cadena sso-*."""
    for path in ROOT.rglob("*.yaml"):
        if {".git", "tests", ".claude"} & set(path.relative_to(ROOT).parts):
            continue
        try:
            docs = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue
        for d in docs:
            if not isinstance(d, dict) or d.get("kind") != "IngressRoute":
                continue
            for route in d["spec"].get("routes", []):
                for mw in route.get("middlewares") or []:
                    if mw["name"].startswith("sso-") and mw["name"].endswith("-chain"):
                        for host in re.findall(r"Host\(`([^`]+)`\)", route["match"]):
                            yield path.relative_to(ROOT), mw["name"], host


class RealmsContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.realms = yaml.safe_load(REALMS.read_text(encoding="utf-8"))["realms"]
        cls.docs = render()

    def of(self, kind, name):
        return next(d for d in self.docs if d["kind"] == kind and d["metadata"]["name"] == name)

    def test_cada_host_en_un_solo_realm(self):
        names = [r["name"] for r in self.realms]
        self.assertEqual(len(names), len(set(names)))
        self.assertFalse({"edani", "master"} & set(names))
        hosts = [h for r in self.realms for h in r["hosts"]]
        self.assertEqual(len(hosts), len(set(hosts)), "un host está en dos realms")
        legacy = set().union(*LEGACY.values())
        self.assertFalse(legacy & set(hosts), "un host migrado sigue en LEGACY")

    def test_cada_proxy_es_de_su_realm_y_de_su_host(self):
        for r in self.realms:
            cfg = self.of("ConfigMap", f"oauth2-proxy-{r['name']}-config")["data"]["oauth2_proxy.cfg"]
            lineas = [l.strip() for l in cfg.splitlines() if not l.strip().startswith("#")]
            self.assertFalse([l for l in lineas if l.startswith("cookie_domains")], r["name"])
            self.assertIn(f'oidc_issuer_url = "https://auth-next.e-dani.com/realms/{r["name"]}"', cfg)
            for clave in ("login_url", "redeem_url", "profile_url", "validate_url", "oidc_jwks_url"):
                url = re.search(rf'^{clave} = "([^"]+)"', cfg, re.M).group(1)
                self.assertIn(f"/realms/{r['name']}/", url, f"{r['name']}: {clave}")
            dep = self.of("Deployment", f"oauth2-proxy-{r['name']}")
            env = dep["spec"]["template"]["spec"]["containers"][0]["envFrom"]
            self.assertEqual(env, [{"secretRef": {"name": f"oauth2-proxy-{r['name']}-secrets"}}])

    def test_callbacks_exactos_sin_comodines(self):
        cm = self.of("ConfigMap", "keycloak-sso-realms")["data"]
        for r in self.realms:
            realm = yaml.safe_load(cm[f"{r['name']}.yaml"])
            self.assertEqual(realm["realm"], r["name"])
            self.assertFalse(realm["registrationAllowed"])
            client = next(c for c in realm["clients"] if c["clientId"] == "oauth2-proxy")
            self.assertEqual(client["redirectUris"],
                             [f"https://{h}/oauth2/callback" for h in r["hosts"]])
            self.assertFalse([u for u in client["redirectUris"] if "*" in u])
            for idp in realm.get("identityProviders", []):
                # Primer login con Google: enlaza o falla; nunca crea un usuario.
                self.assertEqual(idp["firstBrokerLoginFlowAlias"], "link-existing-only")
                # security: solo email verificado por Google y del dominio del realm.
                cfg = idp["config"]
                self.assertEqual((cfg["filteredByClaim"], cfg["claimFilterName"], cfg["claimFilterValue"]),
                                 ("true", "email_verified", "true"))
                self.assertEqual(cfg["hostedDomain"], r["googleHostedDomain"])
                flow = next(f for f in realm["authenticationFlows"] if f["alias"] == "link-existing-only")
                self.assertNotIn("idp-create-user-if-unique",
                                 [e["authenticator"] for e in flow["authenticationExecutions"]])

    def test_solo_401_se_reescribe_al_login(self):
        for r in self.realms:
            err = self.of("Middleware", f"sso-{r['name']}-errors")
            self.assertEqual(err["spec"]["errors"]["status"], ["401"])

    def test_el_job_concilia_antes_que_los_proxies(self):
        job = self.of("Job", "keycloak-sso-config")
        ann = job["metadata"]["annotations"]
        self.assertEqual((ann["argocd.argoproj.io/hook"], ann["argocd.argoproj.io/sync-wave"]),
                         ("Sync", "-1"))
        env = {e["name"]: e.get("value") for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
        # Solo los ficheros del chart: `edani` y `master` no los toca.
        self.assertEqual(env["IMPORT_FILES_LOCATIONS"], "/config/*.yaml")


class RoutesContract(unittest.TestCase):
    def test_una_cadena_de_realm_solo_sirve_hosts_de_ese_realm(self):
        realms = {f"sso-{r['name']}-chain": set(r["hosts"])
                  for r in yaml.safe_load(REALMS.read_text(encoding="utf-8"))["realms"]}
        for path, chain, host in sso_routes():
            if chain in realms:
                self.assertIn(host, realms[chain], f"{path}: {host} por {chain}")
            else:
                self.assertIn(host, LEGACY.get(chain, set()),
                              f"{path}: {host} entra por {chain}, una cadena del realm compartido. "
                              "Una web nueva va en platform/keycloak-sso/realms.yaml con su realm")


if __name__ == "__main__":
    unittest.main()
