# base64 is used only inside the FAKE_KCADM string below, not at this level.
import json, os, pathlib, shutil, subprocess, tempfile, textwrap, unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "jarvis-echo-client.sh"

# Stateful stand-in for kcadm.sh: JSON state across calls, a call journal, and
# minted-token semantics measured live (INFRA-44): with fullScopeAllowed=true
# every realm role of the service account travels; with the flag off only the
# roles present in the client's realm scope mappings do.
# FAKE_FORCE_BAD_OFF_TOKEN models an off-matrix post-flip token to exercise
# the auto-restore path. The fake knows exactly one client (jarvis-echo) and
# only the endpoints the reconciler calls.
FAKE_KCADM = textwrap.dedent('''\
    #!/usr/bin/env python3
    import base64, json, os, sys

    argv = sys.argv[1:]
    with open(os.environ["FAKE_KCADM_LOG"], "a") as log:
        log.write(" ".join(argv) + "\\n")
    state_path = os.environ["FAKE_KC_STATE"]
    with open(state_path) as fh:
        state = json.load(fh)

    def save():
        with open(state_path, "w") as fh:
            json.dump(state, fh)

    def after(name):
        # value of a single-valued option (--fields, --client, --uid, ...)
        return argv[argv.index(name) + 1] if name in argv else None

    def repeated(name):
        # values of a repeatable option (-s key=value, -q filter)
        return [argv[i + 1] for i, a in enumerate(argv) if a == name and i + 1 < len(argv)]

    def emit(rows, fields):
        for row in rows:
            print(",".join(str(row.get(f, "")) for f in fields))

    client = state.get("clients", {}).get("jarvis-echo")
    verb = argv[0]

    if verb == "config" and after("--realm") == "master":
        sys.exit(0)

    if verb == "config":
        if client is None or client["secret"] != after("--secret"):
            sys.exit(1)
        roles = list(client.get("sa_roles", []))
        if client.get("fullScopeAllowed") == "false":
            roles = [] if os.environ.get("FAKE_FORCE_BAD_OFF_TOKEN") else [
                r for r in roles if r in client.get("scope_roles", [])]
        aud = ["account"] + [m["audience"] for m in client.get("mappers", {}).values()]
        claims = {"azp": "jarvis-echo", "aud": aud, "realm_access": {"roles": roles}}
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        with open(after("--config"), "w") as fh:
            json.dump({"token": "hdr." + payload + ".sig"}, fh)
        sys.exit(0)

    if verb == "add-roles":
        client.setdefault("sa_roles", []).append(after("--rolename"))
        save(); sys.exit(0)

    target = argv[1] if len(argv) > 1 else ""
    fields = (after("--fields") or "").split(",")
    settings = dict(a.split("=", 1) for a in repeated("-s") if "=" in a)

    if verb == "get":
        if target == "clients":
            wanted = [q.split("=", 1)[1] for q in repeated("-q") if q.startswith("clientId=")]
            if "jarvis-echo" in wanted and client is not None:
                emit([{"id": "uuid-jarvis-echo"}], fields)
            sys.exit(0)
        if target == "clients/uuid-jarvis-echo":
            emit([client], fields); sys.exit(0)
        if target == "clients/uuid-jarvis-echo/client-secret":
            emit([{"value": client["secret"]}], fields); sys.exit(0)
        if target == "clients/uuid-jarvis-echo/protocol-mappers/models":
            emit([{"id": mid, "name": m["name"]} for mid, m in client.get("mappers", {}).items()], fields)
            sys.exit(0)
        if target == "clients/uuid-jarvis-echo/scope-mappings/realm":
            emit([{"name": r} for r in client.get("scope_roles", [])], fields); sys.exit(0)
        if target == "clients/uuid-jarvis-echo/service-account-user":
            emit([{"id": "sa-jarvis", "username": "service-account-jarvis-echo"}], fields); sys.exit(0)
        if target.startswith("roles/"):
            role = state["roles"].get(target[len("roles/"):])
            if role is None:
                sys.exit(1)
            emit([{"id": role["id"], "composite": str(role["composite"]).lower()}], fields)
            sys.exit(0)
        if target == "users/sa-jarvis/role-mappings/realm":
            emit([{"name": r} for r in client.get("sa_roles", [])], fields); sys.exit(0)
        sys.exit(99)

    if verb == "create" and target == "clients":
        state["clients"]["jarvis-echo"] = dict(
            settings, sa_roles=[], scope_roles=[], mappers={}, secret="generated-jarvis-echo")
        save(); sys.exit(0)
    if verb == "update" and target == "clients/uuid-jarvis-echo":
        state["clients"]["jarvis-echo"].update(settings); save(); sys.exit(0)
    if verb in ("create", "update") and target.startswith("clients/uuid-jarvis-echo/protocol-mappers/models"):
        c = state["clients"]["jarvis-echo"]
        mid = target.rsplit("/", 1)[-1] if verb == "update" else "mapper-" + settings["name"]
        c.setdefault("mappers", {})[mid] = {
            "name": settings["name"], "audience": settings.get('config."included.custom.audience"', "")}
        save(); sys.exit(0)
    if verb == "create" and target == "clients/uuid-jarvis-echo/scope-mappings/realm":
        state["clients"]["jarvis-echo"].setdefault("scope_roles", []).extend(
            entry["name"] for entry in json.loads(after("-b")))
        save(); sys.exit(0)
    if verb == "delete" and target == "clients/uuid-jarvis-echo":
        state["clients"].pop("jarvis-echo", None); save(); sys.exit(0)
    sys.exit(99)
''')

