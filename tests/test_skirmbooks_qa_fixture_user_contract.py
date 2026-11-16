"""SKIRM-494: contract of the Skirmbooks QA fixture user.

The reconciler skirmbooks-qa-fixture-user.sh owns EXACTLY ONE IdP fact — the
human test user qa@e-dani.com of realm edani: it exists, is enabled, holds the
password of its 1Password item (applied through the ExternalSecret
skirmbooks-qa-fixture-user-credentials) and is a member of /skirmbooks-users,
the only group oauth2-proxy-skirmbooks lets through (allowed_groups). The
group itself belongs to skirmbooks-sso.sh (wave 21): this hook refuses to
create it. The gestoria tenant role is NOT this hook's fact (migration 0096 of
skirmbooks-gestoria-src, applied: tenant skirmshop role owner).

Sister of test_agentgateway_write_fixture_user_contract.py (OWU-28-g): the
identity of the fixture is pinned (username, group, realm — never
environment-switchable), the password is redacted (never argv, never stdout —
it reaches kcadm only as the KC_CLI_PASSWORD environment of one call), the
membership write is followed by a post-read (SC-1215), the rollback removes
the membership and DISABLES the user (never deletes it), and the catalog
declarations (ROLES.yaml + PRINCIPALS.md) keep the drift sweep green.
Functional tests drive the real script against a fake kcadm through the
shared harness in tests/keycloak_hook_testlib.py.
"""

import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # unittest from the repo root
from keycloak_hook_testlib import (BASE, COMMON, ROOT, BootstrapSourceContractMixin,
                                   build_fake_kcadm, assert_job_hardened)

SCRIPT = BASE / "scripts" / "skirmbooks-qa-fixture-user.sh"
JOB = BASE / "skirmbooks-qa-fixture-user-job.yaml"

ITEM = "keycloak-next-qa"
ES_NAME = "skirmbooks-qa-fixture-user-credentials"
USERNAME = "qa@e-dani.com"
GROUP = "/skirmbooks-users"

FIRST_NAME = "QA"
LAST_NAME = "Fixture"

# A sentinel stands in for the real password: it must never surface in the
# fake kcadm journal (argv), stdout or stderr.
PASSWORD = "Sentinel-Password-9c1d7b-DoNotLog"

_GET = """\
        endpoint="$1"
        shift
        fields=""
        exact=""
        prev=""
        for a in "$@"; do
          [ "$prev" = "--fields" ] && fields="$a"
          case "$a" in username=*) exact="yes";; esac
          prev="$a"
        done
        case "$endpoint" in
          users)
            # exact-username resolution (the fixture id is minted, not pinned)
            if [ -n "$exact" ]; then
              if [ -f "$state/two-users" ]; then printf 'id-one\\nid-two\\n'; exit 0; fi
              if [ -f "$state/user-exists" ]; then printf 'fixture-user-id\\n'; fi
              exit 0
            fi
            exit 64
            ;;
          groups)
            if [ -f "$state/group-missing" ]; then exit 0; fi
            printf 'skirmbooks-users-gid,%s\\n' "$FAKE_GROUP"
            ;;
          users/*/groups)
            if [ -f "$state/group-member" ]; then printf '%s\\n' "$FAKE_GROUP"; fi
            ;;
          users/*)
            case "$fields" in
              id) printf '%s\\n' "${endpoint#users/}" ;;
              username) printf '%s\\n' "$FAKE_USERNAME" ;;
              enabled)
                if [ -f "$state/user-disabled" ]; then printf 'false\\n'
                else printf 'true\\n'; fi ;;
              serviceAccountClientId)
                if [ -f "$state/user-sa" ]; then printf 'some-client\\n'
                else printf '\\n'; fi ;;
              firstName)
                if [ -f "$state/user-firstname" ]; then cat "$state/user-firstname"
                else printf '\\n'; fi ;;
              lastName)
                if [ -f "$state/user-lastname" ]; then cat "$state/user-lastname"
                else printf '\\n'; fi ;;
              *) exit 63 ;;
            esac
            ;;
          *)
            exit 64
            ;;
        esac
        exit 0
"""

