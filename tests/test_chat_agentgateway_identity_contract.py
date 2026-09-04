import base64
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "chat-agentgateway-client.sh"

# Minimal stateful stand-in for kcadm.sh. State lives in a JSON file so each
# subprocess invocation sees what the previous one changed, and every call is
# appended to a log the tests assert on (no role creation/deletion, exact
# client shape). Realm roles in the minted token follow Keycloak semantics for
# fullScopeAllowed=false: only roles present in the client's realm scope
# mappings are emitted.
FAKE_KCADM = textwrap.dedent('''\
    #!/usr/bin/env python3
    import base64, json, os, sys

    STATE_PATH = os.environ["FAKE_KC_STATE"]
    with open(os.environ["FAKE_KCADM_LOG"], "a") as log:
        log.write(" ".join(sys.argv[1:]) + "\\n")
    with open(STATE_PATH) as fh:
        state = json.load(fh)

    def save():
        with open(STATE_PATH, "w") as fh:
            json.dump(state, fh)

    args = sys.argv[1:]
    opts = {"-s": [], "-q": [], "fields": None, "config": None}
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-s", "-q"):
            opts[a].append(args[i + 1]); i += 2
        elif a == "--fields":
            opts["fields"] = args[i + 1]; i += 2
        elif a == "--config":
            opts["config"] = args[i + 1]; i += 2
        elif a in ("-r", "--realm", "--server", "--user", "--password", "--client", "--secret", "-b", "--uid", "--rolename", "--format"):
            opts[a] = args[i + 1]; i += 2
        elif a == "--noquotes":
            i += 1
        else:
            positional.append(a); i += 1

    def csv(rows, fields):
        for row in rows:
            print(",".join(str(row.get(f, "")).lower() if isinstance(row.get(f), bool) else str(row.get(f, "")) for f in fields))

    def find_client(client_id):
        for uuid, c in state["clients"].items():
            if c["clientId"] == client_id:
                return uuid, c
        return None, None

    def sa_username(uuid):
        return "service-account-" + state["clients"][uuid]["clientId"]

    def role_users(role):
        users = []
        for uuid, c in state["clients"].items():
            if role in c.get("sa_roles", []):
                users.append({"username": sa_username(uuid)})
        for u in state.get("humans", []):
            if role in u.get("roles", []):
                users.append({"username": u["username"]})
        return users

    verb = positional[0]
    if verb == "config":
        if opts.get("--realm") == "master":
            sys.exit(0)
        uuid, c = find_client(opts["--client"])
        if c is None or c["secret"] != opts["--secret"]:
            sys.exit(1)
        roles = list(c.get("sa_roles", []))
        if c.get("fullScopeAllowed") == "false":
            roles = [r for r in roles if r in c.get("scope_roles", [])]
        aud = ["account"] + [m["audience"] for m in c.get("mappers", {}).values()]
        claims = {"azp": c["clientId"], "aud": aud, "realm_access": {"roles": roles}}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        with open(opts["config"], "w") as fh:
            json.dump({"endpoints": {"x": {"realm": {"token": "hdr." + payload + ".sig"}}}}, fh)
        sys.exit(0)

    if verb == "add-roles":
        uuid = opts["--uid"][len("sa-"):]
        state["clients"][uuid].setdefault("sa_roles", []).append(opts["--rolename"]); save(); sys.exit(0)

    endpoint = positional[1]
    parts = endpoint.split("/")
    fields = (opts["fields"] or "").split(",") if opts["fields"] else []

    if verb == "get":
        if endpoint == "clients":
            wanted = [q.split("=", 1)[1] for q in opts["-q"] if q.startswith("clientId=")]
            rows = [{"id": u} for u, c in state["clients"].items() if not wanted or c["clientId"] in wanted]
            csv(rows, fields); sys.exit(0)
        if parts[0] == "clients" and len(parts) == 2:
            csv([state["clients"][parts[1]]], fields); sys.exit(0)
        if parts[0] == "clients" and parts[2] == "protocol-mappers":
            rows = [{"id": mid, "name": m["name"]} for mid, m in state["clients"][parts[1]].get("mappers", {}).items()]
            csv(rows, fields); sys.exit(0)
        if parts[0] == "clients" and parts[2] == "scope-mappings":
            csv([{"name": r} for r in state["clients"][parts[1]].get("scope_roles", [])], fields); sys.exit(0)
        if parts[0] == "clients" and parts[2] == "service-account-user":
            csv([{"id": "sa-" + parts[1], "username": sa_username(parts[1])}], fields); sys.exit(0)
        if parts[0] == "roles" and len(parts) == 2:
            role = state["roles"].get(parts[1])
            if role is None:
                sys.exit(1)
            csv([{"id": role["id"], "composite": role["composite"]}], fields); sys.exit(0)
        if parts[0] == "roles" and parts[2] == "users":
            csv(role_users(parts[1]), fields); sys.exit(0)
        if parts[0] == "roles" and parts[2] == "groups":
            csv([{"path": g} for g in state["roles"].get(parts[1], {}).get("groups", [])], fields); sys.exit(0)
        if parts[0] == "users" and parts[2] == "role-mappings":
            uuid = parts[1][len("sa-"):]
            csv([{"name": r} for r in state["clients"][uuid].get("sa_roles", [])], fields); sys.exit(0)
        sys.exit(99)

    settings = dict(s.split("=", 1) for s in opts["-s"])
    if verb == "create" and endpoint == "clients":
        uuid = "uuid-" + settings["clientId"]
        state["clients"][uuid] = dict(settings, sa_roles=[], scope_roles=[], mappers={})
        save(); sys.exit(0)
    if verb == "update" and parts[0] == "clients" and len(parts) == 2:
        state["clients"][parts[1]].update(settings); save(); sys.exit(0)
    if verb in ("create", "update") and parts[0] == "clients" and parts[2] == "protocol-mappers":
        c = state["clients"][parts[1]]
        mid = parts[4] if len(parts) > 4 else "mapper-" + settings["name"]
        c.setdefault("mappers", {})[mid] = {"name": settings["name"], "audience": settings.get('config."included.custom.audience"', "")}
        save(); sys.exit(0)
    if verb == "create" and parts[0] == "clients" and parts[2] == "scope-mappings":
        for entry in json.loads(opts["-b"]):
            state["clients"][parts[1]].setdefault("scope_roles", []).append(entry["name"])
        save(); sys.exit(0)
    if verb == "create" and endpoint == "roles":
        state["roles"][settings["name"]] = {"id": "role-" + settings["name"], "composite": False}
        save(); sys.exit(0)
    if verb == "delete" and parts[0] == "clients":
        state["clients"].pop(parts[1], None); save(); sys.exit(0)
    if verb == "delete" and parts[0] == "roles":
        state["roles"].pop(parts[1], None); save(); sys.exit(0)
    sys.exit(99)
''')