REVIEWED_ROLE = "agentgateway-read:workspace"


def _run(mode, state, env_overrides=None):
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        paths = {
            "script": root / "kcadm.sh",
            "log": root / "kcadm.log",
            "state": root / "state.json",
        }
        paths["script"].write_text(FAKE_KCADM)
        paths["script"].chmod(0o755)
        paths["log"].write_text("")
        paths["state"].write_text(json.dumps(state))
        environ = dict(os.environ)
        environ["KCADM"] = str(paths["script"])
        environ["FAKE_KCADM_LOG"] = str(paths["log"])
        environ["FAKE_KC_STATE"] = str(paths["state"])
        environ["KC_BOOTSTRAP_ADMIN_USERNAME"] = "test-admin"
        environ["KC_BOOTSTRAP_ADMIN_PASSWORD"] = "test-password"
        environ["MODE"] = mode
        if env_overrides:
            environ.update(env_overrides)
        proc = subprocess.run(["/bin/sh", str(SCRIPT)], capture_output=True,
                              text=True, env=environ)
        journal = paths["log"].read_text().splitlines()
        final = json.loads(paths["state"].read_text())
        return proc, journal, final


def _state(role_present=True, client=None):
    state = {"clients": {}, "roles": {}}
    if role_present:
        state["roles"][REVIEWED_ROLE] = {"id": "role-workspace", "composite": False}
    if client is not None:
        state["clients"]["jarvis-echo"] = client
    return state


def _existing_client(**extra):
    # The state measured live on 2026-10-04, the day INFRA-477 opened: the
    # hand-created client with fullScopeAllowed STILL TRUE, the reviewed grant
    # in place and an EMPTY client role scope (the role travelled through the
    # flag alone).
    client = {
        "clientId": "jarvis-echo", "enabled": "true", "publicClient": "false",
        "standardFlowEnabled": "false", "directAccessGrantsEnabled": "false",
        "serviceAccountsEnabled": "true", "fullScopeAllowed": "true",
        "secret": "generated-jarvis-echo",
        "sa_roles": [REVIEWED_ROLE, "default-roles-edani"],
        "scope_roles": [],
        "mappers": {"m1": {"name": "aud-mcp", "audience": "mcp.lan.e-dani.com"}},
    }
    client.update(extra)
    return client


