"""INFRA-250 (INFRA-219 P4): contract of the keycloak-rbac-auditor reconciler.

The PostSync script runs against a fake kcadm (POSIX sh, state in a temp
directory): no Keycloak, no image, no network. The fake models the realm
objects the script touches — the client, its realm-management role scope,
the service account's direct/effective/other-client/realm grants and groups,
the minted token, and the two live probes made with the auditor's token —
so every fail-closed branch is exercised, and an extra role anywhere must
fail the job without the job removing anything.
"""

import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "keycloak-rbac-auditor-client.sh"
MANIFEST = BASE / "keycloak-rbac-auditor-client.yaml"
KUSTOMIZATION = BASE / "kustomization.yaml"
CI = ROOT / ".github" / "workflows" / "ci.yml"

EXPECTED = ["query-groups", "query-users", "view-realm", "view-users"]
SECRET = "fake-auditor-secret-not-real-0123456789"

FAKE_KCADM = textwrap.dedent(
    r"""
    #!/bin/sh
    command="$1"
    shift
    state="$FAKE_STATE"
    printf '%s %s\n' "$command" "$*" >>"$FAKE_JOURNAL"

    config=""
    prev=""
    body=""
    fields=""
    query=""
    client=""
    uid=""
    cclientid=""
    rolename=""
    for a in "$@"; do
      case "$prev" in
        --config) config="$a" ;;
        -b) body="$a" ;;
        --fields) fields="$a" ;;
        --client) client="$a" ;;
        --uid) uid="$a" ;;
        --cclientid) cclientid="$a" ;;
        --rolename) rolename="$a" ;;
      esac
      case "$a" in clientId=*) query="$a" ;; esac
      prev="$a"
    done

    as_auditor=false
    case "$config" in *client.config) as_auditor=true ;; esac

    token() {
      roles=""
      if [ -f "$state/scope" ] && [ -f "$state/sa-roles" ]; then
        roles="$(sort -u "$state/scope" | while read -r r; do
          grep -Fxq "$r" "$state/sa-roles" && printf '"%s",' "$r"; done | sed 's/,$//')"
      fi
      json="$(printf '{"azp":"%s","resource_access":{"realm-management":{"roles":[%s]}}%s}' \
        "${FAKE_AZP:-keycloak-rbac-auditor}" "$roles" "${FAKE_TOKEN_EXTRA:-}")"
      payload="$(printf '%s' "$json" | base64 | tr -d '\n=' | tr '/+' '_-')"
      printf 'eyJhbGciOiJub25lIn0.%s.sig' "$payload"
    }

    if [ "$command" = config ]; then
      if [ -n "$client" ]; then
        [ -f "$state/client" ] || exit 71
        printf '{"token" : "%s"}\n' "$(token)" >"$config"
      else
        printf '{"admin":true}\n' >"$config"
      fi
      exit 0
    fi

    if $as_auditor; then
      endpoint="$1"
      case "$command:$endpoint" in
        get:roles|get:users) printf '[]\n'; exit 0 ;;
        get:clients/*/client-secret)
          if [ -n "${FAKE_ALLOW_SECRET:-}" ]; then printf '{"value":"leak"}\n'; exit 0; fi
          printf 'HTTP error - 403 Forbidden\n' >&2; exit 1 ;;
        create:users/*/role-mappings/realm)
          if [ -n "${FAKE_ALLOW_MAPPING:-}" ]; then exit 0; fi
          printf 'HTTP error - 403 Forbidden\n' >&2; exit 1 ;;
        *) exit 72 ;;
      esac
    fi

    name_from_body() {
      printf '%s' "$body" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p'
    }

    case "$command" in
      get)
        endpoint="$1"
        case "$endpoint" in
          clients)
            case "$query" in
              clientId=keycloak-rbac-auditor) [ -f "$state/client" ] && printf 'aud-uuid\n' ;;
              clientId=realm-management) printf 'rm-uuid\n' ;;
              *) exit 62 ;;
            esac
            exit 0 ;;
          clients/aud-uuid)
            if [ -f "$state/field-$fields" ]; then cat "$state/field-$fields"; exit 0; fi
            case "$fields" in
              enabled|serviceAccountsEnabled) printf 'true\n' ;;
              publicClient|standardFlowEnabled|implicitFlowEnabled|directAccessGrantsEnabled|fullScopeAllowed) printf 'false\n' ;;
              *) exit 63 ;;
            esac
            exit 0 ;;
          clients/rm-uuid/roles/*) printf 'id-%s\n' "${endpoint##*/}"; exit 0 ;;
          clients/aud-uuid/scope-mappings/clients/rm-uuid) cat "$state/scope" 2>/dev/null; exit 0 ;;
          clients/aud-uuid/scope-mappings/realm) cat "$state/realm-scope" 2>/dev/null; exit 0 ;;
          clients/aud-uuid/service-account-user)
            case "$fields" in
              id) printf 'aud-sa\n' ;;
              username) printf 'service-account-keycloak-rbac-auditor\n' ;;
            esac
            exit 0 ;;
          users/aud-sa/role-mappings/clients/rm-uuid) cat "$state/sa-roles" 2>/dev/null; exit 0 ;;
          users/aud-sa/role-mappings/clients/rm-uuid/composite)
            cat "$state/sa-roles" "$state/sa-composite-extra" 2>/dev/null; exit 0 ;;
          users/aud-sa/role-mappings)
            printf '{\n  "realmMappings" : [ ],\n  "clientMappings" : {\n'
            if [ -s "$state/sa-roles" ]; then
              printf '    "realm-management" : {\n      "id" : "rm-uuid",\n      "client" : "realm-management",\n      "mappings" : [ ]\n    },\n'
            fi
            if [ -f "$state/sa-other-clients" ]; then
              while read -r c; do
                printf '    "%s" : {\n      "id" : "x",\n      "client" : "%s",\n      "mappings" : [ ]\n    },\n' "$c" "$c"
              done <"$state/sa-other-clients"
            fi
            printf '  }\n}\n'
            exit 0 ;;
          users/aud-sa/role-mappings/realm) cat "$state/sa-realm" 2>/dev/null; exit 0 ;;
          users/aud-sa/groups)
            [ -z "${FAKE_FAIL_GROUPS:-}" ] || exit 64
            cat "$state/sa-groups" 2>/dev/null; exit 0 ;;
          *) exit 65 ;;
        esac
        ;;
      create)
        endpoint="$1"
        case "$endpoint" in
          clients) : >"$state/client"; printf 'default-roles-edani\n' >"$state/sa-realm"; exit 0 ;;
          clients/aud-uuid/scope-mappings/clients/rm-uuid) name_from_body >>"$state/scope"; printf '\n' >>"$state/scope"; exit 0 ;;
          *) exit 66 ;;
        esac
        ;;
      update)
        [ "$1" = clients/aud-uuid ] || exit 67
        exit 0 ;;
      add-roles)
        [ "$uid" = aud-sa ] && [ "$cclientid" = realm-management ] || exit 68
        printf '%s\n' "$rolename" >>"$state/sa-roles"
        exit 0 ;;
      *) exit 69 ;;
    esac
    """
).lstrip()


class AuditorReconcilerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        self.state = tmp / "state"
        self.state.mkdir()
        self.journal = tmp / "journal"
        self.kcadm = tmp / "kcadm.sh"
        self.kcadm.write_text(FAKE_KCADM)
        self.kcadm.chmod(0o755)

    def tearDown(self):
        self._tmp.cleanup()

    def existing_auditor(self, roles=EXPECTED, scope=EXPECTED):
        (self.state / "client").write_text("")
        (self.state / "sa-realm").write_text("default-roles-edani\n")
        (self.state / "sa-roles").write_text("".join(f"{r}\n" for r in roles))
        (self.state / "scope").write_text("".join(f"{r}\n" for r in scope))

    def run_script(self, mode="ensure", **overrides):
        env = {
            "PATH": os.environ["PATH"],
            "KCADM": str(self.kcadm),
            "FAKE_STATE": str(self.state),
            "FAKE_JOURNAL": str(self.journal),
            "MODE": mode,
            "KC_BOOTSTRAP_ADMIN_USERNAME": "admin",
            "KC_BOOTSTRAP_ADMIN_PASSWORD": "fake-admin-password",
            "KEYCLOAK_RBAC_AUDITOR_CLIENT_SECRET": SECRET,
        }
        env.update(overrides)
        result = subprocess.run(["sh", str(SCRIPT)], env=env, text=True, capture_output=True, timeout=60)
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        return result

    def journal_lines(self):
        return self.journal.read_text().splitlines() if self.journal.exists() else []

    def assert_fails(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stderr)
        # Fail-closed never means "fix by removing": nothing is deleted.
        self.assertFalse([line for line in self.journal_lines() if line.startswith(("delete", "remove-roles"))])

    def test_fresh_realm_gets_exactly_the_four_roles(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"exact":true', result.stdout)
        self.assertIn('"probe":"read-client-secret","denied":true,"status":"403"', result.stdout)
        self.assertIn('"probe":"post-role-mapping","denied":true,"status":"403"', result.stdout)
        journal = self.journal_lines()
        granted = sorted(line.rsplit("--rolename ", 1)[1] for line in journal if line.startswith("add-roles"))
        self.assertEqual(granted, EXPECTED)
        scoped = sorted((self.state / "scope").read_text().split())
        self.assertEqual(scoped, EXPECTED)
        created = [line for line in journal if line.startswith("create clients ")]
        self.assertEqual(len(created), 1)
        for flag in ("serviceAccountsEnabled=true", "publicClient=false", "standardFlowEnabled=false",
                     "implicitFlowEnabled=false", "directAccessGrantsEnabled=false", "fullScopeAllowed=false"):
            self.assertIn(flag, created[0])
        self.assertFalse([line for line in journal if "view-clients" in line or "manage-" in line])
        # The role-mapping probe carries an empty body: a success would change nothing.
        self.assertTrue([line for line in journal if line.startswith("create users/aud-sa/role-mappings/realm -b []")])

    def test_rerun_is_idempotent(self):
        self.existing_auditor()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        journal = self.journal_lines()
        self.assertFalse([line for line in journal if line.startswith("add-roles")])
        self.assertFalse([line for line in journal if line.startswith("create clients")])
        self.assertTrue([line for line in journal if line.startswith("update clients/aud-uuid")])

    def test_audit_mode_changes_nothing_and_needs_the_client(self):
        result = self.run_script(mode="audit")
        self.assert_fails(result, "client keycloak-rbac-auditor is missing")
        self.existing_auditor()
        self.journal.unlink()
        result = self.run_script(mode="audit")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse([line for line in self.journal_lines() if line.startswith(("create clients", "update", "add-roles"))])

    def test_extra_direct_management_role_fails(self):
        self.existing_auditor(roles=EXPECTED + ["view-clients"])
        self.assert_fails(self.run_script(), "service account realm-management roles are not exactly")

    def test_extra_effective_role_through_a_composite_fails(self):
        self.existing_auditor()
        (self.state / "sa-composite-extra").write_text("query-clients\n")
        self.assert_fails(self.run_script(), "effective realm-management roles are not exactly")

    def test_extra_scope_role_fails(self):
        self.existing_auditor(scope=EXPECTED + ["manage-users"])
        self.assert_fails(self.run_script(), "role scope is not exactly")

    def test_realm_role_scope_must_be_empty(self):
        self.existing_auditor()
        (self.state / "realm-scope").write_text("agentgateway-write\n")
        self.assert_fails(self.run_script(), "client realm role scope must be empty")

    def test_role_of_another_client_fails(self):
        self.existing_auditor()
        (self.state / "sa-other-clients").write_text("broker\n")
        self.assert_fails(self.run_script(), "roles of a client other than realm-management")

    def test_extra_realm_role_on_the_service_account_fails(self):
        self.existing_auditor()
        (self.state / "sa-realm").write_text("default-roles-edani\nagentgateway-write\n")
        self.assert_fails(self.run_script(), "service account realm roles are not exactly default-roles-edani")

    def test_group_membership_fails_and_a_failed_read_is_not_empty(self):
        self.existing_auditor()
        (self.state / "sa-groups").write_text("group-uuid\n")
        self.assert_fails(self.run_script(), "must not belong to any group")
        (self.state / "sa-groups").unlink()
        self.assert_fails(self.run_script(FAKE_FAIL_GROUPS="1"), "cannot read the service account groups")

    def test_full_scope_allowed_fails(self):
        self.existing_auditor()
        (self.state / "field-fullScopeAllowed").write_text("true\n")
        self.assert_fails(self.run_script(), "client field fullScopeAllowed expected false")

    def test_minted_token_is_exact(self):
        self.existing_auditor()
        self.assert_fails(self.run_script(FAKE_TOKEN_EXTRA=',"realm_access":{"roles":["default-roles-edani"]}'),
                          "minted token carries realm roles")
        self.assert_fails(self.run_script(FAKE_TOKEN_EXTRA=',"account":{"roles":["manage-account"]}'),
                          "roles of more than one client")
        self.assert_fails(self.run_script(FAKE_AZP="other"), "minted token has wrong azp")

    def test_auditor_token_must_be_denied_the_secret_and_role_mappings(self):
        self.existing_auditor()
        self.assert_fails(self.run_script(FAKE_ALLOW_SECRET="1"), "auditor token was allowed to read-client-secret")
        self.assert_fails(self.run_script(FAKE_ALLOW_MAPPING="1"), "auditor token was allowed to post-role-mapping")

    def test_identity_and_privilege_are_immutable(self):
        self.assert_fails(self.run_script(KEYCLOAK_RBAC_AUDITOR_CLIENT_SECRET=""), "client secret is empty")
        self.assert_fails(self.run_script(EXPECTED_MANAGEMENT_ROLES="query-groups,query-users,view-clients,view-realm,view-users"),
                          "EXPECTED_MANAGEMENT_ROLES is immutable")
        self.assert_fails(self.run_script(CLIENT_ID="agentgateway-mcp"), "CLIENT_ID is immutable")
        self.assert_fails(self.run_script(MODE="rollback"), "unsupported MODE")


class AuditorManifestContractTest(unittest.TestCase):
    def test_script_never_prints_the_secret_and_pins_the_role_set(self):
        script = SCRIPT.read_text()
        self.assertIn('EXPECTED_MANAGEMENT_ROLES="${EXPECTED_MANAGEMENT_ROLES:-query-groups,query-users,view-realm,view-users}"', script)
        self.assertIn('CLIENT_SECRET="${KEYCLOAK_RBAC_AUDITOR_CLIENT_SECRET:-}"', script)
        self.assertIn("-s fullScopeAllowed=false", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${CLIENT_SECRET}"', script)
        self.assertNotIn('printf \'%s\' "${CLIENT_SECRET}"', script)
        for verb in ('"${KCADM}" delete', "remove-roles"):
            self.assertNotIn(verb, script)

    def test_manifest_reads_its_own_1password_item_and_is_a_hardened_postsync(self):
        manifest = MANIFEST.read_text()
        self.assertEqual(manifest.count("kind: ExternalSecret"), 1)
        self.assertIn("key: keycloak-rbac-auditor/password", manifest)
        self.assertIn("name: onepassword", manifest)
        self.assertIn("client_id: keycloak-rbac-auditor", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("argocd.argoproj.io/hook-delete-policy: BeforeHookCreation", manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn('value: "query-groups,query-users,view-realm,view-users"', manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("node-pool: ks5-nvme", manifest)
        self.assertRegex(manifest, r"quay\.io/keycloak/keycloak:26\.6\.2@sha256:[0-9a-f]{64}")
        for node in ("nvidia-dgx", "gx10-ec3d"):
            self.assertNotIn(node, manifest)

    def test_wired_into_kustomize_and_ci(self):
        kustomization = KUSTOMIZATION.read_text()
        self.assertIn("  - keycloak-rbac-auditor-client.yaml\n", kustomization)
        self.assertIn("keycloak-rbac-auditor-client.sh=scripts/keycloak-rbac-auditor-client.sh", kustomization)
        ci = CI.read_text()
        self.assertIn("sh -n platform/keycloak-next/scripts/keycloak-rbac-auditor-client.sh", ci)
        self.assertIn("python3 -m unittest discover -s tests -p 'test_keycloak_rbac_*.py'", ci)


if __name__ == "__main__":
    unittest.main()
