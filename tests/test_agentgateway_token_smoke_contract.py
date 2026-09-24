"""INFRA-248 (INFRA-219 P2, C2): contract of the read-only roles→token smoke.

The smoke runs against a fake kcadm that serves the realm shape audited by
admin API on 2026-09-24. It must pass on that shape, fail closed when a granted
role does not travel in the token (SC-1142/SC-705 class), when the negative
subject gains an agentgateway-* role, and when the claim plumbing (roles
default scope, realm-role mapper) is missing — and it must never mutate the
realm, never pass a secret on argv and never print a token or a secret.
"""

import base64
import functools
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "agentgateway-token-smoke.sh"
JOB = BASE / "agentgateway-token-smoke-job.yaml"
CI = ROOT / ".github" / "workflows" / "ci.yml"

FAKE_SECRET = "not-a-real-client-secret-7f3a"
FAKE_ADMIN_PASSWORD = "not-a-real-admin-password-91c2"
DEFAULTS = ["default-roles-edani", "offline_access", "uma_authorization"]
CHAT_ROLES = [
    "agentgateway-write:gsc", "agentgateway-write:hermes", "agentgateway-write:media",
    "agentgateway-write:social", "agentgateway-write:synapse", "agentgateway-write:workspace",
]
MCP_SCOPE = ["agentgateway-read:analytics", "agentgateway-read:social", "agentgateway-write"]
OC_SCOPE = ["agentgateway-read:gsc", "agentgateway-read:synapse", "cto-office-send"]
REALM_ROLES = sorted(set(CHAT_ROLES + MCP_SCOPE + OC_SCOPE + DEFAULTS + ["company-metrics-read"]))
DEFAULT_SCOPES = ["web-origins", "service_account", "acr", "roles", "profile", "basic", "email"]

REALM_MAPPER_JSON = textwrap.dedent("""\
    {
      "id" : "mapper-realm",
      "name" : "realm roles",
      "protocol" : "openid-connect",
      "protocolMapper" : "oidc-usermodel-realm-role-mapper",
      "config" : {
        "claim.name" : "realm_access.roles",
        "access.token.claim" : "true",
        "multivalued" : "true"
      }
    }
""")


def make_token(azp, roles):
    claims = {"azp": azp, "aud": "mcp.lan.e-dani.com"}
    if roles is not None:
        claims["realm_access"] = {"roles": roles}
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":")).encode()
    ).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def live_shape():
    """Clients as audited on 2026-09-24 (roles trimmed where the count does
    not matter). token = roles the fake server puts in realm_access (None =
    claim absent, which is what Keycloak does when no role passes the scope)."""
    return {
        "chat-agentgateway": {
            "uuid": "u-chat", "fullscope": "false", "public": "false",
            "effective": CHAT_ROLES + DEFAULTS, "scope": CHAT_ROLES,
            "scope_composite": CHAT_ROLES, "token": CHAT_ROLES,
        },
        "company-metrics-agentgateway": {
            "uuid": "u-metrics", "fullscope": "true", "public": "false",
            "effective": ["company-metrics-read"] + DEFAULTS, "scope": ["company-metrics-read"],
            # fullScopeAllowed=true: the composite scope is every realm role.
            "scope_composite": REALM_ROLES, "token": ["company-metrics-read"] + DEFAULTS,
        },
        "cloudblue": {
            "uuid": "u-cloudblue", "fullscope": "false", "public": "false",
            "effective": DEFAULTS, "scope": [], "scope_composite": [], "token": None,
            "default_scopes": DEFAULT_SCOPES + ["litellm-cloudblue"],
        },
        # near-miss sibling: the server-side clientId= filter is a substring match
        "cloudblue-legacy": {
            "uuid": "u-cloudblue-legacy", "fullscope": "true", "public": "false",
            "effective": DEFAULTS + ["agentgateway-write"], "scope": [], "scope_composite": REALM_ROLES,
            "token": DEFAULTS + ["agentgateway-write"],
        },
        "agentgateway-mcp": {
            "uuid": "u-mcp", "fullscope": "false", "public": "false",
            "effective": MCP_SCOPE + DEFAULTS, "scope": MCP_SCOPE, "scope_composite": MCP_SCOPE,
            "token": MCP_SCOPE,
        },
        "openclaw-readonly-agentgateway": {
            "uuid": "u-oc", "fullscope": "false", "public": "false",
            "effective": OC_SCOPE + DEFAULTS, "scope": OC_SCOPE, "scope_composite": OC_SCOPE,
            "token": OC_SCOPE,
        },
        "agentgateway-social-mcp": {
            "uuid": "u-social", "fullscope": "false", "public": "true",
            "effective": None, "scope": ["agentgateway-read:social"],
            "scope_composite": ["agentgateway-read:social"], "token": None,
            "default_scopes": ["web-origins", "acr", "roles", "profile", "basic", "email"],
        },
    }


