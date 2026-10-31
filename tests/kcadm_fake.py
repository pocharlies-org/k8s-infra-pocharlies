"""Shared stand-in for kcadm.sh, to run one keycloak-next client reconciler offline.

Used by test_jarvis_echo_identity_contract.py and test_hermes_enviar_identity_contract.py
(both reconcile ONE confidential client on top of keycloak-reconcile-lib.sh). Not a test
module: unittest discovery does not pick it up.

The fake keeps JSON state across calls plus a call journal, and mints tokens with the
semantics measured live (INFRA-44): with fullScopeAllowed=true every realm role of the
service account travels; with the flag off only the roles present in the client's realm
scope mappings do. It knows exactly one client, named by `client_id`, and only the
endpoints the reconcilers call. The client uuid, the service-account id and the secret are
derived from `client_id` (uuid-<client>, sa-<client>, generated-<client>). Role holders
(`roles/<name>/users`, `/groups`) are the service account when it holds the role, plus the
`users` / `groups` the state seeds on the role.

Environment knobs of the fake: FAKE_FORCE_BAD_OFF_TOKEN empties the flag-off token (an
off-matrix token); FAKE_TOKEN_EXTRA_ROLES appends roles to every minted token.
"""
import json
import os
import pathlib
import subprocess
import tempfile
import textwrap

_TEMPLATE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import base64, json, os, sys

    CLIENT_ID = "__CLIENT_ID__"
    UUID = "uuid-" + CLIENT_ID
    SA_ID = "sa-" + CLIENT_ID
    SA_USERNAME = "service-account-" + CLIENT_ID
    CLIENT_URL = "clients/" + UUID

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

    client = state.get("clients", {}).get(CLIENT_ID)
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
        roles += [r for r in os.environ.get("FAKE_TOKEN_EXTRA_ROLES", "").split(",") if r]
        aud = ["account"] + [m["audience"] for m in client.get("mappers", {}).values()]
        claims = {"azp": CLIENT_ID, "aud": aud, "realm_access": {"roles": roles}}
        # Compact JSON, like a real Keycloak JWT payload (no space after commas).
        payload = base64.urlsafe_b64encode(
            json.dumps(claims, separators=(",", ":")).encode()).decode().rstrip("=")
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
            if CLIENT_ID in wanted and client is not None:
                emit([{"id": UUID}], fields)
            sys.exit(0)
        if target == CLIENT_URL:
            emit([client], fields); sys.exit(0)
        if target == CLIENT_URL + "/client-secret":
            emit([{"value": client["secret"]}], fields); sys.exit(0)
        if target == CLIENT_URL + "/protocol-mappers/models":
            emit([{"id": mid, "name": m["name"]} for mid, m in client.get("mappers", {}).items()], fields)
            sys.exit(0)
        if target == CLIENT_URL + "/scope-mappings/realm":
            emit([{"name": r} for r in client.get("scope_roles", [])], fields); sys.exit(0)
        if target == CLIENT_URL + "/service-account-user":
            emit([{"id": SA_ID, "username": SA_USERNAME}], fields); sys.exit(0)
        if target.startswith("roles/") and target.endswith("/users"):
            name = target[len("roles/"):-len("/users")]
            role = state["roles"].get(name)
            if role is None:
                sys.exit(1)
            holders = list(role.get("users", []))
            if client is not None and name in client.get("sa_roles", []):
                holders.append(SA_USERNAME)
            emit([{"username": u} for u in holders], fields); sys.exit(0)
        if target.startswith("roles/") and target.endswith("/groups"):
            name = target[len("roles/"):-len("/groups")]
            role = state["roles"].get(name)
            if role is None:
                sys.exit(1)
            emit([{"path": g} for g in role.get("groups", [])], fields); sys.exit(0)
        if target.startswith("roles/"):
            role = state["roles"].get(target[len("roles/"):])
            if role is None:
                sys.exit(1)
            emit([{"id": role["id"], "composite": str(role["composite"]).lower()}], fields)
            sys.exit(0)
        if target == "users/" + SA_ID + "/role-mappings/realm":
            emit([{"name": r} for r in client.get("sa_roles", [])], fields); sys.exit(0)
        sys.exit(99)

    if verb == "create" and target == "clients":
        state["clients"][CLIENT_ID] = dict(
            settings, sa_roles=[], scope_roles=[], mappers={}, secret="generated-" + CLIENT_ID)
        save(); sys.exit(0)
    if verb == "update" and target == CLIENT_URL:
        state["clients"][CLIENT_ID].update(settings); save(); sys.exit(0)
    if verb in ("create", "update") and target.startswith(CLIENT_URL + "/protocol-mappers/models"):
        c = state["clients"][CLIENT_ID]
        mid = target.rsplit("/", 1)[-1] if verb == "update" else "mapper-" + settings["name"]
        c.setdefault("mappers", {})[mid] = {
            "name": settings["name"], "audience": settings.get('config."included.custom.audience"', "")}
        save(); sys.exit(0)
    if verb == "create" and target == CLIENT_URL + "/scope-mappings/realm":
        state["clients"][CLIENT_ID].setdefault("scope_roles", []).extend(
            entry["name"] for entry in json.loads(after("-b")))
        save(); sys.exit(0)
    if verb == "delete" and target == CLIENT_URL:
        state["clients"].pop(CLIENT_ID, None); save(); sys.exit(0)
    sys.exit(99)
''')


def fake_kcadm_source(client_id):
    """The text of the stand-in kcadm.sh for the one client `client_id`."""
    return _TEMPLATE.replace("__CLIENT_ID__", client_id)


def run_reconciler(script, client_id, mode, state, env_overrides=None):
    """Run `script` (a reconciler) against the fake; return (process, call journal, final state)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        paths = {
            "script": root / "kcadm.sh",
            "log": root / "kcadm.log",
            "state": root / "state.json",
        }
        paths["script"].write_text(fake_kcadm_source(client_id))
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
        proc = subprocess.run(["/bin/sh", str(script)], capture_output=True,
                              text=True, env=environ)
        journal = paths["log"].read_text().splitlines()
        final = json.loads(paths["state"].read_text())
        return proc, journal, final
