"""SC-4304 S6: contract of the chat `personal` memory frontier (security ruling
of 03-11-2026, decision of Dani: the personal bank is read by me@e-dani.com and
lays84.mv@gmail.com, those two and nobody else).

Three pieces, one frontier:

* agentgateway-chat-hindsight-mcp-client.sh — the dedicated PUBLIC PKCE client
  of the Open WebUI connection to /chat-hindsight-personal (the
  agentgateway-social-mcp pattern + the explicit single-role realm scope of
  agentgateway-chat-mcp-client.sh). Pinned here: public browser client only,
  exact redirect URI, fullScopeAllowed=false, realm scope EXACTLY
  agentgateway-read:hindsight-personal, never creates the role, no secret.
* agentgateway-hindsight-personal-grants.sh — owns the COMPLETE direct holder
  set of the role: the two humans pinned by subject (OWU-80 discipline), the
  two reviewed Hermes SAs, revocation of every other holder (the chat SA
  bypass of SC-4051 is what this closes), no group mappings, and revoke of the
  manual scope mapping in the chat-agentgateway client. Rollback removes only
  the two human grants.
* the catalog declarations (ROLES.yaml grantees == the four holders,
  PRINCIPALS.md realm_roles in parity, ROUTE-ROLES.md row for the new route),
  which the keycloak-role-drift sweep checks against the live realm and the
  SC-4414 guard checks against the grant surface.

Stdlib only, like the rest of the keycloak-rbac-contract job.
"""

import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
sys.path.insert(0, str(BASE / "scripts"))

import kc_rbac  # noqa: E402  (repo's own catalog loader)

ROLE = "agentgateway-read:hindsight-personal"
DANI_ID = "e51253a7-c137-4c6c-9fb9-af9cecd3b147"
LEILA_ID = "66ec6f4f-5f2c-44f6-a3db-0dccba6e1748"
HOLDERS = {
    "me@e-dani.com",
    "lays84.mv@gmail.com",
    "service-account-hermes-secretaria",
    "service-account-hermes-secretaria-casa",
}
CHAT_SA = "service-account-chat-agentgateway"

CLIENT_SCRIPT = BASE / "scripts" / "agentgateway-chat-hindsight-mcp-client.sh"
CLIENT_ENGINE = BASE / "scripts" / "agentgateway-chat-mcp-client.sh"
CLIENT_JOB = BASE / "agentgateway-chat-hindsight-mcp-client.yaml"
CLIENT_ROLLBACK = BASE / "manual" / "agentgateway-chat-hindsight-mcp-client-rollback-job.yaml"
GRANTS_SCRIPT = BASE / "scripts" / "agentgateway-hindsight-personal-grants.sh"
GRANTS_JOB = BASE / "agentgateway-hindsight-personal-grants-job.yaml"
GRANTS_ROLLBACK = BASE / "manual" / "agentgateway-hindsight-personal-grants-rollback-job.yaml"