def _run(mode, state, env_overrides=None):
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary = pathlib.Path(temporary_directory)
        kcadm = temporary / "kcadm.sh"
        kcadm.write_text(FAKE_KCADM)
        kcadm.chmod(0o755)
        log = temporary / "kcadm.log"
        log.write_text("")
        state_path = temporary / "state.json"
        state_path.write_text(json.dumps(state))
        environment = os.environ.copy()
        environment.update({
            "KCADM": str(kcadm),
            "FAKE_KCADM_LOG": str(log),
            "FAKE_KC_STATE": str(state_path),
            "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
            "KC_BOOTSTRAP_ADMIN_PASSWORD": "test-password",
            "CHAT_AGENTGATEWAY_CLIENT_SECRET": "chat-secret",
            "MODE": mode,
        })
        environment.update(env_overrides or {})
        result = subprocess.run(
            ["/bin/sh", str(SCRIPT)],
            capture_output=True,
            text=True,
            env=environment,
        )
        return result, log.read_text().splitlines(), json.loads(state_path.read_text())


def _state(role_present=True, client=None, humans=None):
    state = {"clients": {}, "roles": {}, "humans": humans or []}
    if role_present:
        state["roles"]["agentgateway-write:media"] = {"id": "role-media", "composite": False}
    if client is not None:
        state["clients"]["uuid-chat-agentgateway"] = client
    return state


def _existing_client(**extra):
    client = {
        "clientId": "chat-agentgateway", "enabled": "true", "publicClient": "false",
        "standardFlowEnabled": "false", "directAccessGrantsEnabled": "false",
        "serviceAccountsEnabled": "true", "fullScopeAllowed": "false",
        "secret": "chat-secret", "sa_roles": ["agentgateway-write:media"],
        "scope_roles": ["agentgateway-write:media"],
        "mappers": {"m1": {"name": "chat-agentgateway-audience", "audience": "mcp.lan.e-dani.com"}},
    }
    client.update(extra)
    return client


