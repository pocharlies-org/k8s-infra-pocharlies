"""INFRA-251 (INFRA-219 C4): PRINCIPALS.md contract and verify-principals.py.

The verifier runs against a stdlib fake Keycloak bound to 127.0.0.1 (no
network, no kcadm, no image): a token endpoint plus the paginated users
endpoint. Like the real one, the default users listing hides service
accounts; they only come back through the username=service-account search.
"""

import base64
import contextlib
import copy
import importlib.util
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPTS = BASE / "scripts"
PRINCIPALS = BASE / "PRINCIPALS.md"
CATALOG = BASE / "ROLES.yaml"
VERIFY = SCRIPTS / "verify-principals.py"

sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402

_spec = importlib.util.spec_from_file_location("verify_principals", VERIFY)
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)

CLIENT_ID = "keycloak-role-auditor"
CLIENT_SECRET = "fake-secret-not-real"
SA_PREFIX = "service-account-"


class FakeKeycloak:
    """Minimal Keycloak: client_credentials token + read-only users listing."""

    def __init__(self, usernames):
        self.usernames = sorted(usernames)
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                form = self.rfile.read(length).decode()
                fake.requests.append(("POST", self.path))
                if self.path != "/realms/edani/protocol/openid-connect/token":
                    return self._send(404, {"error": "not found"})
                expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                if self.headers.get("Authorization") != f"Basic {expected}" or form != "grant_type=client_credentials":
                    return self._send(401, {"error": "invalid_client"})
                return self._send(200, {"access_token": "fake-token", "token_type": "Bearer"})

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                fake.requests.append(("GET", url.path))
                if self.headers.get("Authorization") != "Bearer fake-token":
                    return self._send(401, {"error": "HTTP 401 Unauthorized"})
                if url.path != "/admin/realms/edani/users":
                    return self._send(404, {"error": "not found"})
                query = urllib.parse.parse_qs(url.query)
                first = int(query.get("first", ["0"])[0])
                size = int(query.get("max", ["100"])[0])
                search = query.get("username", [None])[0]
                if search is None:
                    names = [n for n in fake.usernames if not n.startswith(SA_PREFIX)]
                elif query.get("exact", ["false"])[0] == "false":
                    names = [n for n in fake.usernames if search in n]
                else:
                    names = [n for n in fake.usernames if n == search]
                items = [{"id": f"id-{n}", "username": n} for n in names]
                return self._send(200, items[first:first + size])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def principals_document():
    return kc_rbac.load_json_block(PRINCIPALS)


def live_usernames():
    return [entry["username"] for entry in principals_document()["principals"]]