_WRITE_CASES = """\
      create)
        if [ "$1" != "users" ]; then exit 67; fi
        if [ -f "$state/create-fail" ]; then
          printf 'HTTP/1.1 400 Bad Request\\n'
          printf 'Error: User exists with same username\\n'
          exit 1
        fi
        touch "$state/user-exists"
        for a in "$@"; do
          case "$a" in
            firstName=*) printf '%s\\n' "${a#firstName=}" > "$state/user-firstname" ;;
            lastName=*) printf '%s\\n' "${a#lastName=}" > "$state/user-lastname" ;;
          esac
        done
        exit 0
        ;;
      set-password)
        # The password must arrive ONLY as the KC_CLI_PASSWORD environment
        # (kcadm 26's default for --new-password): an argv leak or a missing
        # environment fails here, loudly.
        for a in "$@"; do
          case "$a" in --new-password*|*"$FAKE_PASSWORD"*) exit 70 ;; esac
        done
        if [ -z "${KC_CLI_PASSWORD:-}" ]; then exit 71; fi
        if [ "${KC_CLI_PASSWORD:-}" != "$FAKE_PASSWORD" ]; then exit 72; fi
        touch "$state/password-applied"
        exit 0
        ;;
      update)
        endpoint="$1"
        shift
        case "$endpoint" in
          users/*/groups/*)
            if [ -f "$state/membership-fail" ]; then
              printf 'HTTP/1.1 404 Not Found\\n'
              printf 'Error: group not found\\n'
              exit 1
            fi
            # membership-silent-noop: the server answers 0 and writes nothing,
            # so the post-ensure read must catch it (SC-1215).
            [ -f "$state/membership-silent-noop" ] || touch "$state/group-member"
            exit 0
            ;;
          users/*)
            for a in "$@"; do
              case "$a" in
                enabled=true) rm -f "$state/user-disabled" ;;
                enabled=false) touch "$state/user-disabled" ;;
                firstName=*)
                  [ -f "$state/profile-silent-noop" ] || printf '%s\\n' "${a#firstName=}" > "$state/user-firstname" ;;
                lastName=*)
                  [ -f "$state/profile-silent-noop" ] || printf '%s\\n' "${a#lastName=}" > "$state/user-lastname" ;;
              esac
            done
            exit 0
            ;;
          *) exit 68 ;;
        esac
        ;;
      delete)
        endpoint="$1"
        case "$endpoint" in
          users/*/groups/*) rm -f "$state/group-member" ;;
          *) exit 69 ;;
        esac
        exit 0
        ;;
"""

FAKE_KCADM = build_fake_kcadm("        exit 0\n", _GET, _WRITE_CASES)


def run_reconciler(mode="ensure", fixtures=None, extra_env=None):
    from keycloak_hook_testlib import run_hook
    env = {"FIXTURE_PASSWORD": PASSWORD, "FAKE_USERNAME": USERNAME,
           "FAKE_PASSWORD": PASSWORD, "FAKE_GROUP": GROUP}
    env.update(extra_env or {})
    return run_hook(SCRIPT, FAKE_KCADM, mode=mode, fixtures=fixtures, extra_env=env)


