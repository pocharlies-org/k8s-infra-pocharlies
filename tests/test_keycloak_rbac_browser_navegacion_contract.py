"""SC-2247 (SC-2238): the three catalogue copies of `agentgateway-write:browser-navegacion` agree.

ROLES.yaml (meaning), ROUTE-ROLES.md (the bounded and the bare /browser lists) and PRINCIPALS.md
(who holds it) state the same 27 tools by hand; nothing else ties them. This test pins them to
Security's cut of SC-2238, as set equality (never lengths), so a 28th tool, a tool the bare role
does not have or a sensitive one slipping in fails here and not in a reviewer's recount.
"""

import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
sys.path.insert(0, str(BASE / "scripts"))
import kc_rbac  # noqa: E402

ROLE = "agentgateway-write:browser-navegacion"
BARE = "agentgateway-write"
HOLDERS = {f"service-account-hermes-secretaria{suffix}" for suffix in ("", "-dani", "-leila", "-casa", "-skirmshop")}

# Security's verdict (SC-2238): what moving around and looking at a page needs.
NAVIGATION = {f"browser_{name}" for name in (
    "navigate", "go_back", "go_forward", "reload", "state", "find", "snapshot", "click", "type", "hover", "drag",
    "select_option", "press_key", "wait", "wait_for_element", "is_visible", "get_text", "get_html", "get_attribute",
    "screenshot", "resize_viewport", "list_tabs", "new_tab", "switch_tab", "send_to_back", "close_tab", "highlight",
)}
# What stays with the bare role only.
SENSITIVE = {f"browser_{name}" for name in (
    "fill_secret", "passkey", "evaluate", "iframe_eval", "iframe_click", "upload_file", "drop", "get_console_logs",
    "network_request", "network_requests", "pdf", "fill_form", "list_connections",
)}
UNSAFE = "browser_run_code_unsafe"


class BrowserNavegacionCatalogTest(unittest.TestCase):
    def setUp(self):
        self.catalog = kc_rbac.load_role_catalog(BASE / "ROLES.yaml")
        self.entry = self.catalog[ROLE]
        route = next(r for r in kc_rbac.load_json_block(BASE / "ROUTE-ROLES.md")["routes"] if r["route"] == "browser")
        self.bounded = route["tools"][ROLE]
        self.bare = route["tools"][BARE]
        self.matrix_text = (BASE / "ROUTE-ROLES.md").read_text(encoding="utf-8")
        self.principals = kc_rbac.load_json_block(BASE / "PRINCIPALS.md")["principals"]

    def test_the_cut_is_27_navigation_tools_and_13_sensitive_ones_apart(self):
        self.assertEqual((len(NAVIGATION), len(SENSITIVE)), (27, 13))
        self.assertEqual(NAVIGATION & SENSITIVE, set())

    def test_roles_yaml_meaning_lists_exactly_the_27_tools_once_each(self):
        listed = re.findall(r"browser_[a-z_]+", self.entry["meaning"])
        self.assertEqual(len(listed), len(set(listed)), "a tool repeated in meaning")
        self.assertEqual(set(listed), NAVIGATION)
        self.assertEqual(len(listed), 27)

    def test_roles_yaml_allows_points_at_that_same_list(self):
        allows = self.entry["privilege"]["allows"]
        self.assertIn("enumeradas en meaning", allows)
        self.assertEqual(re.findall(r"browser_[a-z_]+", allows), [], "allows must point at meaning, not keep its own copy")
        self.assertEqual(re.search(r"\b(\d+) tools\b", allows).group(1), "27")

    def test_route_roles_bounded_list_is_the_same_set_as_roles_yaml(self):
        self.assertEqual(len(self.bounded), len(set(self.bounded)), "a tool repeated in the bounded list")
        self.assertEqual(set(self.bounded), set(re.findall(r"browser_[a-z_]+", self.entry["meaning"])))
        self.assertEqual(set(self.bounded), NAVIGATION)

    def test_bounded_is_inside_the_bare_list_of_browser_and_apart_from_the_sensitive(self):
        self.assertEqual(len(self.bare), len(set(self.bare)), "a tool repeated in the bare list")
        # Set, not length: a new /browser tool fails by name until Security files it as navigation or sensitive.
        self.assertEqual(set(self.bare), NAVIGATION | SENSITIVE)
        self.assertEqual(set(self.bounded) - set(self.bare), set(), "the bounded role gates a tool the bare one does not")
        self.assertEqual(set(self.bounded) & SENSITIVE, set(), "a sensitive tool slipped into the bounded role")

    def test_run_code_unsafe_is_in_neither_list(self):
        self.assertNotIn(UNSAFE, self.bounded)
        self.assertNotIn(UNSAFE, self.bare)
        self.assertNotIn(UNSAFE, self.entry["meaning"])

    def test_route_roles_table_row_states_the_same_counts(self):
        row = next(line for line in self.matrix_text.splitlines() if line.startswith("| `browser` |"))
        self.assertIn(f"`{BARE}` (40)", row)
        self.assertIn(f"`{ROLE}` (27)", row)

    def test_only_the_five_secretaria_profiles_hold_it_and_none_with_the_bare_role(self):
        held = {p["username"] for p in self.principals if ROLE in p["realm_roles"]}
        self.assertEqual(held, HOLDERS)
        self.assertEqual(set(self.entry["grantees"]), HOLDERS)
        for principal in self.principals:
            if principal["username"] in HOLDERS:
                self.assertNotIn(BARE, principal["realm_roles"], principal["username"])
        self.assertEqual([n for n, e in self.catalog.items() if ROLE in e.get("composites", [])], [],
                         "a composite would hand the role to someone else")
        for field in ("composites", "client_composites"):
            self.assertNotIn(field, self.entry, "the role must not drag the bare role or anything else along")


if __name__ == "__main__":
    unittest.main()