def _converged_client(**extra):
    client = _existing_client()
    client.update(fullScopeAllowed="false", scope_roles=[REVIEWED_ROLE])
    client.update(extra)
    return client


class JarvisEchoIdentityContractTest(unittest.TestCase):
    def test_reconciler_is_fixed_scope_and_never_touches_the_secret(self):
        script = SCRIPT.read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-jarvis-echo}"', script)
        self.assertIn('READ_ROLE_NAME="${READ_ROLE_NAME:-agentgateway-read:workspace}"', script)
        self.assertIn('EXPECTED_READ_ROLE_NAME="agentgateway-read:workspace"', script)
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', script)
        self.assertIn('MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"', script)
        self.assertIn("unsupported immutable client", script)
        self.assertIn("READ_ROLE_NAME is immutable", script)
        self.assertIn("serviceAccountsEnabled=true", script)
        self.assertIn("standardFlowEnabled=false", script)
        self.assertIn("directAccessGrantsEnabled=false", script)
        self.assertIn("oidc-audience-mapper", script)
        # The role is owned by the read-grants hook: never created or deleted
        # here, and the reconciler refuses to run without it.
        self.assertIn("the agentgateway-read-grants hook owns it", script)
        self.assertNotIn("create roles", script)
        self.assertNotIn('delete "roles/', script)
        self.assertNotIn("delete roles", script)
        # The secret is never written: neither branch of the upsert carries a
        # secret field, and the mint only reads it through the admin API.
        self.assertNotIn("-s secret=", script)
        self.assertIn('"clients/${CLIENT_UUID}/client-secret"', script)
        self.assertIn("check_exact_token", script)
        self.assertIn("restored to true and confirmed", script)
        self.assertIn("manual intervention required", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${client_secret}"', script)
        self.assertNotIn('echo "${token}"', script)

    def test_guards_are_immutable_before_any_call(self):
        result, calls, _ = _run("ensure", _state(), {"CLIENT_ID": "jarvis-echo-2"})
        self.assertEqual(1, result.returncode)
        self.assertIn("unsupported immutable client", result.stderr)
        self.assertEqual([], calls)
        result, calls, _ = _run(
            "ensure", _state(), {"READ_ROLE_NAME": "agentgateway-read:gsc"}
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("READ_ROLE_NAME is immutable", result.stderr)
        self.assertEqual([], calls)

    def test_ensure_adopts_the_live_hand_created_client(self):
        # The INFRA-477 adoption path: the client exists with the flag true
        # and an empty scope. Ensure maps the role into the client role scope,
        # flips fullScopeAllowed=false only afterwards, and verifies the
        # exact token. The upsert update itself must not carry the flag.
        result, calls, state = _run("ensure", _state(client=_existing_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_id":"jarvis-echo","realm_role":"agentgateway-read:workspace","present":true', result.stdout)
        self.assertIn('"fullscope_allowed":false,"token_verified":true', result.stdout)
        updates = [c for c in calls if c.startswith("update clients/uuid-jarvis-echo ")]
        self.assertTrue(updates)
        self.assertFalse(any("fullScopeAllowed=false" in c for c in updates[:1]), updates)
        self.assertTrue(any("fullScopeAllowed=false" in c for c in updates), updates)
        self.assertFalse(any(c.startswith("create clients ") for c in calls))
        self.assertFalse(any(c.startswith("add-roles ") for c in calls))
        self.assertTrue(any(c.startswith("create clients/uuid-jarvis-echo/scope-mappings/realm") for c in calls))
        self.assertFalse(any(c.startswith("create roles") for c in calls))
        client = state["clients"]["jarvis-echo"]
        self.assertEqual("false", client["fullScopeAllowed"])
        self.assertEqual([REVIEWED_ROLE], client["scope_roles"])
        self.assertEqual([REVIEWED_ROLE, "default-roles-edani"], client["sa_roles"])

    def test_ensure_creates_the_client_on_a_fresh_realm(self):
        result, calls, state = _run("ensure", _state())
        self.assertEqual(0, result.returncode, result.stderr)
        creates = [c for c in calls if c.startswith("create clients ") and "clientId=jarvis-echo" in c]
        self.assertEqual(1, len(creates))
        self.assertIn("fullScopeAllowed=false", creates[0])
        self.assertTrue(any(c.startswith("add-roles ") and f"--rolename {REVIEWED_ROLE}" in c for c in calls))
        client = state["clients"]["jarvis-echo"]
        self.assertEqual([REVIEWED_ROLE], client["sa_roles"])
        self.assertEqual([REVIEWED_ROLE], client["scope_roles"])

    def test_ensure_is_idempotent_on_a_converged_client(self):
        result, calls, state = _run("ensure", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(any(c.startswith("create clients ") for c in calls))
        self.assertFalse(any(c.startswith("add-roles") for c in calls))
        self.assertFalse(any(c.startswith("create clients/uuid-jarvis-echo/scope-mappings") for c in calls))
        # Steady state: the owned flag is already false, so no update may
        # touch it (INFRA-45 discipline: an idempotent run flips nothing).
        self.assertFalse(any("fullScopeAllowed" in c for c in calls if c.startswith("update ")))
        self.assertEqual("false", state["clients"]["jarvis-echo"]["fullScopeAllowed"])

    def test_ensure_refuses_to_run_before_the_read_role_exists(self):
        result, calls, state = _run("ensure", _state(role_present=False))
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-read:workspace is missing; the agentgateway-read-grants hook owns it", result.stderr)
        self.assertFalse(any(c.startswith("create") for c in calls))
        self.assertEqual({}, state["clients"])

    def test_ensure_fails_when_the_service_account_holds_a_write_role(self):
        # INFRA-477: security approved read-only calendar access. The
        # umbrella role and any write domain fail closed.
        for extra in ("agentgateway-write", "agentgateway-write:workspace"):
            client = _converged_client(sa_roles=[REVIEWED_ROLE, "default-roles-edani", extra])
            result, _, _ = _run("ensure", _state(client=client))
            self.assertEqual(1, result.returncode, extra)
            self.assertIn(f"unreviewed AgentGateway role: {extra}", result.stderr)

    def test_ensure_fails_when_the_service_account_holds_a_sibling_read_role(self):
        client = _converged_client(sa_roles=[REVIEWED_ROLE, "agentgateway-read:gsc", "default-roles-edani"])
        result, _, _ = _run("ensure", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("unreviewed AgentGateway role: agentgateway-read:gsc", result.stderr)

    def test_post_flip_off_matrix_token_restores_fullscope_and_aborts(self):
        # The flip is the live step: if the token with the flag off is
        # off-matrix, the flag goes back to true (read-back + confirmation
        # mint) before the abort, so the Alexa skill never loses its token.
        result, calls, state = _run(
            "ensure", _state(client=_existing_client()),
            {"FAKE_FORCE_BAD_OFF_TOKEN": "1"},
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("restored to true and confirmed", result.stderr)
        self.assertEqual("true", state["clients"]["jarvis-echo"]["fullScopeAllowed"])
        self.assertTrue(any(c.startswith("update clients/uuid-jarvis-echo ") and "fullScopeAllowed=true" in c for c in calls))

    def test_steady_state_off_matrix_token_fails_without_mutation(self):
        # Flag already false and the minted token is off-matrix: that is
        # drift or an attack, not a flip candidate — the flag is owned
        # steady state and must not be touched (INFRA-45 discipline).
        result, calls, _ = _run(
            "ensure", _state(client=_converged_client()),
            {"FAKE_FORCE_BAD_OFF_TOKEN": "1"},
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("flag unchanged by this run", result.stderr)
        self.assertFalse(any("fullScopeAllowed" in c for c in calls if c.startswith("update ")))

    def test_extra_scope_mapping_fails_closed_before_the_live_flip(self):
        # A second role mapped into the client scope widens the reviewed
        # matrix the moment the service account is granted it: fail closed,
        # additive reconciliation never removes and never flips.
        client = _converged_client(scope_roles=[REVIEWED_ROLE, "agentgateway-write"])
        result, calls, _ = _run("ensure", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("scope has unexpected role agentgateway-write; it widens the reviewed matrix", result.stderr)
        self.assertFalse(any("fullScopeAllowed" in c for c in calls if c.startswith("update ")))
        self.assertFalse(any(c.startswith("add-roles") for c in calls))

    def test_missing_scope_mapping_is_repaired_not_fatal(self):
        # The empty scope of the hand-created client (measured 2026-10-04)
        # is drift this hook repairs by ADDING the reviewed role, then
        # converges the flag.
        client = _converged_client(scope_roles=[])
        result, calls, state = _run("ensure", _state(client=client))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(any(c.startswith("create clients/uuid-jarvis-echo/scope-mappings/realm") for c in calls))
        self.assertEqual([REVIEWED_ROLE], state["clients"]["jarvis-echo"]["scope_roles"])

    def test_audit_passes_on_the_converged_client(self):
        result, calls, _ = _run("audit", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"token_verified":true', result.stdout)
        self.assertFalse(any(c.startswith("create") or c.startswith("update") or c.startswith("add-roles") for c in calls))

    def test_audit_fails_when_the_service_account_is_missing_the_role(self):
        client = _converged_client(sa_roles=["default-roles-edani"])
        result, _, _ = _run("audit", _state(client=client))
        self.assertEqual(1, result.returncode)
        self.assertIn("direct realm role missing: agentgateway-read:workspace", result.stderr)

    def test_rollback_deletes_the_client_and_retains_the_role(self):
        result, calls, state = _run("rollback", _state(client=_converged_client()))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_present":false,"role_retained":true', result.stdout)
        self.assertTrue(any(c.startswith("delete clients/uuid-jarvis-echo ") for c in calls))
        self.assertFalse(any(c.startswith("delete roles") for c in calls))
        self.assertIn(REVIEWED_ROLE, state["roles"])
        self.assertEqual({}, state["clients"])

    def test_manifest_is_a_hardened_postsync_without_external_secret(self):
        manifest = (BASE / "jarvis-echo-client.yaml").read_text()
        # Unlike chat-agentgateway-client.yaml: no ExternalSecret, no
        # 1Password reference — the secret is not managed here and the hook
        # must never block on an unseeded secretKeyRef (INFRA-477).
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("onepassword", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("argocd.argoproj.io/hook-delete-policy: BeforeHookCreation", manifest)
        self.assertIn('argocd.argoproj.io/sync-wave: "24"', manifest)
        self.assertIn("name: CLIENT_ID, value: jarvis-echo", manifest)
        self.assertIn("name: READ_ROLE_NAME, value: agentgateway-read:workspace", manifest)
        self.assertIn('name: MAPPER_NAME, value: aud-mcp', manifest)
        self.assertIn('synapse.e-dani.com/agentgateway-m2m-client: "true"', manifest)
        self.assertIn("activeDeadlineSeconds: 1800", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertNotIn("CLIENT_SECRET", manifest)

    def test_kustomization_owns_job_and_script_and_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "jarvis-echo-client-rollback-job.yaml").read_text()
        self.assertIn("jarvis-echo-client.yaml", kustomization)
        self.assertIn("scripts/jarvis-echo-client.sh", kustomization)
        self.assertNotIn("manual/jarvis-echo-client-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(
            ["kubectl", "kustomize", str(BASE)],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("keycloak-jarvis-echo-client", result.stdout)


if __name__ == "__main__":
    unittest.main()