class PrincipalsShapeTest(unittest.TestCase):
    def test_every_entry_honours_the_contract(self):
        document = principals_document()
        self.assertEqual(document["realm"], "edani")
        entries = verify.load_principals(PRINCIPALS)
        self.assertGreaterEqual(len(entries), 19)
        catalog = kc_rbac.load_role_catalog(CATALOG)
        self.assertEqual(verify.find_drift(entries, catalog, set(entries)), [])
        for username, entry in entries.items():
            self.assertTrue(entry["owner"].strip(), username)
            self.assertTrue(entry["source"].strip(), username)
            self.assertTrue(entry["purpose"].strip(), username)
            if "origen-desconocido" in entry.get("flags", []):
                self.assertEqual(entry["owner"], "Dani (operador)", username)

    def test_every_principal_holds_default_roles(self):
        # ROLES.yaml says Keycloak grants default-roles-edani on creation: the
        # grantees of that role and this inventory are the same set.
        catalog = kc_rbac.load_role_catalog(CATALOG)
        self.assertEqual(sorted(catalog["default-roles-edani"]["grantees"]), sorted(live_usernames()))

    def test_the_two_pending_principals_of_sc320_are_owned(self):
        entries = verify.load_principals(PRINCIPALS)
        for username in ("me@e-dani.com", "service-account-synapse-sre-orchestrator"):
            self.assertEqual(entries[username]["status"], "activo")
            self.assertIn("cto-office-send", entries[username]["realm_roles"])
            self.assertIn("SC-320", entries[username]["source"])

    def test_the_verifier_reads_users_only(self):
        # The drift CronJob's auditor has no view-clients (INFRA-219 architecture).
        source = VERIFY.read_text(encoding="utf-8")
        self.assertNotIn('"clients', source)
        self.assertNotIn("role-mappings", source)

    def test_shape_errors_raise(self):
        document = principals_document()
        cases = [
            (lambda d: d["principals"].append(copy.deepcopy(d["principals"][0])), "duplicado"),
            (lambda d: d["principals"][0].update(status="retirado"), "activo o retirada-propuesta"),
            (lambda d: d["principals"][0].update(type="robot"), "sa o humano"),
            (lambda d: next(p for p in d["principals"] if p["type"] == "sa").update(client="otro"), "service-account-<client>"),
            (lambda d: next(p for p in d["principals"] if p["type"] == "humano").update(client="x"), "client debe ser null"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "PRINCIPALS.md"
            for mutate, message in cases:
                bad = copy.deepcopy(document)
                mutate(bad)
                path.write_text("```json\n" + json.dumps(bad) + "\n```\n", encoding="utf-8")
                with self.assertRaisesRegex(kc_rbac.CatalogError, re.escape(message)):
                    verify.load_principals(path)


class VerifyPrincipalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self.tmp.name)
        (tmp / "client_id").write_text(CLIENT_ID + "\n")
        (tmp / "client_secret").write_text(CLIENT_SECRET + "\n")
        self.env = {
            "KC_CLIENT_ID_FILE": str(tmp / "client_id"),
            "KC_CLIENT_SECRET_FILE": str(tmp / "client_secret"),
            "KC_REALM": "edani",
        }
        self.copy_path = tmp / "PRINCIPALS.md"

    def tearDown(self):
        self.tmp.cleanup()

    def edited_copy(self, mutate):
        """A local copy of PRINCIPALS.md with its json block edited (prose kept)."""
        text = PRINCIPALS.read_text(encoding="utf-8")
        document = principals_document()
        mutate(document)
        start = text.index("```json\n") + len("```json\n")
        end = text.index("\n```", start)
        self.copy_path.write_text(text[:start] + json.dumps(document, ensure_ascii=False, indent=2) + text[end:], encoding="utf-8")
        return self.copy_path

    def run_verify(self, usernames, principals_path=PRINCIPALS):
        with FakeKeycloak(usernames) as fake:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = verify.main(["--principals", str(principals_path), "--catalog", str(CATALOG)],
                                   env={**self.env, "KEYCLOAK_URL": fake.url})
            self.assertTrue(all(method == "GET" for method, path in fake.requests if "/admin/" in path),
                            "the verifier must never mutate the realm")
            self.assertTrue(all(path == "/admin/realms/edani/users" for _, path in fake.requests if "/admin/" in path),
                            "the verifier reads users only")
        return code, out.getvalue().splitlines()

    def test_exact_realm_is_ok(self):
        usernames = live_usernames()
        code, lines = self.run_verify(usernames)
        self.assertEqual(code, 0)
        self.assertEqual(lines, [f"OK: {len(usernames)} principals, 0 sin dueño"])

    def test_service_accounts_come_from_their_own_query_with_pagination(self):
        original = kc_rbac.DEFAULT_PAGE_SIZE
        kc_rbac.DEFAULT_PAGE_SIZE = 2
        try:
            code, lines = self.run_verify(live_usernames())
        finally:
            kc_rbac.DEFAULT_PAGE_SIZE = original
        self.assertEqual(code, 0, lines)

    def test_live_principal_without_entry_is_named(self):
        path = self.edited_copy(lambda d: d.update(
            principals=[p for p in d["principals"] if p["username"] != "service-account-cloudblue"]))
        code, lines = self.run_verify(live_usernames(), path)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: principal service-account-cloudblue existe en el realm y no tiene entrada en PRINCIPALS.md"])

    def test_new_live_user_without_entry_is_named(self):
        code, lines = self.run_verify(live_usernames() + ["nuevo@e-dani.com"])
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: principal nuevo@e-dani.com existe en el realm y no tiene entrada en PRINCIPALS.md"])

    def test_entry_without_owner_is_named(self):
        def mutate(document):
            for entry in document["principals"]:
                if entry["username"] == "uriel":
                    entry["owner"] = "  "
                if entry["username"] == "qa-con-rol@e-dani.com":
                    del entry["owner"]
        code, lines = self.run_verify(live_usernames(), self.edited_copy(mutate))
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: entrada qa-con-rol@e-dani.com sin dueño", "DRIFT: entrada uriel sin dueño"])

    def test_entry_without_live_principal_is_named(self):
        usernames = [u for u in live_usernames() if u != "qa-sin-rol@e-dani.com"]
        code, lines = self.run_verify(usernames)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: entrada qa-sin-rol@e-dani.com de PRINCIPALS.md no existe en el realm"])

    def test_retirement_needs_a_reason(self):
        def mutate(document):
            for entry in document["principals"]:
                if entry["username"] == "qa-sin-rol@e-dani.com":
                    del entry["retirement_reason"]
        code, lines = self.run_verify(live_usernames(), self.edited_copy(mutate))
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: entrada qa-sin-rol@e-dani.com en retirada-propuesta sin motivo"])

    def test_realm_roles_mirror_the_catalog(self):
        def mutate(document):
            for entry in document["principals"]:
                if entry["username"] == "service-account-synapse-sre-orchestrator":
                    entry["realm_roles"] = ["default-roles-edani", "synapse-sre-m2m", "rol-inventado"]
                if entry["username"] == "uriel":
                    entry["realm_roles"].append("agentgateway-write")
        code, lines = self.run_verify(live_usernames(), self.edited_copy(mutate))
        self.assertEqual(code, 1)
        self.assertEqual(lines, [
            "DRIFT: entrada service-account-synapse-sre-orchestrator declara rol-inventado, que no está en ROLES.yaml",
            "DRIFT: entrada service-account-synapse-sre-orchestrator no declara cto-office-send, que ROLES.yaml le concede",
            "DRIFT: entrada uriel declara agentgateway-write y ROLES.yaml no se lo concede",
        ])

    def test_auth_error_exits_2(self):
        env = {**self.env}
        pathlib.Path(env["KC_CLIENT_SECRET_FILE"]).write_text("wrong\n")
        with FakeKeycloak(live_usernames()) as fake:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = verify.main([], env={**env, "KEYCLOAK_URL": fake.url})
        self.assertEqual(code, 2)
        self.assertTrue(out.getvalue().startswith("ERROR: HTTP 401"), out.getvalue())
        self.assertNotIn("wrong", out.getvalue())

    def test_cli_entrypoint_exit_code(self):
        with FakeKeycloak(live_usernames()) as fake:
            completed = subprocess.run(
                [sys.executable, str(VERIFY)],
                env={**os.environ, **self.env, "KEYCLOAK_URL": fake.url},
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(completed.stdout.strip(), f"OK: {len(live_usernames())} principals, 0 sin dueño")


if __name__ == "__main__":
    unittest.main()
