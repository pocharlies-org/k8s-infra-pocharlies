"""INFRA-247 (INFRA-219 C-1): one source of truth for the reconciled roles.

The reconcilers keep their reviewed matrices as immutable shell constants.
ROLES.yaml must say exactly the same thing about the roles each of them owns:
same role set, same grantees. A change to one without the other fails here.
"""

import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPTS = BASE / "scripts"

sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402

READ_GRANTS = SCRIPTS / "agentgateway-read-grants.sh"
DOMAIN_ROLES = SCRIPTS / "agentgateway-domain-roles.sh"
MCP_SA = "service-account-agentgateway-mcp"
OPENCLAW_SA = "service-account-openclaw-readonly-agentgateway"


def shell_list(path, variable):
    match = re.search(rf'^{variable}="([^"]*)"$', path.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise AssertionError(f"{variable} not found in {path.name}")
    return [item for item in match.group(1).split(",") if item]


def owned_by(catalog, script):
    return {name: entry for name, entry in catalog.items()
            if entry["status"] == "active" and entry["origin"].startswith(script.name)}


class RoleCatalogParityTest(unittest.TestCase):
    def setUp(self):
        self.catalog = kc_rbac.load_role_catalog(BASE / "ROLES.yaml")

    def test_read_grants_matrix_matches_catalog(self):
        reads = shell_list(READ_GRANTS, "EXPECTED_READ_ROLE_NAMES")
        openclaw = shell_list(READ_GRANTS, "EXPECTED_OPENCLAW_READ_ROLE_NAMES")
        self.assertTrue(set(openclaw) <= set(reads))
        owned = owned_by(self.catalog, READ_GRANTS)
        self.assertEqual(set(owned), set(reads), "roles owned by agentgateway-read-grants.sh")
        for role in reads:
            expected = {MCP_SA} | ({OPENCLAW_SA} if role in openclaw else set())
            self.assertEqual(set(owned[role]["grantees"]), expected, role)

    def test_domain_roles_matrix_matches_catalog(self):
        roles = shell_list(DOMAIN_ROLES, "EXPECTED_ROLE_NAMES")
        allowed = {}
        for pair in shell_list(DOMAIN_ROLES, "EXPECTED_ALLOWED_SERVICE_ACCOUNTS"):
            role, _, account = pair.partition("=")
            self.assertIn(role, roles, pair)
            allowed.setdefault(role, set()).add(account)
        owned = owned_by(self.catalog, DOMAIN_ROLES)
        self.assertEqual(set(owned), set(roles), "roles owned by agentgateway-domain-roles.sh")
        for role in roles:
            self.assertEqual(set(owned[role]["grantees"]), allowed.get(role, set()), role)

    def test_extractor_reads_the_reviewed_constants(self):
        # Guard against a silent parse: the matrices are non-trivial today.
        self.assertEqual(len(shell_list(READ_GRANTS, "EXPECTED_READ_ROLE_NAMES")), 21)
        self.assertEqual(len(shell_list(READ_GRANTS, "EXPECTED_OPENCLAW_READ_ROLE_NAMES")), 6)
        self.assertGreaterEqual(len(shell_list(DOMAIN_ROLES, "EXPECTED_ROLE_NAMES")), 11)


if __name__ == "__main__":
    unittest.main()
