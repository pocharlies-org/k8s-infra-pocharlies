"""INFRA-247 (INFRA-219 C1): ROLES.yaml contract and verify-role-catalog.py.

The verifier runs against a stdlib fake Keycloak bound to 127.0.0.1 (no
network, no kcadm, no image): a token endpoint plus the paginated admin
endpoints the verifier reads.
"""

import contextlib
import copy
import importlib.util
import io
import json
import os
import pathlib
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
CATALOG = BASE / "ROLES.yaml"
VERIFY = SCRIPTS / "verify-role-catalog.py"

sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402

_spec = importlib.util.spec_from_file_location("verify_role_catalog", VERIFY)
verify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verify)

CLIENT_ID = "keycloak-role-auditor"
CLIENT_SECRET = "fake-secret-not-real"


class FakeKeycloak:
    """Minimal Keycloak: client_credentials token + read-only realm admin API."""

    def __init__(self, roles):
        # roles: {name: {"users": [...], "groups": [...], "composites": [...]}}
        self.roles = roles
        self.token_status = 200
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
                if fake.token_status != 200:
                    return self._send(fake.token_status, {"error": "unauthorized_client"})
                import base64
                expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                if self.headers.get("Authorization") != f"Basic {expected}" or form != "grant_type=client_credentials":
                    return self._send(401, {"error": "invalid_client"})
                return self._send(200, {"access_token": "fake-token", "token_type": "Bearer"})

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                fake.requests.append(("GET", url.path))
                if self.headers.get("Authorization") != "Bearer fake-token":
                    return self._send(401, {"error": "HTTP 401 Unauthorized"})
                query = urllib.parse.parse_qs(url.query)
                first = int(query.get("first", ["0"])[0])
                size = int(query.get("max", ["100"])[0])
                parts = [urllib.parse.unquote(p) for p in url.path.split("/")]
                # ['', 'admin', 'realms', 'edani', 'roles', <name>?, <kind>?]
                if parts[:4] != ["", "admin", "realms", "edani"] or len(parts) < 5 or parts[4] != "roles":
                    return self._send(404, {"error": "not found"})
                if len(parts) == 5:
                    items = [{"name": name} for name in sorted(fake.roles)]
                elif len(parts) == 7 and parts[5] in fake.roles and parts[6] == "composites":
                    # Not paged, like Keycloak; client-role composites ride along.
                    items = [{"name": value, "clientRole": False} for value in fake.roles[parts[5]].get("composites", [])]
                    items += [{"name": value, "clientRole": True} for value in fake.roles[parts[5]].get("client_composites", [])]
                    return self._send(200, items)
                elif len(parts) == 7 and parts[5] in fake.roles and parts[6] in ("users", "groups"):
                    values = fake.roles[parts[5]][parts[6]]
                    key = "username" if parts[6] == "users" else "path"
                    items = [{key: value} for value in values]
                else:
                    return self._send(404, {"error": "Could not find role"})
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


def realm_from_catalog(catalog):
    return {
        name: {"users": list(entry["grantees"]), "groups": [], "composites": list(entry.get("composites", []))}
        for name, entry in catalog.items()
    }


