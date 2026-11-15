"""Shared contract skeleton for the dedicated scoped-client hooks
(keycloak-scoped-client-lib.sh reconcilers: hermes-enviar, correo-agente,
hindsight-reader).

The reconcilers share one flow, so their contract tests share one skeleton:
fake-kcadm state builders and the tests that are identical for every scoped
client (fixed scope, secret never touched, create with exactly the reviewed
roles, idempotence, missing roles, unreviewed roles, exact minted token,
rollback). A module plugs in through class attributes:

  SCRIPT, SCRIPTS     the reconciler and its scripts directory
  CLIENTS             {client_id: [reviewed realm roles]}
  GUARD_CASES         [(client_id, env_overrides, expected_stderr)]
  MISSING_CASES       [(client_id, role, owner_message)]
  UNREVIEWED_CASES    [(client_id, extra_role)]
  AUDIT_NO_MAPPER_CLIENT  a client for the missing-audience-mapper audit case
  ROLLBACK_CLIENT     a client for the rollback case

Subclasses may add their own tests (correo-agente adds the write-role
exclusivity of its executor). Same family as keycloak_hook_testlib.py (OWU-28-g).
"""
import pathlib
import sys

TESTS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
from kcadm_fake import run_reconciler  # noqa: E402


class ScopedClientContractMixin:
    def _run(self, client_id, mode, state, env=None):
        return run_reconciler(self.SCRIPT, client_id, mode, state,
                              {"CLIENT_ID": client_id, **(env or {})})

    def _state(self, client_id, missing=(), client=None):
        state = {"clients": {}, "roles": {}}
        for role in sorted({r for roles in self.CLIENTS.values() for r in roles}):
            if role in missing:
                continue
            state["roles"][role] = {"id": f"role-{role}", "composite": False}
        if client is not None:
            state["clients"][client_id] = client
        return state

    def _converged(self, client_id, **extra):
        roles = self.CLIENTS[client_id]
        client = {
            "clientId": client_id, "enabled": "true", "publicClient": "false",
            "standardFlowEnabled": "false", "directAccessGrantsEnabled": "false",
            "implicitFlowEnabled": "false", "serviceAccountsEnabled": "true",
            "fullScopeAllowed": "false", "secret": f"generated-{client_id}",
            "sa_roles": list(roles) + ["default-roles-edani"], "scope_roles": list(roles),
            "mappers": {"m1": {"name": "aud-mcp", "audience": "mcp.lan.e-dani.com"}},
        }
        client.update(extra)
        return client

    def fixed_scope_extra_checks(self, own, script):
        """Hook for module-specific assertions on the reconciler source."""

    def test_reconciler_is_fixed_scope_and_never_touches_the_secret(self):
        own = self.SCRIPT.read_text()
        self.assertIn('. "$(dirname "$0")/keycloak-scoped-client-lib.sh"', own)
        script = own + (self.SCRIPTS / "keycloak-scoped-client-lib.sh").read_text()
        self.assertIn("unsupported immutable client", script)
        self.assertIn('. "$(dirname "$0")/keycloak-reconcile-lib.sh"', script)
        self.assertIn('ensure_role_in_client_scope "${role}"', script)
        self.assertIn('client_secret_via_admin "${CLIENT_UUID}"', script)
        self.assertNotIn("redirectUris", script)
        self.assertNotIn("create roles", script)
        self.assertNotIn("-s secret=", script)
        self.assertNotIn("set -x", script)
        self.fixed_scope_extra_checks(own, script)

    def test_guards_are_immutable_before_any_call(self):
        for client_id, env, message in self.GUARD_CASES:
            result, calls, _ = self._run(client_id, "ensure", self._state(client_id), env)
            self.assertEqual(1, result.returncode, env)
            self.assertIn(message, result.stderr)
            self.assertEqual([], calls)

    def test_ensure_creates_each_client_with_exactly_its_roles(self):
        for client_id, roles in self.CLIENTS.items():
            result, calls, state = self._run(client_id, "ensure", self._state(client_id))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f'"client_id":"{client_id}","realm_roles":"{" ".join(roles)}","present":true', result.stdout)
            self.assertIn('"fullscope_allowed":false,"token_verified":true', result.stdout)
            creates = [c for c in calls if c.startswith("create clients ") and f"clientId={client_id}" in c]
            self.assertEqual(1, len(creates))
            for flag in ("serviceAccountsEnabled=true", "publicClient=false", "standardFlowEnabled=false",
                         "directAccessGrantsEnabled=false", "implicitFlowEnabled=false", "fullScopeAllowed=false"):
                self.assertIn(flag, creates[0])
            client = state["clients"][client_id]
            self.assertEqual(roles, client["sa_roles"])
            self.assertEqual(roles, client["scope_roles"])
            self.assertEqual(["aud-mcp"], [m["name"] for m in client["mappers"].values()])
            self.assertFalse(any(c.startswith("create roles") for c in calls))
            self.assertFalse(any("secret=" in c for c in calls if c.startswith(("create", "update"))))

    def test_ensure_is_idempotent_and_audit_mutates_nothing(self):
        for client_id in self.CLIENTS:
            result, calls, _ = self._run(client_id, "ensure", self._state(client_id, client=self._converged(client_id)))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(any(c.startswith(("create clients ", "add-roles")) for c in calls))
            result, calls, _ = self._run(client_id, "audit", self._state(client_id, client=self._converged(client_id)))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(any(c.startswith(("create", "update", "add-roles", "delete")) for c in calls))

    def test_ensure_refuses_to_run_before_the_roles_exist(self):
        for client_id, role, owner in self.MISSING_CASES:
            result, calls, _ = self._run(client_id, "ensure", self._state(client_id, missing=(role,)))
            self.assertEqual(1, result.returncode)
            self.assertIn(f"{role} is missing; {owner}", result.stderr)
            self.assertFalse(any(c.startswith("create") for c in calls))

    def test_unreviewed_roles_fail_closed(self):
        for client_id, extra in self.UNREVIEWED_CASES:
            client = self._converged(client_id, sa_roles=self.CLIENTS[client_id] + ["default-roles-edani", extra])
            result, _, _ = self._run(client_id, "ensure", self._state(client_id, client=client))
            self.assertEqual(1, result.returncode, (client_id, extra))
            self.assertIn(f"unreviewed AgentGateway role: {extra}", result.stderr)
            client = self._converged(client_id, scope_roles=self.CLIENTS[client_id] + [extra])
            result, _, _ = self._run(client_id, "ensure", self._state(client_id, client=client))
            self.assertEqual(1, result.returncode, (client_id, extra))
            self.assertIn(f"client role scope has unexpected role {extra}", result.stderr)

    def test_minted_token_must_be_exact(self):
        for client_id in self.CLIENTS:
            state = self._state(client_id, client=self._converged(client_id))
            result, _, _ = self._run(client_id, "ensure", state, {"FAKE_TOKEN_EXTRA_ROLES": "agentgateway-write"})
            self.assertEqual(1, result.returncode)
            self.assertIn("minted token contains a forbidden agentgateway-write role", result.stderr)
            result, _, _ = self._run(client_id, "ensure", state, {"FAKE_TOKEN_EXTRA_ROLES": "offline_access"})
            self.assertEqual(1, result.returncode)
            self.assertIn(f"minted {client_id} token realm roles are not exactly", result.stderr)
        result, _, _ = self._run(self.AUDIT_NO_MAPPER_CLIENT, "audit",
                                 self._state(self.AUDIT_NO_MAPPER_CLIENT,
                                             client=self._converged(self.AUDIT_NO_MAPPER_CLIENT, mappers={})))
        self.assertEqual(1, result.returncode)
        self.assertIn("audience mapper missing", result.stderr)

    def test_rollback_deletes_the_client_and_retains_the_roles(self):
        client_id = self.ROLLBACK_CLIENT
        result, calls, state = self._run(client_id, "rollback",
                                         self._state(client_id, client=self._converged(client_id)))
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"client_present":false,"roles_retained":true', result.stdout)
        self.assertFalse(any(c.startswith("delete roles") for c in calls))
        for role in {r for roles in self.CLIENTS.values() for r in roles}:
            self.assertIn(role, state["roles"])
        self.assertEqual({}, state["clients"])