# Generic fake: "get <endpoint> [--fields F]" serves the file
# <endpoint with / → _>__<F>; a missing file is a 404 (exit 1). The clients
# collection query is a SUBSTRING match, like the real server. Every mutating
# verb is journalled and refused. config credentials must receive secrets via
# KC_CLI_PASSWORD / KC_CLI_CLIENT_SECRET only.
FAKE_KCADM = textwrap.dedent("""\
    #!/bin/sh
    state="${FAKE_STATE:?}"
    printf '%s\\n' "$*" >>"${FAKE_JOURNAL:?}"
    verb="$1"; shift
    case "$verb" in
      config)
        client=""; config=""; user=""; prev=""
        for a in "$@"; do
          case "$prev" in
            --config) config="$a" ;;
            --client) client="$a" ;;
            --user) user="$a" ;;
          esac
          case "$a" in --password|--secret) exit 71 ;; esac
          prev="$a"
        done
        if [ -n "$client" ]; then
          [ "${KC_CLI_CLIENT_SECRET:-}" = "$FAKE_EXPECTED_SECRET" ] || exit 72
          [ -f "$state/token_$client" ] || exit 73
          printf '{"token": "%s", "refreshToken": "r"}\\n' "$(cat "$state/token_$client")" >"$config"
        else
          [ -n "$user" ] || exit 74
          [ "${KC_CLI_PASSWORD:-}" = "$FAKE_EXPECTED_ADMIN_PASSWORD" ] || exit 75
          printf '{}\\n' >"$config"
        fi
        exit 0
        ;;
      get) ;;
      *) exit 99 ;;
    esac
    endpoint="$1"; shift
    fields=""; query=""; prev=""
    for a in "$@"; do
      [ "$prev" = "--fields" ] && fields="$a"
      [ "$prev" = "-q" ] && query="$a"
      prev="$a"
    done
    if [ "$endpoint" = clients ] && [ -n "$query" ]; then
      grep -F ",${query#clientId=}" "$state/clients.csv" || true
      exit 0
    fi
    file="$state/$(printf '%s' "$endpoint" | tr '/' '_')__${fields}"
    [ -f "$file" ] || exit 1
    cat "$file"
    exit 0
""")


def write_state(state, clients, mapper_json=REALM_MAPPER_JSON, roles_scope=True):
    rows = []
    for client_id, c in clients.items():
        u = c["uuid"]
        rows.append(f"{u},{client_id}\n")
        (state / f"clients_{u}__fullScopeAllowed").write_text(c["fullscope"] + "\n")
        (state / f"clients_{u}__publicClient").write_text(c["public"] + "\n")
        (state / f"clients_{u}_default-client-scopes__name").write_text(
            "".join(f"{s}\n" for s in c.get("default_scopes", DEFAULT_SCOPES))
        )
        (state / f"clients_{u}_scope-mappings_realm__name").write_text(
            "".join(f"{r}\n" for r in c["scope"])
        )
        (state / f"clients_{u}_scope-mappings_realm_composite__name").write_text(
            "".join(f"{r}\n" for r in c["scope_composite"])
        )
        if c["effective"] is not None:
            sa = f"sa-{u}"
            (state / f"clients_{u}_service-account-user__id,username").write_text(
                f"{sa},service-account-{client_id}\n"
            )
            (state / f"users_{sa}_role-mappings_realm_composite__name").write_text(
                "".join(f"{r}\n" for r in c["effective"])
            )
            (state / f"clients_{u}_client-secret__value").write_text(FAKE_SECRET + "\n")
            (state / f"token_{client_id}").write_text(make_token(client_id, c["token"]))
    (state / "clients.csv").write_text("".join(rows))
    scopes = "scope-profile,profile\n" + ("scope-roles,roles\n" if roles_scope else "")
    (state / "client-scopes__id,name").write_text(scopes)
    (state / "client-scopes_scope-roles_protocol-mappers_models__id,protocolMapper").write_text(
        "mapper-client,oidc-usermodel-client-role-mapper\nmapper-realm,oidc-usermodel-realm-role-mapper\n"
    )
    (state / "client-scopes_scope-roles_protocol-mappers_models_mapper-realm__").write_text(mapper_json)


