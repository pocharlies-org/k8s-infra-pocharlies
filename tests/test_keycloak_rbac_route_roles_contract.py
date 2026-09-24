"""INFRA-249 (INFRA-219 C3): ROUTE-ROLES.md and verify-route-roles.py.

No network: the AgentGateway config is a local config.yaml rendered in the
gateway's own rule shapes (--config-file), and the realm is the stdlib fake
Keycloak of the catalog contract test, bound to 127.0.0.1.
"""

import contextlib
import copy
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPTS = BASE / "scripts"
MATRIX = BASE / "ROUTE-ROLES.md"

sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load("verify_route_roles", SCRIPTS / "verify-route-roles.py")
catalog_test = _load("catalog_contract", ROOT / "tests" / "test_keycloak_rbac_catalog_contract.py")
FakeKeycloak = catalog_test.FakeKeycloak

ROLES = '"{role}" in jwt.realm_access.roles'


def render_config(routes):
    """A config.yaml in the gateway's layout: one route per path, CEL rules on one line."""
    out = [
        "# AgentGateway STANDALONE config (test copy).",
        '# A comment naming "agentgateway-write" in jwt.realm_access.roles is not a gate.',
        "binds:",
        "  - port: 3000",
        "    listeners:",
        "      - name: mcp",
        "        routes:",
    ]
    for route in routes:
        out += [
            f"          - name: {route['route']}",
            f"            matches: [ {{ path: {{ pathPrefix: {route['path']} }} }} ]",
            f"            # - name: not-a-route",
            "            policies:",
            "              jwtAuth:",
            '                mode: "$JWT_MODE"',
        ]
        if route["require"]:
            roles = " || ".join(ROLES.format(role=role) for role in route["require"])
            out += [
                "              authorization:",
                "                rules:",
                f"                  - require: 'has(jwt.realm_access) && has(jwt.realm_access.roles) && ({roles})'",
            ]
        out += ["              mcpAuthorization:", "                rules:",
                "                  - 'mcp.tool.name == \"health\"'"]
        for role, tools in route["tools"].items():
            for tool in tools:
                out.append(f"                  - 'mcp.tool.name == \"{tool}\" && $GATEWAY_WRITE && {ROLES.format(role=role)}'")
            listed = ", ".join(f'"{tool}"' for tool in tools)
            out.append(f"                  - 'mcp.tool.name in [{listed}] && $GATEWAY_WRITE && {ROLES.format(role=role)}'")
        out += [
            "            backends:",
            "              - mcp:",
            "                  targets:",
            f"                    - name: {route['route']}",
            "                      mcp: { host: http://backend:3030/mcp }",
        ]
    return "\n".join(out) + "\n"


def render_matrix(document):
    return f"# ROUTE-ROLES (test copy)\n\n```json\n{json.dumps(document, indent=2)}\n```\n"


SMALL = {
    "schema": "agentgateway-route-roles/v1",
    "routes": [
        {"route": "picqer", "path": "/picqer", "require": ["agentgateway-read:picqer"],
         "tools": {"agentgateway-write": ["picqer_orders", "picqer_products"],
                   "agentgateway-write:picqer": ["picqer_orders", "picqer_products"]}},
        {"route": "dgx-control", "path": "/dgx-control", "require": [],
         "tools": {"agentgateway-write:dgx-control": ["compute_mode_set", "opencode_restart"]}},
        {"route": "chat-stt", "path": "/chat-stt", "require": [], "tools": {}},
        {"route": "cto-office", "path": "/cto-office", "require": ["cto-office-send"],
         "tools": {"cto-office-send": ["cto_office_send"]}},
    ],
    "unrouted": [
        {"role": "agentgateway-read:image", "disposition": "reservado", "purpose": "sin require en /image"},
        {"role": "claude-sessions", "disposition": "aplicacion", "purpose": "rol del backend"},
    ],
}
SMALL_REALM = [
    "agentgateway-read:picqer", "agentgateway-write", "agentgateway-write:picqer",
    "agentgateway-write:dgx-control", "cto-office-send", "agentgateway-read:image",
    "claude-sessions", "default-roles-edani", "offline_access",
]


class RouteRolesVerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self.tmp.name)
        (tmp / "client_id").write_text(catalog_test.CLIENT_ID + "\n")
        (tmp / "client_secret").write_text(catalog_test.CLIENT_SECRET + "\n")
        self.env = {
            "KC_CLIENT_ID_FILE": str(tmp / "client_id"),
            "KC_CLIENT_SECRET_FILE": str(tmp / "client_secret"),
            "KC_REALM": "edani",
        }
        self.dir = tmp

    def tearDown(self):
        self.tmp.cleanup()

    def run_verify(self, matrix, config_routes=None, realm=SMALL_REALM, matrix_text=None, config_text=None):
        matrix_path, config_path = self.dir / "ROUTE-ROLES.md", self.dir / "config.yaml"
        matrix_path.write_text(matrix_text if matrix_text is not None else render_matrix(matrix))
        if config_text is None:
            config_text = render_config(config_routes if config_routes is not None else matrix["routes"])
        config_path.write_text(config_text)
        with FakeKeycloak({name: {"users": [], "groups": []} for name in realm}) as fake:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = verify.main(["--matrix", str(matrix_path), "--config-file", str(config_path)],
                                   env={**self.env, "KEYCLOAK_URL": fake.url})
            self.assertTrue(all(method == "GET" for method, path in fake.requests if "/admin/" in path),
                            "the verifier must never mutate the realm")
        return code, out.getvalue().splitlines()

    def test_coherent_matrix_config_and_realm_is_ok(self):
        code, lines = self.run_verify(SMALL)
        self.assertEqual(code, 0, lines)
        # picqer 3 + dgx-control 1 + chat-stt 0 + cto-office 1 (require and tools count once)
        self.assertEqual(lines, ["OK: 5 gates coherentes, 0 roles referenciados inexistentes, 0 roles sin ruta documentada"])

    def test_role_referenced_by_config_and_missing_from_realm_is_drift(self):
        realm = [name for name in SMALL_REALM if name != "agentgateway-write:dgx-control"]
        code, lines = self.run_verify(SMALL, realm=realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: agentgateway-write:dgx-control referenciado en config y ausente del realm"])

    def test_live_gateway_role_without_route_or_unrouted_entry_is_drift(self):
        code, lines = self.run_verify(SMALL, realm=SMALL_REALM + ["agentgateway-read:tts"])
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: rol gateway agentgateway-read:tts vivo sin ruta que lo exija ni entrada en unrouted"])

    def test_non_gateway_realm_roles_are_out_of_scope(self):
        code, _ = self.run_verify(SMALL, realm=SMALL_REALM + ["uma_authorization", "synapse-draft-m2m"])
        self.assertEqual(code, 0)

    def test_deleted_tool_row_names_route_and_role(self):
        matrix = copy.deepcopy(SMALL)
        del matrix["routes"][0]["tools"]["agentgateway-write:picqer"]
        code, lines = self.run_verify(matrix, config_routes=SMALL["routes"])
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: ruta picqer: agentgateway-write:picqer gatea 2 tools en el config y la matriz no lo recoge"])

    def test_deleted_route_row_names_the_route(self):
        matrix = copy.deepcopy(SMALL)
        matrix["routes"] = [r for r in matrix["routes"] if r["route"] != "cto-office"]
        code, lines = self.run_verify(matrix, config_routes=SMALL["routes"])
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: ruta cto-office (/cto-office) está en el config y no en la matriz (cto-office-send)"])

    def test_route_level_role_and_tool_differences_are_drift(self):
        config = copy.deepcopy(SMALL["routes"])
        config[0]["require"] = []
        config[0]["tools"]["agentgateway-write"].append("picqer_webhooks")
        code, lines = self.run_verify(SMALL, config_routes=config)
        self.assertEqual(code, 1)
        self.assertIn("DRIFT: ruta picqer: la matriz declara agentgateway-read:picqer a nivel de ruta y el config no lo exige", lines)
        self.assertIn("DRIFT: ruta picqer: tool picqer_webhooks gateada por agentgateway-write falta en la matriz", lines)
        # read:picqer is no longer referenced by the config: it is a live role without route now.
        self.assertIn("DRIFT: rol gateway agentgateway-read:picqer vivo sin ruta que lo exija ni entrada en unrouted", lines)

    def test_matrix_route_gone_from_config_is_drift(self):
        config = [r for r in SMALL["routes"] if r["route"] != "chat-stt"]
        code, lines = self.run_verify(SMALL, config_routes=config)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: ruta chat-stt está en la matriz y no en el config"])

    def test_unrouted_role_that_a_route_requires_is_drift(self):
        matrix = copy.deepcopy(SMALL)
        matrix["unrouted"].append({"role": "cto-office-send", "disposition": "reservado", "purpose": "x"})
        code, lines = self.run_verify(matrix, config_routes=SMALL["routes"])
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: cto-office-send está en unrouted pero lo exige la ruta cto-office"])

    def test_unrouted_role_missing_from_realm_is_drift(self):
        realm = [name for name in SMALL_REALM if name != "claude-sessions"]
        code, lines = self.run_verify(SMALL, realm=realm)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["DRIFT: claude-sessions está en unrouted y ausente del realm"])

    def test_unreadable_rule_shape_is_an_error_not_a_silent_pass(self):
        config = render_config(SMALL["routes"]) + (
            "          - name: odd\n"
            "            matches: [ { path: { pathPrefix: /odd } } ]\n"
            "            policies:\n"
            "              mcpAuthorization:\n"
            "                rules:\n"
            "                  - >-\n"
            '                    "agentgateway-write" in jwt.realm_access.roles\n'
        )
        code, lines = self.run_verify(SMALL, config_text=config)
        self.assertEqual(code, 2)
        self.assertTrue(lines[0].startswith("ERROR: config: ruta odd: 1 referencias de rol fuera de una regla legible"), lines)

    def test_matrix_needs_exactly_one_json_block(self):
        code, lines = self.run_verify(SMALL, matrix_text=render_matrix(SMALL) + "\n```json\n{}\n```\n")
        self.assertEqual(code, 2)
        self.assertIn("exactamente un bloque", lines[0])

    def test_unknown_disposition_is_an_error(self):
        matrix = copy.deepcopy(SMALL)
        matrix["unrouted"][0]["disposition"] = "borrar"
        code, lines = self.run_verify(matrix, config_routes=SMALL["routes"])
        self.assertEqual(code, 2)
        self.assertIn("disposition de agentgateway-read:image", lines[0])