class RoleCatalogShapeTest(unittest.TestCase):
    def test_catalog_is_json_and_every_entry_honours_the_contract(self):
        document = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(document["realm"], "edani")
        catalog = kc_rbac.load_role_catalog(CATALOG)
        self.assertGreaterEqual(len(catalog), 43)
        for name, entry in catalog.items():
            self.assertIn(entry["status"], ("active", "deprecated"), name)
            self.assertEqual(entry["grantees"], sorted(entry["grantees"]), f"{name}: grantees sorted")

    def test_measured_grants_of_the_privileged_principals(self):
        catalog = kc_rbac.load_role_catalog(CATALOG)
        mcp = "service-account-agentgateway-mcp"
        held = {name for name, entry in catalog.items() if mcp in entry["grantees"]}
        reads = {name for name in held if name.startswith("agentgateway-read:")}
        self.assertEqual(len(reads), 21)
        self.assertEqual(held - reads, {"agentgateway-write", "default-roles-edani"})
        self.assertEqual(catalog["agentgateway-write"]["grantees"], [mcp])
        # cto-office-send is untouchable (SC-320): catalogued as measured, active.
        self.assertEqual(catalog["cto-office-send"]["status"], "active")
        for builtin in ("default-roles-edani", "offline_access", "uma_authorization"):
            self.assertTrue(catalog[builtin]["origin"].startswith("keycloak-builtin"), builtin)

    def test_catalog_rejects_duplicate_or_unknown_status(self):
        document = json.loads(CATALOG.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "ROLES.yaml"
            dup = copy.deepcopy(document)
            dup["roles"].append(copy.deepcopy(dup["roles"][0]))
            path.write_text(json.dumps(dup))
            with self.assertRaisesRegex(kc_rbac.CatalogError, "duplicado"):
                kc_rbac.load_role_catalog(path)
            bad = copy.deepcopy(document)
            bad["roles"][0]["status"] = "retired"
            path.write_text(json.dumps(bad))
            with self.assertRaisesRegex(kc_rbac.CatalogError, "active o deprecated"):
                kc_rbac.load_role_catalog(path)
            ghost = copy.deepcopy(document)
            ghost["roles"][0]["composites"] = ["no-existe"]
            path.write_text(json.dumps(ghost))
            with self.assertRaisesRegex(kc_rbac.CatalogError, "no catalogados: no-existe"):
                kc_rbac.load_role_catalog(path)
            unsorted = copy.deepcopy(document)
            unsorted["roles"][0]["composites"] = ["uma_authorization", "offline_access"]
            path.write_text(json.dumps(unsorted))
            with self.assertRaisesRegex(kc_rbac.CatalogError, "ordenado y sin repetidos"):
                kc_rbac.load_role_catalog(path)

    def test_measured_composites(self):
        catalog = kc_rbac.load_role_catalog(CATALOG)
        composite = {name: entry["composites"] for name, entry in catalog.items() if "composites" in entry}
        self.assertEqual(composite, {"default-roles-edani": ["offline_access", "uma_authorization"]})

    def test_load_json_block_requires_exactly_one_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            md = pathlib.Path(tmp) / "PRINCIPALS.md"
            md.write_text('# Principals\n\ntexto\n\n```json\n{"principals": [1, 2]}\n```\n')
            self.assertEqual(kc_rbac.load_json_block(md), {"principals": [1, 2]})
            md.write_text("```json\n{}\n```\n\n```json\n{}\n```\n")
            with self.assertRaisesRegex(kc_rbac.CatalogError, "exactamente un bloque"):
                kc_rbac.load_json_block(md)
            md.write_text("sin bloque\n")
            with self.assertRaisesRegex(kc_rbac.CatalogError, "exactamente un bloque"):
                kc_rbac.load_json_block(md)


class VerifyRoleCatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = kc_rbac.load_role_catalog(CATALOG)
        self.tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self.tmp.name)
        (tmp / "client_id").write_text(CLIENT_ID + "\n")
        (tmp / "client_secret").write_text(CLIENT_SECRET + "\n")
        self.env = {
            "KC_CLIENT_ID_FILE": str(tmp / "client_id"),
            "KC_CLIENT_SECRET_FILE": str(tmp / "client_secret"),
            "KC_REALM": "edani",
        }
        self.catalog_path = tmp / "ROLES.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def run_verify(self, realm, catalog_document=None, token_status=200):
        if catalog_document is None:
            catalog_path = CATALOG
        else:
            self.catalog_path.write_text(json.dumps(catalog_document))
            catalog_path = self.catalog_path
        with FakeKeycloak(realm) as fake:
            fake.token_status = token_status
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = verify.main(["--catalog", str(catalog_path)], env={**self.env, "KEYCLOAK_URL": fake.url})
            self.assertTrue(all(method == "GET" for method, path in fake.requests if "/admin/" in path),
                            "the verifier must never mutate the realm")
        return code, out.getvalue().splitlines()

    def test_exact_realm_is_ok(self):
        code, lines = self.run_verify(realm_from_catalog(self.catalog))
        self.assertEqual(code, 0)
        self.assertEqual(lines, [f"OK: {len(self.catalog)} roles en catálogo, 0 sin catalogar, 0 catalogados inexistentes"])

    def test_pagination_is_followed(self):
        realm = realm_from_catalog(self.catalog)
        original = kc_rbac.DEFAULT_PAGE_SIZE
        kc_rbac.DEFAULT_PAGE_SIZE = 2
        try:
            code, lines = self.run_verify(realm)
        finally:
            kc_rbac.DEFAULT_PAGE_SIZE = original
        self.assertEqual(code, 0, lines)

    def test_uncatalogued_realm_role_is_drift(self):
        realm = realm_from_catalog(self.catalog)
        realm["agentgateway-read:nueva"] = {"users": [], "groups": []}
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: rol agentgateway-read:nueva existe en el realm y no está en el catálogo"])

    def test_entry_deleted_from_a_catalog_copy_names_the_role(self):
        document = json.loads(CATALOG.read_text(encoding="utf-8"))
        document["roles"] = [r for r in document["roles"] if r["name"] != "agentgateway-read:weight"]
        code, lines = self.run_verify(realm_from_catalog(self.catalog), document)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: rol agentgateway-read:weight existe en el realm y no está en el catálogo"])

    def test_catalogued_role_missing_from_realm_is_drift(self):
        realm = realm_from_catalog(self.catalog)
        del realm["synapse-draft-m2m"]
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: rol synapse-draft-m2m catalogado (active) no existe en el realm"])

    def test_undeclared_grant_is_drift(self):
        realm = realm_from_catalog(self.catalog)
        realm["agentgateway-read:weight"]["users"].append("qa-con-rol@e-dani.com")
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: qa-con-rol@e-dani.com tiene agentgateway-read:weight no declarada"])

    def test_lost_declared_grant_is_drift(self):
        realm = realm_from_catalog(self.catalog)
        realm["agentgateway-write"]["users"] = []
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: service-account-agentgateway-mcp declarado en agentgateway-write no la tiene concedida"])

    def test_client_role_composites_are_not_realm_composites(self):
        realm = realm_from_catalog(self.catalog)
        realm["default-roles-edani"]["client_composites"] = ["manage-account", "view-profile"]
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 0, lines)

    def test_composite_added_in_the_realm_is_drift(self):
        realm = realm_from_catalog(self.catalog)
        realm["default-roles-edani"]["composites"].append("agentgateway-read:weight")
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: default-roles-edani contiene agentgateway-read:weight y el catálogo no lo declara en composites"])

    def test_composite_removed_in_the_realm_is_drift(self):
        realm = realm_from_catalog(self.catalog)
        realm["default-roles-edani"]["composites"].remove("uma_authorization")
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: default-roles-edani declara uma_authorization en composites y el realm no lo contiene"])

    def test_role_turned_composite_without_catalog_entry_is_drift(self):
        realm = realm_from_catalog(self.catalog)
        realm["agentgateway-read:weight"]["composites"] = ["agentgateway-write"]
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: agentgateway-read:weight contiene agentgateway-write y el catálogo no lo declara en composites"])

    def test_group_holding_a_catalogued_role_is_drift(self):
        realm = realm_from_catalog(self.catalog)
        realm["agentgateway-write:media"]["groups"] = ["/operadores"]
        code, lines = self.run_verify(realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: grupo /operadores tiene agentgateway-write:media (R2: sin role-mapping por grupo)"])

    def test_deprecated_role_is_accepted_present_or_gone(self):
        document = json.loads(CATALOG.read_text(encoding="utf-8"))
        for role in document["roles"]:
            if role["name"] == "agentgateway-write:sauvage":
                role["status"] = "deprecated"
        realm = realm_from_catalog(self.catalog)
        code, lines = self.run_verify(realm, document)
        self.assertEqual((code, lines[0][:3]), (0, "OK:"))
        del realm["agentgateway-write:sauvage"]
        code, lines = self.run_verify(realm, document)
        self.assertEqual((code, lines[0][:3]), (0, "OK:"))

    def test_auth_error_exits_2(self):
        code, lines = self.run_verify(realm_from_catalog(self.catalog), token_status=401)
        self.assertEqual(code, 2)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("ERROR: HTTP 401"), lines)
        self.assertNotIn(CLIENT_SECRET, lines[0])

    def test_unreachable_keycloak_exits_2(self):
        with FakeKeycloak({}) as fake:
            url = fake.url
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify.main(["--catalog", str(CATALOG)], env={**self.env, "KEYCLOAK_URL": url})
        self.assertEqual(code, 2)
        self.assertTrue(out.getvalue().startswith("ERROR: sin respuesta"), out.getvalue())

    def test_cli_entrypoint_exit_code(self):
        with FakeKeycloak(realm_from_catalog(self.catalog)) as fake:
            completed = subprocess.run(
                [sys.executable, str(VERIFY)],
                env={**os.environ, **self.env, "KEYCLOAK_URL": fake.url},
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(completed.stdout.startswith("OK: "), completed.stdout)

    def test_secret_never_reaches_argv(self):
        source = (SCRIPTS / "kc_rbac.py").read_text(encoding="utf-8")
        # Only the docstring line that forbids it may name keycloak-bootstrap.
        self.assertEqual(source.count("keycloak-bootstrap"), 1)
        self.assertIn("os.unlink(path)", source)
        self.assertIn("0o077", source)
        verify_source = VERIFY.read_text(encoding="utf-8")
        self.assertNotIn("--client-secret", verify_source)


if __name__ == "__main__":
    unittest.main()
