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
CHAT_SA = "service-account-chat-agentgateway"
JARVIS_SA = "service-account-jarvis-echo"
ENVIAR_SA = "service-account-hermes-enviar"
SECRETARIA_SAS = [
    "service-account-hermes-secretaria",
    "service-account-hermes-secretaria-casa",
    "service-account-hermes-secretaria-dani",
    "service-account-hermes-secretaria-leila",
]
SECRETARIA_SKIRMSHOP_SA = "service-account-hermes-secretaria-skirmshop"
PROBE_SA = "service-account-atlassian-mcp-probe"


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
        chat = shell_list(READ_GRANTS, "EXPECTED_CHAT_READ_ROLE_NAMES")
        jarvis = shell_list(READ_GRANTS, "EXPECTED_JARVIS_READ_ROLE_NAMES")
        enviar = shell_list(READ_GRANTS, "EXPECTED_ENVIAR_READ_ROLE_NAMES")
        secretaria =shell_list(READ_GRANTS, "EXPECTED_SECRETARIA_READ_ROLE_NAMES")
        secretaria_skirmshop = shell_list(READ_GRANTS, "EXPECTED_SECRETARIA_SKIRMSHOP_READ_ROLE_NAMES")
        probe = shell_list(READ_GRANTS, "EXPECTED_PROBE_READ_ROLE_NAMES")
        self.assertTrue(set(openclaw) <= set(reads))
        self.assertTrue(set(chat) <= set(reads))
        self.assertTrue(set(jarvis) <= set(reads))
        self.assertTrue(set(enviar) <= set(reads))
        owned =owned_by(self.catalog, READ_GRANTS)
        self.assertEqual(set(owned), set(reads), "roles owned by agentgateway-read-grants.sh")
        for role in reads:
            # SC-699: the chat grantee travels in the read-grants holder
            # allowlist (EXPECTED_CHAT_READ_ROLE_NAMES); the grant itself is
            # owned by chat-agentgateway-client.sh. INFRA-477: same rule for
            # the jarvis-echo grantee (EXPECTED_JARVIS_READ_ROLE_NAMES), the
            # grant owned by jarvis-echo-client.sh.
            expected = (
                {MCP_SA}
                | ({OPENCLAW_SA} if role in openclaw else set())
                | ({CHAT_SA} if role in chat else set())
                | ({JARVIS_SA} if role in jarvis else set())
                # INFRA-676: same rule for the hermes-enviar grantee
                # (EXPECTED_ENVIAR_READ_ROLE_NAMES), the grant owned by
                # hermes-enviar-client.sh.
                | ({ENVIAR_SA} if role in enviar else set())
                # SC-2005: reviewed holders granted outside this reconciler
                # (INFRA-494 secretarias, SC-1834 probe).
                | (set(SECRETARIA_SAS) if role in secretaria else set())
                | ({SECRETARIA_SKIRMSHOP_SA} if role in secretaria_skirmshop else set())
                | ({PROBE_SA} if role in probe else set())
            )
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
        self.assertEqual(shell_list(READ_GRANTS, "EXPECTED_CHAT_READ_ROLE_NAMES"), ["agentgateway-read:studio"])
        self.assertEqual(shell_list(READ_GRANTS, "EXPECTED_JARVIS_READ_ROLE_NAMES"), ["agentgateway-read:workspace"])
        self.assertEqual(shell_list(READ_GRANTS, "EXPECTED_ENVIAR_READ_ROLE_NAMES"), ["agentgateway-read:workspace"])
        self.assertEqual(len(shell_list(READ_GRANTS, "EXPECTED_SECRETARIA_READ_ROLE_NAMES")), 3)
        self.assertEqual(len(shell_list(READ_GRANTS, "EXPECTED_SECRETARIA_SKIRMSHOP_READ_ROLE_NAMES")), 5)
        self.assertEqual(shell_list(READ_GRANTS, "EXPECTED_PROBE_READ_ROLE_NAMES"), ["agentgateway-read:atlassian"])
        self.assertGreaterEqual(len(shell_list(DOMAIN_ROLES, "EXPECTED_ROLE_NAMES")), 14)
        self.assertEqual(
            len([pair for pair in shell_list(DOMAIN_ROLES, "EXPECTED_ALLOWED_SERVICE_ACCOUNTS")
                 if pair.endswith(("hermes-secretaria", "hermes-secretaria-casa",
                                    "hermes-secretaria-dani", "hermes-secretaria-leila"))]),
            8)

    def test_chat_extra_holders_parity_with_domain_roles(self):
        # SC-2029: the chat hook's exclusivity guard tolerates, on
        # write:social/:workspace, exactly the reviewed holders of the
        # domain-roles allowlist that are not its own service account — one
        # source of truth, no silent drift between the two guards.
        # INFRA-676: "its own" roles means the ones the chat hook guards
        # (its ROLE_NAMES). A holder of a role the chat hook never inspects
        # (workspace-envio, held by hermes-enviar) is not its business, and
        # copying that pair there would be dead config.
        chat = SCRIPTS / "chat-agentgateway-client.sh"
        extra = set(shell_list(chat, "EXPECTED_REVIEWED_EXTRA_HOLDERS"))
        chat_roles = set(re.search(r'^EXPECTED_ROLE_NAMES="([^"]*)"$',
                                   chat.read_text(encoding="utf-8"), re.MULTILINE).group(1).split())
        domain = {
            pair for pair in shell_list(DOMAIN_ROLES, "EXPECTED_ALLOWED_SERVICE_ACCOUNTS")
            if not pair.endswith("=service-account-chat-agentgateway")
            and pair.partition("=")[0] in chat_roles
        }
        self.assertEqual(extra, domain)
        guarded_elsewhere = {
            pair for pair in shell_list(DOMAIN_ROLES, "EXPECTED_ALLOWED_SERVICE_ACCOUNTS")
            if pair.partition("=")[0] not in chat_roles
        }
        self.assertEqual({"agentgateway-write:workspace-envio=service-account-hermes-enviar"}, guarded_elsewhere)


if __name__ == "__main__":
    unittest.main()