def fake_env(tmp, extra=None):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "KCADM": str(tmp / "kcadm.sh"),
        "FAKE_STATE": str(tmp / "state"),
        "FAKE_JOURNAL": str(tmp / "journal"),
        "FAKE_EXPECTED_SECRET": FAKE_SECRET,
        "FAKE_EXPECTED_ADMIN_PASSWORD": FAKE_ADMIN_PASSWORD,
        "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
        "KC_BOOTSTRAP_ADMIN_PASSWORD": FAKE_ADMIN_PASSWORD,
        "KEYCLOAK_URL": "http://keycloak.test.invalid",
    }
    env.update(extra or {})
    return env


class AgentgatewayTokenSmokeContractTest(unittest.TestCase):
    def run_smoke(self, mutate=None, mapper_json=REALM_MAPPER_JSON, roles_scope=True, extra_env=None):
        clients = live_shape()
        if mutate:
            mutate(clients)
        with tempfile.TemporaryDirectory() as raw:
            tmp = pathlib.Path(raw)
            (tmp / "state").mkdir()
            (tmp / "journal").touch()
            (tmp / "kcadm.sh").write_text(FAKE_KCADM)
            (tmp / "kcadm.sh").chmod(0o755)
            write_state(tmp / "state", clients, mapper_json, roles_scope)
            proc = subprocess.run(
                ["/bin/sh", str(SCRIPT)], env=fake_env(tmp, extra_env),
                capture_output=True, text=True, timeout=120,
            )
            journal = (tmp / "journal").read_text()
        return proc, journal

    def assert_no_leak(self, proc, journal):
        tokens = [make_token(k, v["token"]) for k, v in live_shape().items() if v["effective"] is not None]
        for blob in (proc.stdout, proc.stderr, journal):
            self.assertNotIn(FAKE_SECRET, blob)
            self.assertNotIn(FAKE_ADMIN_PASSWORD, blob)
            for token in tokens:
                self.assertNotIn(token.split(".")[1], blob)
        for line in journal.splitlines():
            verb = line.split(" ", 1)[0]
            self.assertIn(verb, ("config", "get"), f"realm mutation attempted: {line}")

    def lines(self, proc):
        return [json.loads(l) for l in proc.stdout.splitlines() if l.startswith("{")]

    def test_live_shape_passes_and_reports_roles(self):
        proc, journal = self.run_smoke()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assert_no_leak(proc, journal)
        out = {l.get("client", l.get("check", l.get("result"))): l for l in self.lines(proc)}
        self.assertEqual(out["realm-role-mapper"]["claim"], "realm_access.roles")
        self.assertEqual(out["chat-agentgateway"]["token_realm_roles"], sorted(CHAT_ROLES))
        self.assertEqual(out["chat-agentgateway"]["agentgateway_roles"], 6)
        self.assertEqual(
            out["company-metrics-agentgateway"]["token_realm_roles"],
            sorted(["company-metrics-read"] + DEFAULTS),
        )
        self.assertIs(out["company-metrics-agentgateway"]["fullScopeAllowed"], True)
        # Negative subject: exact client (not the near-miss sibling), claim
        # absent, zero agentgateway-* entries.
        self.assertEqual(out["cloudblue"]["kind"], "negative")
        self.assertEqual(out["cloudblue"]["token_realm_roles"], [])
        self.assertEqual(out["cloudblue"]["agentgateway_roles"], 0)
        for config_client in ("agentgateway-mcp", "openclaw-readonly-agentgateway", "agentgateway-social-mcp"):
            self.assertEqual(out[config_client]["kind"], "config")
            self.assertNotIn("token_realm_roles", out[config_client])
        self.assertIs(out["agentgateway-social-mcp"]["publicClient"], True)
        self.assertEqual(out["PASS"]["realm_mutations"], 0)
        # C-5: no token of the clients read-grants already mints.
        self.assertNotIn("--client agentgateway-mcp", journal)
        self.assertNotIn("--client openclaw-readonly-agentgateway", journal)
        self.assertIn("--client chat-agentgateway", journal)
        self.assertIn("--client company-metrics-agentgateway", journal)
        self.assertRegex(journal, r"(?m)--client cloudblue$")
        self.assertNotIn("--client cloudblue-legacy", journal)

    def test_granted_role_missing_from_token_fails(self):
        def drop(clients):
            clients["chat-agentgateway"]["token"] = CHAT_ROLES[1:]
        proc, journal = self.run_smoke(drop)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("do not travel uniformly", proc.stderr)
        self.assert_no_leak(proc, journal)

    def test_extra_role_in_token_fails(self):
        def widen(clients):
            clients["chat-agentgateway"]["token"] = CHAT_ROLES + ["default-roles-edani"]
        proc, _ = self.run_smoke(widen)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("do not travel uniformly", proc.stderr)

    def test_negative_subject_with_gateway_role_fails(self):
        def grant(clients):
            c = clients["cloudblue"]
            c["effective"] = DEFAULTS + ["agentgateway-read:social"]
            c["scope"] = c["scope_composite"] = ["agentgateway-read:social"]
            c["token"] = ["agentgateway-read:social"]
        proc, _ = self.run_smoke(grant)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("negative subject cloudblue carries 1 agentgateway-* roles", proc.stderr)

    def test_negative_subject_granted_but_not_scoped_fails(self):
        # The role does not travel (scope filters it) but the SA is no longer
        # role-less: the negative must be re-chosen, not silently accepted.
        def grant(clients):
            clients["cloudblue"]["effective"] = DEFAULTS + ["agentgateway-write"]
        proc, _ = self.run_smoke(grant)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no longer role-less", proc.stderr)

    def test_missing_roles_default_scope_fails(self):
        def strip(clients):
            clients["company-metrics-agentgateway"]["default_scopes"] = ["web-origins", "profile"]
        proc, _ = self.run_smoke(strip)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("company-metrics-agentgateway does not carry the roles default client scope", proc.stderr)

    def test_realm_mapper_wrong_claim_fails(self):
        proc, _ = self.run_smoke(mapper_json=REALM_MAPPER_JSON.replace("realm_access.roles", "roles"))
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not write realm_access.roles", proc.stderr)

    def test_missing_roles_scope_fails(self):
        proc, _ = self.run_smoke(roles_scope=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("expected exactly one roles client scope", proc.stderr)

    def test_config_client_without_any_scope_fails(self):
        def empty(clients):
            clients["agentgateway-social-mcp"]["scope"] = []
        proc, _ = self.run_smoke(empty)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("agentgateway-social-mcp has fullScopeAllowed=false and an empty realm scope", proc.stderr)

    def test_subjects_are_immutable(self):
        for name, value in (
            ("MINTED_CLIENT_IDS", "agentgateway-mcp"),
            ("NEGATIVE_CLIENT_ID", "company-metrics-agentgateway"),
            ("CONFIG_CLIENT_IDS", "agentgateway-social-mcp"),
        ):
            with self.subTest(name=name):
                proc, journal = self.run_smoke(extra_env={name: value})
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("immutable", proc.stderr)
                self.assertEqual(journal, "")

    def test_script_is_read_only_and_image_safe(self):
        script = SCRIPT.read_text()
        code = "\n".join(l for l in script.splitlines() if not l.lstrip().startswith("#"))
        for verb in ("create", "update", "delete"):
            self.assertNotRegex(code, rf'"\$\{{KCADM\}}" {verb}\b')
        # Secrets never on argv; the pinned image ships neither jq nor awk
        # (SC-1215), nor curl.
        self.assertNotIn("--password", code)
        self.assertNotIn("--secret", code)
        for tool in ("jq", "awk", "curl", "python"):
            self.assertNotRegex(code, rf"\b{tool}\b")
        self.assertIn("KC_CLI_PASSWORD=", code)
        self.assertIn("KC_CLI_CLIENT_SECRET=", code)

    def test_job_manifest_contract(self):
        job = JOB.read_text()
        read_grants = (BASE / "agentgateway-read-grants-job.yaml").read_text()
        image = re.search(r"image: (\S+)", read_grants).group(1)
        self.assertIn(f"image: {image}", job)
        self.assertIn("argocd.argoproj.io/hook: PostSync", job)
        self.assertIn('argocd.argoproj.io/sync-wave: "26"', job)
        waves = [
            int(w) for f in BASE.glob("*.yaml") if f != JOB
            for w in re.findall(r'argocd\.argoproj\.io/sync-wave: "(\d+)"', f.read_text())
        ]
        self.assertGreater(26, max(waves), "the smoke must run after every identity reconciler")
        self.assertIn("node-pool: ks5-nvme", job)
        self.assertIn("key: node-role.kubernetes.io/control-plane", job)
        for spark in ("nvidia-dgx", "gx10-ec3d"):
            self.assertNotIn(f"kubernetes.io/hostname: {spark}", job)
        self.assertIn("name: keycloak-bootstrap", job)
        self.assertIn("automountServiceAccountToken: false", job)
        self.assertIn("readOnlyRootFilesystem: true", job)
        self.assertNotIn("args:", job)
        # Egress: keycloak and DNS only.
        policy = job.split("kind: NetworkPolicy", 1)[1]
        self.assertIn("policyTypes: [Egress]", policy)
        self.assertEqual(policy.count("- to:"), 2)
        self.assertIn("podSelector: { matchLabels: { app: keycloak } }", policy)
        self.assertIn("k8s-app: kube-dns", policy)
        self.assertNotIn("ipBlock", policy)
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("  - agentgateway-token-smoke-job.yaml\n", kustomization)
        self.assertIn("agentgateway-token-smoke.sh=scripts/agentgateway-token-smoke.sh", kustomization)
        ci = CI.read_text()
        job_block = ci.split("keycloak-agentgateway-role-contract:", 1)[1].split("\n  keycloak-", 1)[0]
        self.assertIn("sh -n platform/keycloak-next/scripts/agentgateway-token-smoke.sh", job_block)
        self.assertIn("tests/test_agentgateway_token_smoke_contract.py", job_block)


# ---- in-image run (SC-1215: the pinned image is not a general-purpose shell)
_IMAGE = re.search(r"image: (\S+)", JOB.read_text()).group(1)
_DOCKER = shutil.which("docker")
_REQUIRE_IMAGE = os.environ.get("REQUIRE_IMAGE_CONTRACT") == "1"


def _image_ready():
    if not _DOCKER:
        return False
    try:
        return subprocess.run([_DOCKER, "image", "inspect", _IMAGE],
                              capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def in_keycloak_image(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not _image_ready():
            if _REQUIRE_IMAGE:
                self.fail("pinned keycloak image unavailable while REQUIRE_IMAGE_CONTRACT=1")
            self.skipTest("requires docker and the pinned keycloak image")
        return func(self, *args, **kwargs)
    return wrapper


class AgentgatewayTokenSmokeInImageTest(unittest.TestCase):
    @in_keycloak_image
    def test_live_shape_passes_inside_the_pinned_image(self):
        # The fixture dir is bind-mounted, so it must live where the docker
        # daemon can see it (RUNNER_TEMP on ARC; see the impersonation test).
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="kc-token-smoke-", dir=os.environ.get("RUNNER_TEMP") or None))
        try:
            (tmp / "state").mkdir()
            (tmp / "journal").touch()
            (tmp / "kcadm.sh").write_text(FAKE_KCADM)
            write_state(tmp / "state", live_shape())
            for f in [tmp, tmp / "state", *tmp.rglob("*")]:
                f.chmod(0o777 if f.is_dir() or f.name == "kcadm.sh" else 0o666)
            env = fake_env(pathlib.Path("/fixture"))
            cmd = [_DOCKER, "run", "--rm", "--network", "none",
                   "-v", f"{tmp}:/fixture", "-v", f"{BASE / 'scripts'}:/opt/bootstrap:ro"]
            for key, value in env.items():
                if key != "PATH":
                    cmd += ["-e", f"{key}={value}"]
            cmd += ["--entrypoint", "/bin/sh", _IMAGE, "/opt/bootstrap/agentgateway-token-smoke.sh"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('"result":"PASS"', proc.stdout)
            self.assertIn('"client":"cloudblue","kind":"negative"', proc.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