class ChatAgentGatewayIdentityContractTest(unittest.TestCase):
    def test_reconciler_is_fixed_scope_and_never_owns_the_domain_role(self):
        script = SCRIPT.read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-chat-agentgateway}"', script)
        self.assertIn('ROLE_NAME="${ROLE_NAME:-agentgateway-write:media}"', script)
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', script)
        self.assertIn('FORBIDDEN_REALM_ROLE="${FORBIDDEN_REALM_ROLE:-agentgateway-write}"', script)
        self.assertIn('RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"', script)
        self.assertIn("chat-agentgateway:agentgateway-write:media)", script)
        self.assertIn('CLIENT_SECRET="${CHAT_AGENTGATEWAY_CLIENT_SECRET:-}"', script)
        self.assertIn("unsupported immutable client/role pair", script)
        self.assertIn("serviceAccountsEnabled=true", script)
        self.assertIn("standardFlowEnabled=false", script)
        self.assertIn("directAccessGrantsEnabled=false", script)
        self.assertIn("fullScopeAllowed=false", script)
        self.assertIn("oidc-audience-mapper", script)
        self.assertIn('"clients/${CLIENT_UUID}/scope-mappings/realm"', script)
        self.assertIn("ensure_role_scope_mapping", script)
        self.assertIn('"roles/${ROLE_NAME}/users" -q first=0 -q max=2', script)
        self.assertIn('"roles/${ROLE_NAME}/groups" -q first=0 -q max=2', script)
        self.assertIn("assert_single_write_role", script)
        self.assertIn("verify_minted_claims", script)
        self.assertIn("rollback_identity", script)
        # The domain role belongs to agentgateway-domain-roles.sh: never created
        # or deleted here, and the reconciler refuses to run without it.
        self.assertNotIn("create roles", script)
        self.assertNotIn('delete "roles/', script)
        self.assertIn("the agentgateway-domain-roles hook owns it", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${CHAT_AGENTGATEWAY_CLIENT_SECRET}"', script)
        self.assertNotIn('echo "${token}"', script)

    def test_ensure_creates_the_client_and_maps_only_the_media_role(self):
        result, calls, state = _run("ensure", _state())
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_id":"chat-agentgateway","realm_role":"agentgateway-write:media","present":true', result.stdout)
        self.assertNotIn("chat-secret", result.stdout + result.stderr)
        self.assertTrue(any(c.startswith("create clients ") and "clientId=chat-agentgateway" in c for c in calls))
        self.assertTrue(any(c.startswith("add-roles ") and "--rolename agentgateway-write:media" in c for c in calls))
        self.assertFalse(any(c.startswith("create roles") for c in calls))
        self.assertFalse(any(c.startswith("delete roles") for c in calls))
        client = state["clients"]["uuid-chat-agentgateway"]
        self.assertEqual(["agentgateway-write:media"], client["sa_roles"])
        self.assertEqual(["agentgateway-write:media"], client["scope_roles"])
        self.assertEqual("false", client["fullScopeAllowed"])
        self.assertEqual(["mcp.lan.e-dani.com"], [m["audience"] for m in client["mappers"].values()])

    def test_ensure_is_idempotent_on_a_converged_client(self):
        result, calls, _ = _run("ensure", _state(client=_existing_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(any(c.startswith("create clients") for c in calls))
        self.assertFalse(any(c.startswith("add-roles") for c in calls))
        self.assertTrue(any(c.startswith("update clients/uuid-chat-agentgateway ") for c in calls))

    def test_ensure_refuses_to_run_before_the_domain_role_exists(self):
        result, calls, state = _run("ensure", _state(role_present=False))
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-write:media is missing; the agentgateway-domain-roles hook owns it", result.stderr)
        self.assertFalse(any(c.startswith("create") for c in calls))
        self.assertEqual({}, state["clients"])

    def test_ensure_fails_when_the_service_account_holds_another_write_role(self):
        client = _existing_client(sa_roles=["agentgateway-write:media", "agentgateway-write"])
        result, _, _ = _run("ensure", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("service account holds an extra AgentGateway write role", result.stderr)

    def test_ensure_fails_when_a_human_holds_the_media_role(self):
        humans = [{"username": "dani", "roles": ["agentgateway-write:media"]}]
        result, calls, _ = _run("ensure", _state(humans=humans))
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-write:media has an unauthorized user", result.stderr)
        self.assertFalse(any(c.startswith("add-roles") for c in calls))

    def test_ensure_rejects_a_token_that_carries_the_umbrella_role(self):
        # Scope-mapping drift: the umbrella role leaks into the scope even though
        # the service account mapping looks right on paper.
        client = _existing_client(scope_roles=["agentgateway-write:media", "agentgateway-write"],
                                  sa_roles=["agentgateway-write:media", "agentgateway-write"])
        result, _, _ = _run("audit", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("extra AgentGateway write role", result.stderr)

    def test_rollback_deletes_the_client_but_retains_the_domain_role(self):
        result, calls, state = _run("rollback", _state(client=_existing_client()),
                                    {"CHAT_AGENTGATEWAY_CLIENT_SECRET": ""})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_present":false,"role_retained":true', result.stdout)
        self.assertTrue(any(c.startswith("delete clients/uuid-chat-agentgateway ") for c in calls))
        self.assertFalse(any(c.startswith("delete roles") for c in calls))
        self.assertIn("agentgateway-write:media", state["roles"])
        self.assertEqual({}, state["clients"])

    def test_immutable_pair_and_secret_are_enforced_before_any_call(self):
        result, calls, _ = _run("ensure", _state(), {"CLIENT_ID": "chat-agentgateway-2"})
        self.assertEqual(1, result.returncode)
        self.assertIn("unsupported immutable client/role pair", result.stderr)
        self.assertEqual([], calls)
        result, calls, _ = _run("ensure", _state(), {"CHAT_AGENTGATEWAY_CLIENT_SECRET": ""})
        self.assertEqual(1, result.returncode)
        self.assertIn("client secret is empty", result.stderr)
        self.assertEqual([], calls)

    def test_manifest_uses_one_vault_property_and_a_hardened_postsync_job(self):
        manifest = (BASE / "chat-agentgateway-client.yaml").read_text()
        self.assertEqual(manifest.count("kind: ExternalSecret"), 1)
        self.assertIn("key: secret/agentgateway/prod", manifest)
        self.assertIn("property: chat_agentgateway_client_secret", manifest)
        self.assertIn("name: CLIENT_ID, value: chat-agentgateway", manifest)
        self.assertIn("name: ROLE_NAME, value: agentgateway-write:media", manifest)
        self.assertIn("name: FORBIDDEN_REALM_ROLE, value: agentgateway-write", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("argocd.argoproj.io/hook-delete-policy: BeforeHookCreation", manifest)
        # After the domain roles (19), the umbrella role (20), OpenClaw (21)
        # and the Synapse M2M clients (22).
        self.assertIn('argocd.argoproj.io/sync-wave: "23"', manifest)
        self.assertIn('name: RECONCILE_CONTRACT_VERSION, value: "1"', manifest)
        self.assertIn('synapse.e-dani.com/agentgateway-m2m-client: "true"', manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertNotIn("agentgateway-write\n", manifest)

    def test_domain_roles_hook_allowlists_exactly_this_service_account(self):
        script = (BASE / "scripts" / "agentgateway-domain-roles.sh").read_text()
        job = (BASE / "agentgateway-domain-roles-job.yaml").read_text()
        self.assertIn('EXPECTED_ALLOWED_SERVICE_ACCOUNTS="agentgateway-write:media=service-account-chat-agentgateway"', script)
        self.assertIn("value: agentgateway-write:media=service-account-chat-agentgateway", job)

    def test_kustomization_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "chat-agentgateway-client-rollback-job.yaml").read_text()
        self.assertIn("chat-agentgateway-client.yaml", kustomization)
        self.assertIn("scripts/chat-agentgateway-client.sh", kustomization)
        self.assertNotIn("manual/chat-agentgateway-client-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertNotIn("CHAT_AGENTGATEWAY_CLIENT_SECRET", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(
            ["kubectl", "kustomize", str(BASE)],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("keycloak-chat-agentgateway-client", result.stdout)
        self.assertIn("chat-agentgateway-keycloak-bootstrap", result.stdout)


if __name__ == "__main__":
    unittest.main()