class RouteRolesMatrixTest(unittest.TestCase):
    """The committed ROUTE-ROLES.md: shape and the INFRA-249 facts it records."""

    def setUp(self):
        self.routes, self.unrouted = verify.load_matrix(MATRIX)

    def test_committed_matrix_round_trips_through_the_config_parser(self):
        document = kc_rbac.load_json_block(MATRIX)
        parsed = verify.parse_config(render_config(document["routes"]))
        self.assertEqual(parsed, self.routes)

    def test_dgx_control_writes_are_gated_on_the_new_domain_role(self):
        for route in ("dgx-control", "chat-dgx-control"):
            self.assertEqual(self.routes[route]["require"], set(), route)
            self.assertEqual(self.routes[route]["tools"], {
                "agentgateway-write:dgx-control": {"compute_mode_set", "refusal_lambda_set", "opencode_restart"},
            }, route)

    def test_cto_office_is_documented_and_untouched(self):
        self.assertEqual(self.routes["cto-office"]["require"], {"cto-office-send"})
        self.assertIn("cto-office-send", self.routes["cto-office"]["tools"])

    def test_claude_sessions_roles_are_classified(self):
        self.assertEqual(self.routes["claude-sessions-read"]["require"], {"agentgateway-read:claude-sessions"})
        self.assertEqual(self.routes["claude-sessions-write"]["require"], {"agentgateway-write:claude-sessions"})
        self.assertEqual(self.unrouted["claude-sessions"]["disposition"], "aplicacion")

    def test_every_catalogued_gateway_role_is_routed_or_unrouted(self):
        catalog = kc_rbac.load_role_catalog(BASE / "ROLES.yaml")
        routed = set().union(*(r["require"] | set(r["tools"]) for r in self.routes.values()))
        gateway = {name for name, entry in catalog.items()
                   if name.startswith("agentgateway-") and entry["status"] == "active"}
        self.assertEqual(gateway - routed - set(self.unrouted), set())
        self.assertEqual(routed & set(self.unrouted), set())
        self.assertEqual(set(self.unrouted) - set(catalog), set())
        self.assertEqual(routed - set(catalog), set(), "every gated role is catalogued in ROLES.yaml")


if __name__ == "__main__":
    unittest.main()