class ChatHindsightMcpClientContractTest(unittest.TestCase):
    def test_wrapper_carries_the_identity_and_execs_the_shared_engine(self):
        # #452 (jscpd dedup): this client is the shared chat engine driven by a
        # thin wrapper that carries ONLY its identity. Identity on the wrapper,
        # behavior on the engine (shared with agentgateway-chat-mcp).
        script = CLIENT_SCRIPT.read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-agentgateway-chat-hindsight-mcp}"', script)
        self.assertIn('EXPECTED_CLIENT_ID="agentgateway-chat-hindsight-mcp"', script)
        self.assertIn(
            'REDIRECT_URIS="${REDIRECT_URIS:-https://chat.e-dani.com/oauth/clients/mcp:hindsight-personal/callback}"',
            script,
        )
        self.assertIn(
            'REALM_SCOPE_ROLE_NAMES="${REALM_SCOPE_ROLE_NAMES:-agentgateway-read:hindsight-personal}"',
            script,
        )
        self.assertIn('EXPECTED_REALM_SCOPE_ROLE_NAMES="agentgateway-read:hindsight-personal"', script)
        # the role is owned by the catalog, never created here
        self.assertIn('ROLE_OWNER="the catalog"', script)
        # the scope comparison is EXACT, never a subset (read-grants precedent)
        self.assertIn('SCOPE_AUDIT="exact"', script)
        self.assertIn(
            'ADMIN_CONFIG="${ADMIN_CONFIG:-/tmp/kcadm-agentgateway-chat-hindsight-admin.config}"',
            script,
        )
        self.assertIn('exec /bin/sh "${0%/*}/agentgateway-chat-mcp-client.sh"', script)
        self.assertNotIn("set -x", script)
        self.assertNotIn("CLIENT_SECRET", script)

    def test_engine_is_a_public_pkce_client_with_the_exact_scope_audit(self):
        engine = CLIENT_ENGINE.read_text()
        self.assertIn('REALM="${REALM:-edani}"', engine)
        self.assertIn('MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"', engine)
        self.assertIn('PKCE_METHOD="${PKCE_METHOD:-S256}"', engine)
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', engine)
        self.assertIn("REALM_SCOPE_ROLE_NAMES is immutable", engine)
        self.assertIn('RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"', engine)
        # public browser client: auth-code + PKCE only, no secret, no service
        # account, no direct access, no implicit; the scope is explicit.
        self.assertIn("publicClient=true", engine)
        self.assertIn("standardFlowEnabled=true", engine)
        self.assertIn("directAccessGrantsEnabled=false", engine)
        self.assertIn("implicitFlowEnabled=false", engine)
        self.assertIn("serviceAccountsEnabled=false", engine)
        self.assertIn("fullScopeAllowed=false", engine)
        self.assertIn('attributes.\\"pkce.code.challenge.method\\"', engine)
        # the exact branch of the shared engine: fullScopeAllowed asserted and
        # the scope compared as a whole, never as a subset.
        self.assertIn('assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false', engine)
        self.assertIn('actual="$(scope_names)"', engine)
        self.assertIn('fail "client realm scope mapping must be exactly', engine)
        # the role is never created here, whatever ROLE_OWNER the wrapper sets.
        self.assertIn("refusing to create it here", engine)
        # INFRA-197 regression: PKCE check reads the client without --fields.
        self.assertIn('kget "clients/${CLIENT_UUID}" --format json', engine)
        self.assertIn("oidc-audience-mapper", engine)
        self.assertIn('config."userinfo.token.claim"=false', engine)
        self.assertNotIn("mint", engine)
        self.assertNotIn("CLIENT_SECRET", engine)
        self.assertIn("rollback_identity", engine)
        self.assertNotIn("set -x", engine)

    def test_manifest_is_a_hardened_postsync_job_with_no_secret(self):
        manifest = CLIENT_JOB.read_text()
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertNotIn("client_secret", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn('argocd.argoproj.io/sync-wave: "23"', manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn('agentgateway.e-dani.com/reconcile-contract-version: "1"', manifest)
        self.assertIn("name: CLIENT_ID, value: agentgateway-chat-hindsight-mcp", manifest)
        self.assertIn(
            "name: REDIRECT_URIS, value: \"https://chat.e-dani.com/oauth/clients/mcp:hindsight-personal/callback\"",
            manifest,
        )
        self.assertIn("name: REALM_SCOPE_ROLE_NAMES, value: agentgateway-read:hindsight-personal", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        rollback = CLIENT_ROLLBACK.read_text()
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)


class HindsightPersonalGrantsContractTest(unittest.TestCase):
    def test_reconciler_owns_the_exact_holder_set(self):
        script = GRANTS_SCRIPT.read_text()
        self.assertIn('ROLE_NAME="${ROLE_NAME:-agentgateway-read:hindsight-personal}"', script)
        self.assertIn('EXPECTED_ROLE_NAME="agentgateway-read:hindsight-personal"', script)
        self.assertIn("ROLE_NAME is immutable", script)
        # humans pinned by subject (OWU-80 discipline), usernames cross-checked
        self.assertIn(DANI_ID + "=me@e-dani.com", script)
        self.assertIn(LEILA_ID + "=lays84.mv@gmail.com", script)
        self.assertIn("refusing to create a human user", script)
        self.assertIn("not the pinned", script)
        self.assertIn("is disabled: refusing to grant", script)
        # reviewed SA holders: asserted and re-granted, never revoked
        self.assertIn(
            'REVIEWED_SERVICE_ACCOUNTS="service-account-hermes-secretaria,service-account-hermes-secretaria-casa"',
            script,
        )
        # the chat SA is the revoked holder (sidecar bypass closure) and its
        # client's manual scope mapping is revoked with it
        self.assertIn('REVOKED_SERVICE_ACCOUNTS="service-account-chat-agentgateway"', script)
        self.assertIn('EXPECTED_CHAT_CLIENT_ID="chat-agentgateway"', script)
        self.assertIn("failed to remove ${ROLE_NAME} from the scope of ${CHAT_CLIENT_ID}", script)
        # exclusivity: every direct holder outside the reviewed set is revoked;
        # group mappings fail (SC-44 C6)
        self.assertIn("holds ${ROLE_NAME} outside the reviewed holder set", script)
        self.assertIn("group role-mapping is forbidden", script)
        # never creates the role
        self.assertIn("refusing to create it here", script)
        # rollback touches only the two human grants
        self.assertIn("Removes ONLY the two human grants", GRANTS_ROLLBACK.read_text())
        # Keycloak's username search is a SUBSTRING match: without exact=true
        # username=service-account-hermes-secretaria also matched -casa and the
        # other hermes-secretaria-* (measured 2026-11-04: the PostSync failed
        # with "expected exactly one user ..., found 5").
        self.assertIn('kget users -q "username=$1" -q exact=true', script)
        self.assertNotIn("set -x", script)

    def test_prefix_username_resolves_to_exactly_one_user(self):
        # Behavior regression (PostSync failure of 2026-11-04): a username that
        # is a prefix of others must still resolve to ONE user. The fake kcadm
        # below reproduces Keycloak's search: without exact=true a username
        # query returns every user whose name CONTAINS it (5 for
        # service-account-hermes-secretaria), with exact=true only the exact
        # match. A script that drops exact=true fails this audit run.
        import os
        import stat
        import subprocess
        import tempfile

        stub = """#!/bin/sh
ROLE=agentgateway-read:hindsight-personal
line="$*"
case "$line" in
  *"config credentials"*) exit 0 ;;
  *"roles/$ROLE/groups --fields path"*) exit 0 ;;
  *"roles/$ROLE/users -q first=0"*)
    printf 'e51253a7-c137-4c6c-9fb9-af9cecd3b147,me@e-dani.com\\n'
    printf '66ec6f4f-5f2c-44f6-a3db-0dccba6e1748,lays84.mv@gmail.com\\n'
    printf 'id-secretaria,service-account-hermes-secretaria\\n'
    printf 'id-casa,service-account-hermes-secretaria-casa\\n'
    exit 0 ;;
  *"roles/$ROLE --fields id"*) echo role-uuid; exit 0 ;;
  *"users/e51253a7-c137-4c6c-9fb9-af9cecd3b147/role-mappings/realm"*) echo "$ROLE"; exit 0 ;;
  *"users/66ec6f4f-5f2c-44f6-a3db-0dccba6e1748/role-mappings/realm"*) echo "$ROLE"; exit 0 ;;
  *"users/id-secretaria/role-mappings/realm"*) echo "$ROLE"; exit 0 ;;
  *"users/id-casa/role-mappings/realm"*) echo "$ROLE"; exit 0 ;;
  *"users/id-chat/role-mappings/realm"*) exit 0 ;;
  *"users/e51253a7-c137-4c6c-9fb9-af9cecd3b147 --fields username"*) echo me@e-dani.com; exit 0 ;;
  *"users/e51253a7-c137-4c6c-9fb9-af9cecd3b147 --fields enabled"*) echo true; exit 0 ;;
  *"users/e51253a7-c137-4c6c-9fb9-af9cecd3b147 --fields serviceAccountClientId"*) exit 0 ;;
  *"users/e51253a7-c137-4c6c-9fb9-af9cecd3b147 --fields id"*) echo e51253a7-c137-4c6c-9fb9-af9cecd3b147; exit 0 ;;
  *"users/66ec6f4f-5f2c-44f6-a3db-0dccba6e1748 --fields username"*) echo lays84.mv@gmail.com; exit 0 ;;
  *"users/66ec6f4f-5f2c-44f6-a3db-0dccba6e1748 --fields enabled"*) echo true; exit 0 ;;
  *"users/66ec6f4f-5f2c-44f6-a3db-0dccba6e1748 --fields serviceAccountClientId"*) exit 0 ;;
  *"users/66ec6f4f-5f2c-44f6-a3db-0dccba6e1748 --fields id"*) echo 66ec6f4f-5f2c-44f6-a3db-0dccba6e1748; exit 0 ;;
  *"get users -q username=service-account-hermes-secretaria-casa"*) echo id-casa; exit 0 ;;
  *"get users -q username=service-account-hermes-secretaria"*)
    case "$line" in
      *exact=true*) echo id-secretaria ;;
      *) printf 'id-secretaria\\nid-casa\\nid-studio\\nid-hogar\\nid-jarvis\\n' ;;
    esac
    exit 0 ;;
  *"get users -q username=service-account-chat-agentgateway"*) echo id-chat; exit 0 ;;
  *"get clients -q clientId=chat-agentgateway"*) echo chat-uuid; exit 0 ;;
  *"clients/chat-uuid/scope-mappings/realm"*) exit 0 ;;
esac
echo "fake kcadm: unexpected call: $line" >&2
exit 1
"""
        with tempfile.TemporaryDirectory() as tmp:
            kcadm = os.path.join(tmp, "kcadm")
            with open(kcadm, "w") as handle:
                handle.write(stub)
            os.chmod(kcadm, os.stat(kcadm).st_mode | stat.S_IXUSR)
            env = dict(
                os.environ,
                KCADM=kcadm,
                MODE="audit",
                KC_BOOTSTRAP_ADMIN_USERNAME="a",
                KC_BOOTSTRAP_ADMIN_PASSWORD="b",
            )
            proc = subprocess.run(
                ["/bin/sh", str(GRANTS_SCRIPT)],
                env=env, capture_output=True, text=True, timeout=60,
            )
        self.assertEqual(
            proc.returncode, 0,
            "audit failed with the prefix-colliding realm: " + proc.stderr,
        )
        self.assertIn('"holders_reviewed":4', proc.stdout)

    def test_manifest_is_a_hardened_postsync_job(self):
        manifest = GRANTS_JOB.read_text()
        self.assertNotIn("kind: ExternalSecret", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn('argocd.argoproj.io/sync-wave: "25"', manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn("name: ROLE_NAME, value: agentgateway-read:hindsight-personal", manifest)
        self.assertIn("name: CHAT_CLIENT_ID, value: chat-agentgateway", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        rollback = GRANTS_ROLLBACK.read_text()
        self.assertIn("value: rollback", rollback)


class WiringContractTest(unittest.TestCase):
    def test_kustomization_includes_both_reconcilers_and_excludes_rollbacks(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("agentgateway-chat-hindsight-mcp-client.yaml", kustomization)
        self.assertIn("agentgateway-hindsight-personal-grants-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-chat-hindsight-mcp-client.sh", kustomization)
        self.assertIn("scripts/agentgateway-hindsight-personal-grants.sh", kustomization)
        # the client script sources the reconcile library; the grants script
        # needs only the common bootstrap
        self.assertRegex(
            kustomization,
            r"keycloak-reconcile-lib\.sh=scripts/keycloak-reconcile-lib\.sh\n\s*options:\n\s*labels:\n\s*app\.kubernetes\.io/component: agentgateway-chat-hindsight-mcp-client",
        )
        # the wrapper execs the shared engine: the engine file must be mounted
        # in the hindsight ConfigMap too, next to the wrapper (#452 dedup)
        self.assertRegex(
            kustomization,
            r"keycloak-agentgateway-chat-hindsight-mcp-client\n\s*files:\n\s*-\s*agentgateway-chat-hindsight-mcp-client\.sh=\S+\n\s*-\s*agentgateway-chat-mcp-client\.sh=scripts/agentgateway-chat-mcp-client\.sh",
        )
        self.assertNotIn("manual/agentgateway-chat-hindsight-mcp-client-rollback-job.yaml", kustomization)
        self.assertNotIn("manual/agentgateway-hindsight-personal-grants-rollback-job.yaml", kustomization)


class CatalogDeclarationContractTest(unittest.TestCase):
    def test_roles_yaml_grantees_are_exactly_the_four_holders(self):
        catalog = json.loads((BASE / "ROLES.yaml").read_text())
        entry = {r["name"]: r for r in catalog["roles"]}[ROLE]
        self.assertEqual(set(entry["grantees"]), HOLDERS)
        self.assertNotIn(CHAT_SA, entry["grantees"])

    def test_principals_md_is_in_parity_with_the_catalog(self):
        principals = {
            p["username"]: p
            for p in kc_rbac.load_json_block(BASE / "PRINCIPALS.md")["principals"]
        }
        for holder in HOLDERS:
            self.assertIn(ROLE, principals[holder]["realm_roles"], holder)
        self.assertNotIn(ROLE, principals[CHAT_SA]["realm_roles"])

    def test_route_roles_matrix_has_the_chat_route(self):
        text = (BASE / "ROUTE-ROLES.md").read_text()
        matrix = kc_rbac.load_json_block(BASE / "ROUTE-ROLES.md")
        routes = {r["route"]: r for r in matrix["routes"]}
        self.assertIn("chat-hindsight-personal", routes)
        self.assertEqual(routes["chat-hindsight-personal"]["path"], "/chat-hindsight-personal")
        self.assertEqual(routes["chat-hindsight-personal"]["require"], [ROLE])
        self.assertIn("SC-4304 S6", text)


if __name__ == "__main__":
    unittest.main()