class SkirmbooksQaFixtureFunctionalTest(unittest.TestCase):
    def test_ensure_creates_the_user_then_applies_password_and_grants_membership(self):
        result, journal, state = run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"created":true', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("create users", journal)
        self.assertIn("set-password", journal)
        self.assertIn("update users/fixture-user-id/groups/skirmbooks-users-gid", journal)
        self.assertIn("group-member", state)
        # The membership write is followed by a re-read (SC-1215 post-assertion).
        self.assertGreater(
            journal.rindex("get users/fixture-user-id/groups"),
            journal.index("update users/fixture-user-id/groups"),
        )

    def test_ensure_sets_the_profile_names_when_creating_the_user(self):
        # OWU-76: a user without firstName/lastName is sent to Update Account
        # Information at login. The names are part of the create itself.
        result, journal, state = run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        create_line = next(l for l in journal.splitlines() if l.startswith("create users"))
        self.assertIn(f"firstName={FIRST_NAME}", create_line)
        self.assertIn(f"lastName={LAST_NAME}", create_line)
        self.assertIn("requiredActions=[]", create_line)
        self.assertIn("emailVerified=true", create_line)

    def test_ensure_is_a_noop_on_a_complete_fixture(self):
        result, journal, state = run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "group-member": "1",
                      "user-firstname": FIRST_NAME + "\n",
                      "user-lastname": LAST_NAME + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"created":false', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("create users", journal)
        self.assertNotIn("update users/fixture-user-id/groups", journal)
        # The password is re-applied on every sync (Keycloak == 1Password).
        self.assertIn("set-password", journal)

    def test_ensure_grants_membership_when_missing(self):
        result, journal, state = run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "user-firstname": FIRST_NAME + "\n",
                      "user-lastname": LAST_NAME + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("update users/fixture-user-id/groups/skirmbooks-users-gid", journal)
        self.assertIn("group-member", state)

    def test_ensure_post_assertion_fails_when_the_membership_write_silently_noops(self):
        # SC-1215: a 0-exit write that did not land must be caught by the
        # post-ensure read, not reported as granted.
        result, _, state = run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "membership-silent-noop": "1",
                      "user-firstname": FIRST_NAME + "\n",
                      "user-lastname": LAST_NAME + "\n"},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("post-ensure assertion failed", result.stderr)
        self.assertNotIn("group-member", state)

    def test_ensure_surfaces_server_reply_on_membership_write_failure(self):
        result, _, _ = run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "membership-fail": "1",
                      "user-firstname": FIRST_NAME + "\n",
                      "user-lastname": LAST_NAME + "\n"},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("server replied", result.stderr)

    def test_ensure_refuses_to_create_the_group_owned_by_skirmbooks_sso(self):
        # The group is skirmbooks-sso.sh's fact (wave 21): missing here means
        # the trunk moved — fail loud, never create it from this hook.
        result, journal, _ = run_reconciler("ensure", fixtures={"group-missing": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("owned by skirmbooks-sso.sh", result.stderr)
        self.assertNotIn("create groups", journal)

    def test_ensure_fails_before_any_mutation_without_the_password(self):
        result, journal, _ = run_reconciler("ensure", extra_env={"FIXTURE_PASSWORD": ""})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FIXTURE_PASSWORD is empty", result.stderr)
        self.assertNotIn("create users", journal)
        self.assertNotIn("update", journal)

    def test_ensure_fails_closed_when_the_username_is_ambiguous(self):
        # Two users with the exact username is a realm the contract does not
        # describe: it must never be mistaken for "absent" (which would
        # create a user).
        result, journal, _ = run_reconciler("ensure", fixtures={"two-users": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("does not resolve to at most one user", result.stderr)
        self.assertNotIn("create users", journal)

    def test_password_never_reaches_argv_stdout_or_stderr(self):
        result, journal, _ = run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(PASSWORD, journal)
        self.assertNotIn(PASSWORD, result.stdout)
        self.assertNotIn(PASSWORD, result.stderr)

    def test_audit_passes_on_a_complete_fixture(self):
        result, journal, _ = run_reconciler(
            "audit",
            fixtures={"user-exists": "1", "group-member": "1",
                      "user-firstname": FIRST_NAME + "\n",
                      "user-lastname": LAST_NAME + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        # Audit mutates nothing.
        self.assertNotIn("create", journal)
        self.assertNotIn("update", journal)
        self.assertNotIn("set-password", journal)

    def test_audit_fails_when_the_membership_is_missing(self):
        result, _, _ = run_reconciler(
            "audit",
            fixtures={"user-exists": "1", "user-firstname": FIRST_NAME + "\n",
                      "user-lastname": LAST_NAME + "\n"},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("is not a member of " + GROUP, result.stderr)

    def test_rollback_removes_membership_and_disables_never_deletes(self):
        result, journal, state = run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "group-member": "1",
                      "user-firstname": FIRST_NAME + "\n",
                      "user-lastname": LAST_NAME + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        # Re-run as rollback against the state the ensure left is not what the
        # harness does (fresh tmp per run), so drive rollback directly:
        result, journal, state = run_reconciler(
            "rollback",
            fixtures={"user-exists": "1", "group-member": "1",
                      "user-firstname": FIRST_NAME + "\n",
                      "user-lastname": LAST_NAME + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("delete users/fixture-user-id/groups/skirmbooks-users-gid", journal)
        self.assertNotIn("group-member", state)
        self.assertIn("user-disabled", state)
        self.assertNotIn("remove users", journal)  # never deletes the principal

    def test_rollback_is_idempotent_on_an_absent_user(self):
        result, journal, _ = run_reconciler("rollback")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertNotIn("create", journal)


class SkirmbooksQaFixtureStaticTest(BootstrapSourceContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT

    def test_script_pins_its_identity(self):
        code = SCRIPT.read_text()
        self.assertIn('[ "${USERNAME}" = "qa@e-dani.com" ]', code)
        self.assertIn('[ "${USER_GROUP}" = "/skirmbooks-users" ]', code)
        self.assertIn('[ "${REALM}" = "edani" ]', code)

    def test_job_manifest_is_hardened(self):
        assert_job_hardened(self, JOB.read_text())

    def test_job_wires_the_group_and_the_password_secret(self):
        manifest = JOB.read_text()
        self.assertIn("value: /skirmbooks-users", manifest)
        self.assertIn("value: qa@e-dani.com", manifest)
        self.assertIn("name: " + ES_NAME, manifest)
        self.assertIn("key: FIXTURE_PASSWORD", manifest)

    def test_external_secret_reads_the_onepassword_item(self):
        manifest = JOB.read_text()
        self.assertIn("name: " + ES_NAME, manifest)
        self.assertIn(f"key: {ITEM}/password", manifest)
        self.assertIn("refreshPolicy: OnChange", manifest)
        self.assertIn("kind: ClusterSecretStore", manifest)

    def test_kustomization_registers_the_resource_and_the_configmap(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("skirmbooks-qa-fixture-user-job.yaml", kustomization)
        self.assertIn("name: keycloak-skirmbooks-qa-fixture-user", kustomization)
        self.assertIn(
            "skirmbooks-qa-fixture-user.sh=scripts/skirmbooks-qa-fixture-user.sh",
            kustomization,
        )
        self.assertIn("kc-admin-common.sh=scripts/kc-admin-common.sh", kustomization)

    def test_catalog_declarations_keep_the_drift_sweep_green(self):
        # The same facts tests/test_keycloak_rbac_grant_declaration_contract.py
        # enforces from the manifest: the grantee is declared in PRINCIPALS.md
        # and in the grantees of default-roles-edani in ROLES.yaml.
        principals = (BASE / "PRINCIPALS.md").read_text()
        self.assertIn('"username": "qa@e-dani.com"', principals)
        roles = json.loads((BASE / "ROLES.yaml").read_text())
        default = next(r for r in roles["roles"] if r["name"] == "default-roles-edani")
        self.assertIn(USERNAME, default["grantees"])


if __name__ == "__main__":
    unittest.main()
