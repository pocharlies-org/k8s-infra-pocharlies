"""SC-1233 (P0 of SC-1198): dedicated OIDC client `dgx-messages` and
`oauth2-proxy-messages` for messages.lan.e-dani.com.

Two layers:
- static contract of the manifests (flags the architect fixed in D1/D3/D4);
- the reconciler executed INSIDE the pinned Keycloak image (no awk there,
  SC-1215) against a kcadm stub, proving it fails closed when the registered
  redirect is not exact or the example token lacks azp/aud.
"""
import functools
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "dgx-messages-client.sh"
PROXY = BASE / "oauth2-proxy-messages.yaml"
CLIENT = BASE / "dgx-messages-client.yaml"
REDIRECT = "https://messages.lan.e-dani.com/oauth2/callback"
ORIGIN = "https://messages.lan.e-dani.com"

_IMAGE_RE = re.compile(r"image: (\S+/keycloak:26\.6\.2@sha256:[0-9a-f]{64})")


def _pinned_image():
    match = _IMAGE_RE.search(CLIENT.read_text())
    if not match:
        raise AssertionError("pinned keycloak 26.6.2 image not found in the Job manifest")
    return match.group(1)


DOCKER = shutil.which("docker")
IMAGE = _pinned_image()


def _image_ready():
    if not DOCKER:
        return False
    try:
        return subprocess.run(
            [DOCKER, "image", "inspect", IMAGE], capture_output=True, timeout=60
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


IMAGE_READY = _image_ready()
REQUIRE_IMAGE_CONTRACT = os.environ.get("REQUIRE_IMAGE_CONTRACT") == "1"


def in_keycloak_image(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not IMAGE_READY:
            if REQUIRE_IMAGE_CONTRACT:
                self.fail("pinned keycloak image unavailable while REQUIRE_IMAGE_CONTRACT=1")
            self.skipTest("requires docker and the pinned keycloak 26.6.2 image")
        return func(self, *args, **kwargs)
    return wrapper


def _docs(path):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _by_kind_name(docs, kind, name):
    for d in docs:
        if d["kind"] == kind and d["metadata"]["name"] == name:
            return d
    raise AssertionError(f"{kind}/{name} not found")


def _cfg(docs):
    raw = _by_kind_name(docs, "ConfigMap", "oauth2-proxy-messages-config")["data"]["oauth2_proxy.cfg"]
    cfg = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        cfg[key.strip()] = value.strip()
    return cfg


# POSIX-sh kcadm stub. State lives in FIXTURE_DIR so create/update/delete are
# observable: clients.csv (id,clientId; "-q clientId=" is a SUBSTRING match
# like the real server), mappers.csv (id,name) and per-field fixtures.
KCADM_STUB = textwrap.dedent("""\
    #!/bin/sh
    set -eu
    # The reconciler runs with umask 077 as the image user; the runner (another
    # uid) must still read what the stub writes.
    umask 022
    F="${FIXTURE_DIR:?}"
    printf '%s\\n' "$*" | sed 's/secret=[^ ]*/secret=REDACTED/' >> "${STUB_LOG:?}"
    sub="$1"; shift
    [ "$sub" = config ] && exit 0
    res="$1"; shift
    fields=""; q=""; prev=""; name=""
    for a in "$@"; do
      case "$prev" in
        --fields) fields="$a" ;;
        -q) case "$a" in clientId=*) q="${a#clientId=}" ;; esac ;;
        -s) case "$a" in name=*) name="${a#name=}" ;; esac ;;
      esac
      prev="$a"
    done
    case "$sub:$res" in
      create:clients)
        printf 'new-client-uuid,dgx-messages\\n' >> "$F/clients.csv"; exit 0 ;;
      update:clients/*) exit 0 ;;
      create:clients/*/protocol-mappers/models)
        printf 'mapper-%s,%s\\n' "$name" "$name" >> "$F/mappers.csv"; exit 0 ;;
      update:clients/*/protocol-mappers/models/*) exit 0 ;;
      delete:clients/*)
        uuid="${res#clients/}"
        sed -i "/^${uuid},/d" "$F/clients.csv"; exit 0 ;;
      get:clients)
        grep -F "$q" "$F/clients.csv" || true; exit 0 ;;
      get:clients/*/protocol-mappers/models)
        cat "$F/mappers.csv"; exit 0 ;;
      get:clients/*/evaluate-scopes/generate-example-access-token)
        cat "$F/access.json"; exit 0 ;;
      get:clients/*/evaluate-scopes/generate-example-id-token)
        cat "$F/id.json"; exit 0 ;;
      get:clients/*)
        if [ -f "$F/field_$fields" ]; then cat "$F/field_$fields"; exit 0; fi
        printf 'stub: no fixture for field %s\\n' "$fields" >&2; exit 2 ;;
    esac
    printf 'stub: unsupported %s %s\\n' "$sub" "$res" >&2
    exit 2
""")

BOOLS = {
    "enabled": "true",
    "publicClient": "false",
    "standardFlowEnabled": "true",
    "implicitFlowEnabled": "false",
    "directAccessGrantsEnabled": "false",
    "serviceAccountsEnabled": "false",
    "fullScopeAllowed": "false",
}

# Shapes as kcadm pretty-prints them (multi-line, " : " separators).
REDIRECT_JSON = '{\n  "redirectUris" : [ "%s" ]\n}\n' % REDIRECT
ORIGINS_JSON = '{\n  "webOrigins" : [ "%s" ]\n}\n' % ORIGIN
ATTRS_JSON = textwrap.dedent("""\
    {
      "attributes" : {
        "realm_client" : "false",
        "post.logout.redirect.uris" : "https://messages.lan.e-dani.com/",
        "pkce.code.challenge.method" : "S256"
      }
    }
""")
# Measured shape of evaluate-scopes (24-09-2026, openclaw-readonly-ui): a single
# audience serializes as a string, several as an array.
ACCESS_JSON = textwrap.dedent("""\
    {
      "iss" : "https://auth-next.e-dani.com/realms/edani",
      "aud" : "social-api",
      "sub" : "e51253a7-c137-4c6c-9fb9-af9cecd3b147",
      "typ" : "Bearer",
      "azp" : "dgx-messages",
      "scope" : "openid email profile",
      "groups" : [ "/company-operator", "/edani-admins" ]
    }
""")
ID_JSON = textwrap.dedent("""\
    {
      "aud" : "dgx-messages",
      "typ" : "ID",
      "azp" : "dgx-messages"
    }
""")
SECRET = "stub-client-secret-never-printed"


def _fixtures(**overrides):
    files = {
        "clients.csv": "",
        "mappers.csv": "",
        "field_redirectUris": REDIRECT_JSON,
        "field_webOrigins": ORIGINS_JSON,
        "field_attributes": ATTRS_JSON,
        "access.json": ACCESS_JSON,
        "id.json": ID_JSON,
    }
    for field, value in BOOLS.items():
        files[f"field_{field}"] = value + "\n"
    files.update(overrides)
    return files


def _run(files, mode="ensure"):
    parent = os.environ.get("RUNNER_TEMP") or None
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="kc-dgx-messages-", dir=parent))
    try:
        (tmp / "kcadm.sh").write_text(KCADM_STUB)
        # Pre-created world-writable: on the ARC runners the container uid is
        # not the runner uid, and a log born inside the container is unreadable.
        (tmp / "stub.log").write_text("")
        for name, content in files.items():
            (tmp / name).write_text(content)
        for f in tmp.iterdir():
            f.chmod(0o666)
        (tmp / "kcadm.sh").chmod(0o755)
        tmp.chmod(0o777)
        proc = subprocess.run(
            [
                DOCKER, "run", "--rm",
                "-v", f"{tmp}:/fixture",
                "-v", f"{BASE / 'scripts'}:/opt/bootstrap:ro",
                "-e", f"MODE={mode}",
                "-e", "KCADM=/fixture/kcadm.sh",
                "-e", "FIXTURE_DIR=/fixture",
                "-e", "STUB_LOG=/fixture/stub.log",
                "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=stub-user",
                "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD=stub-password",
                "-e", f"DGX_MESSAGES_CLIENT_SECRET={SECRET}",
                "-e", "HOME=/tmp",
                "--entrypoint", "/bin/sh", IMAGE,
                "/opt/bootstrap/dgx-messages-client.sh",
            ],
            capture_output=True, text=True, timeout=120,
        )
        log_file = tmp / "stub.log"
        log = log_file.read_text() if log_file.exists() else ""
        return proc.returncode, proc.stdout, proc.stderr, log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class DgxMessagesManifestContractTest(unittest.TestCase):
    def setUp(self):
        self.proxy = _docs(PROXY)
        self.cfg = _cfg(self.proxy)

    def test_kustomization_wires_the_new_resources(self):
        kust = yaml.safe_load((BASE / "kustomization.yaml").read_text())
        self.assertIn("oauth2-proxy-messages.yaml", kust["resources"])
        self.assertIn("dgx-messages-client.yaml", kust["resources"])
        gens = {g["name"]: g for g in kust["configMapGenerator"]}
        self.assertEqual(
            gens["keycloak-dgx-messages-client"]["files"],
            ["dgx-messages-client.sh=scripts/dgx-messages-client.sh"],
        )
        self.assertNotIn("manual/dgx-messages-client-rollback-job.yaml", kust["resources"])

    def test_proxy_flags(self):
        c = self.cfg
        self.assertEqual(c["provider"], '"keycloak-oidc"')
        self.assertEqual(c["redirect_url"], f'"{REDIRECT}"')
        self.assertEqual(c["scope"], '"openid email profile"')
        self.assertEqual(c["cookie_name"], '"_messages_sso"')
        self.assertNotIn("cookie_domains", c)
        self.assertEqual(c["cookie_secure"], "true")
        self.assertEqual(c["cookie_httponly"], "true")
        self.assertEqual(c["cookie_samesite"], '"lax"')
        # realm edani accessTokenLifespan=300s (measured 24-09-2026) minus 1 min.
        self.assertEqual(c["cookie_refresh"], '"4m"')
        # <= ssoSessionMaxLifespan=31536000s.
        self.assertEqual(c["cookie_expire"], '"8760h"')
        self.assertEqual(c["pass_access_token"], "true")
        self.assertEqual(c["set_xauthrequest"], "true")
        self.assertEqual(c["set_authorization_header"], "false")
        self.assertEqual(c["skip_provider_button"], "true")
        self.assertEqual(c["whitelist_domains"], '[ "messages.lan.e-dani.com", "auth-next.e-dani.com" ]')
        self.assertEqual(c["allowed_groups"], '[ "/edani-admins", "/edani-operators", "/edani-users" ]')
        self.assertEqual(c["code_challenge_method"], '"S256"')
        dep = _by_kind_name(self.proxy, "Deployment", "oauth2-proxy-messages")
        env = {e["name"]: e for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["OAUTH2_PROXY_CLIENT_ID"]["value"], "dgx-messages")
        for key in ("OAUTH2_PROXY_CLIENT_SECRET", "OAUTH2_PROXY_COOKIE_SECRET"):
            self.assertEqual(env[key]["valueFrom"]["secretKeyRef"]["name"], "dgx-messages-sso-secrets")

    def test_middlewares(self):
        fa = _by_kind_name(self.proxy, "Middleware", "sso-messages-forward-auth")["spec"]["forwardAuth"]
        self.assertEqual(fa["address"], "http://oauth2-proxy-messages.keycloak.svc.cluster.local:4180/oauth2/auth")
        self.assertEqual(
            fa["authResponseHeaders"],
            [
                "X-Auth-Request-Access-Token",
                "X-Auth-Request-User",
                "X-Auth-Request-Email",
                "X-Auth-Request-Preferred-Username",
                "X-Auth-Request-Groups",
                "Authorization",
                "X-Forwarded-User",
            ],
        )
        self.assertIn("_messages_sso", fa["addAuthCookiesToResponse"])
        errors = _by_kind_name(self.proxy, "Middleware", "sso-messages-errors")["spec"]["errors"]
        self.assertEqual(errors["service"], {"name": "oauth2-proxy-messages", "port": 4180})
        chain = _by_kind_name(self.proxy, "Middleware", "sso-messages-chain")["spec"]["chain"]
        self.assertEqual(
            [m["name"] for m in chain["middlewares"]],
            ["sso-messages-errors", "sso-messages-forward-auth"],
        )

    def test_proxy_ingress_only_from_traefik_lan(self):
        np = _by_kind_name(self.proxy, "NetworkPolicy", "oauth2-proxy-messages")["spec"]
        self.assertEqual(np["policyTypes"], ["Ingress", "Egress"])
        self.assertEqual(len(np["ingress"]), 1)
        peers = np["ingress"][0]["from"]
        self.assertEqual(len(peers), 1)
        self.assertEqual(
            peers[0]["namespaceSelector"]["matchLabels"],
            {"kubernetes.io/metadata.name": "traefik-lan"},
        )
        self.assertNotIn("ipBlock", peers[0])

    def test_external_secret_and_job(self):
        docs = _docs(CLIENT)
        es = _by_kind_name(docs, "ExternalSecret", "dgx-messages-sso-secrets")["spec"]
        self.assertEqual(
            sorted(d["remoteRef"]["key"] for d in es["data"]),
            ["keycloak-next-dgx-messages/client_secret", "keycloak-next-dgx-messages/cookie_secret"],
        )
        job = _by_kind_name(docs, "Job", "keycloak-dgx-messages-client")
        self.assertEqual(job["metadata"]["annotations"]["argocd.argoproj.io/hook"], "PostSync")
        env = {e["name"]: e for e in job["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["REDIRECT_URI"]["value"], REDIRECT)
        self.assertEqual(env["SOCIAL_AUDIENCE"]["value"], "social-api")
        for path in (PROXY, CLIENT):
            self.assertNotRegex(path.read_text(), r"(?i)(client|cookie)_secret\s*[:=]\s*['\"]?[A-Za-z0-9_-]{16,}")

    def test_script_uses_only_image_commands(self):
        script = SCRIPT.read_text()
        code = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
        self.assertNotRegex(code, r"\bawk\b")
        self.assertNotIn("set -x", code)
        self.assertIn('-s "redirectUris=[\\"${REDIRECT_URI}\\"]"', script)
        self.assertIn("-s serviceAccountsEnabled=false", script)
        self.assertIn("-s directAccessGrantsEnabled=false", script)
        self.assertIn("'config.\"id.token.claim\"=false'", script)
        self.assertIn("evaluate-scopes/$1", script)


class DgxMessagesReconcilerInImageTest(unittest.TestCase):
    @in_keycloak_image
    def test_ensure_creates_client_and_reports_verified_claims(self):
        rc, out, err, log = _run(_fixtures())
        self.assertEqual(rc, 0, err)
        self.assertIn('"redirect_exact":true', out)
        self.assertIn('"azp":"dgx-messages"', out)
        self.assertIn("create clients", log)
        self.assertIn("name=dgx-messages-social-api-audience", log)
        self.assertIn("name=dgx-messages-groups", log)
        self.assertNotIn(SECRET, out + err)

    @in_keycloak_image
    def test_substring_near_miss_is_not_updated(self):
        rc, out, err, log = _run(_fixtures(**{"clients.csv": "other-uuid,dgx-messages-v2\n"}))
        self.assertEqual(rc, 0, err)
        self.assertNotIn("update clients/other-uuid", log)
        self.assertIn("create clients", log)

    @in_keycloak_image
    def test_existing_client_is_updated(self):
        rc, out, err, log = _run(_fixtures(**{"clients.csv": "known-uuid,dgx-messages\n"}))
        self.assertEqual(rc, 0, err)
        self.assertIn("update clients/known-uuid", log)

    @in_keycloak_image
    def test_fails_when_redirect_is_not_exact(self):
        wide = '{\n  "redirectUris" : [ "%s", "https://messages.lan.e-dani.com/*" ]\n}\n' % REDIRECT
        rc, out, err, _ = _run(_fixtures(field_redirectUris=wide))
        self.assertNotEqual(rc, 0)
        self.assertIn("redirectUris registered", err)
        self.assertNotIn('"redirect_exact":true', out)

    @in_keycloak_image
    def test_fails_on_wrong_azp(self):
        rc, _, err, _ = _run(_fixtures(**{"access.json": ACCESS_JSON.replace('"azp" : "dgx-messages"', '"azp" : "oauth2-proxy"')}))
        self.assertNotEqual(rc, 0)
        self.assertIn("wrong azp", err)

    @in_keycloak_image
    def test_fails_without_social_api_audience(self):
        rc, _, err, _ = _run(_fixtures(**{"access.json": ACCESS_JSON.replace('"aud" : "social-api"', '"aud" : "account"')}))
        self.assertNotEqual(rc, 0)
        self.assertIn("aud does not contain social-api", err)

    @in_keycloak_image
    def test_accepts_audience_array(self):
        multi = ACCESS_JSON.replace('"aud" : "social-api"', '"aud" : [ "account", "social-api" ]')
        rc, _, err, _ = _run(_fixtures(**{"access.json": multi}))
        self.assertEqual(rc, 0, err)

    @in_keycloak_image
    def test_fails_when_id_token_carries_social_api(self):
        leaky = ID_JSON.replace('"aud" : "dgx-messages"', '"aud" : [ "dgx-messages", "social-api" ]')
        rc, _, err, _ = _run(_fixtures(**{"id.json": leaky}))
        self.assertNotEqual(rc, 0)
        self.assertIn("id token carries social-api", err)

    @in_keycloak_image
    def test_rollback_deletes_only_the_exact_client(self):
        csv = "known-uuid,dgx-messages\nother-uuid,dgx-messages-v2\n"
        rc, out, err, log = _run(_fixtures(**{"clients.csv": csv}), mode="rollback")
        self.assertEqual(rc, 0, err)
        self.assertIn('"present":false', out)
        self.assertIn("delete clients/known-uuid", log)
        self.assertNotIn("delete clients/other-uuid", log)


if __name__ == "__main__":
    unittest.main()
