"""OWU-28 historia g: contract of the reverse C2 fixture user.

The reconciler agentgateway-write-fixture-user.sh owns EXACTLY ONE IdP fact —
the human test user qa-write-sin-vinculo@e-dani.com of realm edani: it
exists, is enabled, holds the password of its 1Password item (applied through
the ExternalSecret agentgateway-write-fixture-user-credentials), holds the
realm role agentgateway-write, belongs to no group and is not a service
account. Its Atlassian negative is by construction (no entry in
atlassian-identity-bindings, fail-closed by absence in the agentgateway
shim), so nothing here touches that repo.

Unlike the OWU-80 Daniel grant this hook CREATES the user (the id is minted
by Keycloak, so resolution is by EXACT username) and RE-APPLIES the password
on every sync (SC-1635/SC-1645: Keycloak must never drift from 1Password).
These tests pin the identity of the fixture, the password redaction (never
argv, never stdout — it reaches kcadm only as the KC_CLI_PASSWORD environment
of one call), the no-groups / no-service-account assertions, the wave
ordering (25 after the role hook's 20), the rollback scope (remove role +
disable, never delete), the ES/Job/kustomization wiring and the catalog
declarations (ROLES.yaml + PRINCIPALS.md) that keep the drift sweep green.
Functional tests drive the real script against a fake kcadm; the exclusivity
side reuses the harness of tests/test_agentgateway_write_grant_daniel_contract.py.
"""

import json
import os
import pathlib
import re
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "agentgateway-write-fixture-user.sh"
JOB = BASE / "agentgateway-write-fixture-user-job.yaml"
ROLLBACK_JOB = BASE / "manual" / "agentgateway-write-fixture-user-rollback-job.yaml"

FIXTURE = "qa-write-sin-vinculo@e-dani.com"
ROLE = "agentgateway-write"
SA = "service-account-agentgateway-mcp"
ITEM = "keycloak-next-qa-write-sin-vinculo"
ES_NAME = "agentgateway-write-fixture-user-credentials"

# The reconciler runs inside the pinned Keycloak image, which ships no awk
# (SC-1215). Only these externals may be invoked.
IMAGE_SAFE_EXTERNS = ("kcadm", "sed", "grep", "tr", "wc", "rm", "sleep")

# A sentinel stands in for the real password: it must never surface in the
# fake kcadm journal (argv), stdout or stderr.
PASSWORD = "Sentinel-Password-4f2e9a-DoNotLog"

FAKE_KCADM = textwrap.dedent(
    """\
    #!/bin/sh
    command="$1"
    shift
    state="$FAKE_STATE"
    journal="$FAKE_JOURNAL"
    printf '%s %s\\n' "$command" "$*" >>"$journal"

    case "$command" in
      config)
        exit 0
        ;;
      get)
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
          users/*/role-mappings/realm)
            if [ -f "$state/user-roles" ]; then cat "$state/user-roles"; fi
            ;;
          users/*/groups)
            if [ -f "$state/user-groups" ]; then cat "$state/user-groups"; fi
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
              *) exit 63 ;;
            esac
            ;;
          roles/*)
            if [ -f "$state/role-missing" ]; then exit 1; fi
            printf 'role-uuid\\n'
            ;;
          *)
            exit 64
            ;;
        esac
        exit 0
        ;;
      create)
        # create users …: the fixture hook is the ONLY reconciler of this
        # platform that creates users.
        if [ "$1" != "users" ]; then exit 67; fi
        if [ -f "$state/create-fail" ]; then
          printf 'HTTP/1.1 400 Bad Request\\n'
          printf 'Error: User exists with same username\\n'
          exit 1
        fi
        touch "$state/user-exists"
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
        for a in "$@"; do
          case "$a" in
            enabled=true) rm -f "$state/user-disabled" ;;
            enabled=false) touch "$state/user-disabled" ;;
          esac
        done
        exit 0
        ;;
      add-roles|remove-roles)
        uid=""; rolename=""; prev=""
        for a in "$@"; do
          [ "$prev" = "--uid" ] && uid="$a"
          [ "$prev" = "--rolename" ] && rolename="$a"
          prev="$a"
        done
        [ "$uid" = "fixture-user-id" ] || exit 65
        if [ "$command" = add-roles ]; then
          if [ -f "$state/addroles-fail" ]; then
            printf 'HTTP/1.1 400 Bad Request\\n'
            printf 'Error: unknown role %s\\n' "$rolename"
            exit 1
          fi
          if [ ! -f "$state/addroles-silent-noop" ]; then
            touch "$state/user-roles"
            printf '%s\\n' "$rolename" >> "$state/user-roles"
          fi
        else
          if [ -f "$state/user-roles" ]; then
            grep -Fxv "$rolename" "$state/user-roles" > "$state/user-roles.tmp" || true
            mv "$state/user-roles.tmp" "$state/user-roles"
          fi
        fi
        exit 0
        ;;
      *)
        exit 66
        ;;
    esac
    """
)


def _code(script_text):
    """Executable lines only (comments dropped): the comments name the very
    binaries and flags the contract forbids, to explain why."""
    return "\n".join(
        line for line in script_text.splitlines() if not line.lstrip().startswith("#")
    )


class WriteFixtureUserFunctionalTest(unittest.TestCase):
    def run_reconciler(self, mode="ensure", fixtures=None, extra_env=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            state = tmp_path / "state"
            state.mkdir()
            journal = tmp_path / "journal"
            journal.touch()
            fake_kcadm = tmp_path / "kcadm.sh"
            fake_kcadm.write_text(FAKE_KCADM)
            fake_kcadm.chmod(0o755)
            for name, content in (fixtures or {}).items():
                (state / name).write_text(content)
            env = os.environ.copy()
            env.update(
                {
                    "MODE": mode,
                    "KCADM": str(fake_kcadm),
                    "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-a-real-secret",
                    "FIXTURE_PASSWORD": PASSWORD,
                    "FAKE_STATE": str(state),
                    "FAKE_JOURNAL": str(journal),
                    "FAKE_USERNAME": FIXTURE,
                    "FAKE_PASSWORD": PASSWORD,
                }
            )
            if extra_env:
                env.update(extra_env)
            result = subprocess.run(
                ["/bin/sh", str(SCRIPT)], capture_output=True, text=True, env=env
            )
            state_files = {p.name: p.read_text() for p in sorted(state.iterdir())}
            return result, journal.read_text(), state_files

    # ---- ensure -------------------------------------------------------

    def test_ensure_creates_the_user_then_applies_password_and_grants_role(self):
        result, journal, state = self.run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"created":true', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("create users", journal)
        self.assertIn("set-password", journal)
        self.assertIn("--uid fixture-user-id --rolename " + ROLE, journal)
        self.assertIn(ROLE, state.get("user-roles", ""))
        self.assertIn("password-applied", state)
        # The role write is followed by a re-read (SC-1215 post-assertion).
        self.assertGreater(
            journal.rindex("role-mappings/realm"), journal.index("add-roles")
        )

    def test_ensure_is_idempotent_but_still_reapplies_the_password(self):
        # SC-1635/SC-1645: the password is re-applied on every sync so
        # Keycloak cannot drift from 1Password; creation and the grant are
        # skipped when already present.
        result, journal, state = self.run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "user-roles": ROLE + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"created":false', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("create users", journal)
        self.assertNotIn("add-roles", journal)
        self.assertIn("set-password", journal)
        self.assertIn("password-applied", state)

    def test_ensure_reenables_a_disabled_user(self):
        result, journal, state = self.run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "user-disabled": "1", "user-roles": ROLE + "\n"},
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("enabled=true", journal)
        self.assertNotIn("user-disabled", state)

    def test_ensure_never_leaks_the_password_into_argv_or_output(self):
        result, journal, _ = self.run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(PASSWORD, journal)
        self.assertNotIn(PASSWORD, result.stdout)
        self.assertNotIn(PASSWORD, result.stderr)
        self.assertNotIn("--new-password", journal)

    def test_ensure_fails_before_any_mutation_without_the_credential(self):
        result, journal, _ = self.run_reconciler(
            "ensure", extra_env={"FIXTURE_PASSWORD": ""}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FIXTURE_PASSWORD is empty", result.stderr)
        self.assertNotIn("create users", journal)
        self.assertNotIn("set-password", journal)
        self.assertNotIn("add-roles", journal)

    def test_ensure_never_creates_the_role(self):
        result, journal, _ = self.run_reconciler("ensure", fixtures={"role-missing": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to create it here", result.stderr)
        self.assertNotIn("create users", journal)

    def test_ensure_fails_when_the_username_is_a_service_account(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-exists": "1", "user-sa": "1"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("service account", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_fails_when_the_fixture_has_groups(self):
        # The reverse C2 negative isolates ONE variable: write WITHOUT the
        # Atlassian binding. Groups would mix fixtures — refused.
        result, journal, _ = self.run_reconciler(
            "ensure",
            fixtures={"user-exists": "1", "user-groups": "/edani-operators\n"},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("no groups", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_surfaces_server_reply_on_create_failure(self):
        result, _, _ = self.run_reconciler("ensure", fixtures={"create-fail": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("server replied", result.stderr)

    def test_ensure_fails_when_the_exact_username_is_ambiguous(self):
        # An exact search answering with two users is a realm the contract
        # does not describe: fail closed, never pick one, never create.
        result, journal, _ = self.run_reconciler("ensure", fixtures={"two-users": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("does not resolve", result.stderr)
        self.assertNotIn("create users", journal)

    def test_ensure_post_assertion_fails_when_the_write_silently_noops(self):
        # SC-1215 lesson: kcadm can swallow server answers.
        result, _, state = self.run_reconciler(
            "ensure", fixtures={"user-exists": "1", "addroles-silent-noop": "1"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("post-ensure assertion failed", result.stderr)
        self.assertNotIn(ROLE, state.get("user-roles", ""))

    # ---- audit / rollback ---------------------------------------------

    def test_audit_passes_when_present_and_fails_when_absent(self):
        ok, _, _ = self.run_reconciler(
            "audit", fixtures={"user-exists": "1", "user-roles": ROLE + "\n"}
        )
        self.assertEqual(0, ok.returncode, ok.stderr)
        self.assertIn('"present":true', ok.stdout)
        bad, journal, _ = self.run_reconciler("audit")
        self.assertNotEqual(0, bad.returncode)
        self.assertIn("audit:", bad.stderr)
        self.assertNotIn("create users", journal)
        self.assertNotIn("add-roles", journal)

    def test_rollback_removes_the_role_and_disables_without_deleting(self):
        result, journal, state = self.run_reconciler(
            "rollback", fixtures={"user-exists": "1", "user-roles": ROLE + "\n"}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn("remove-roles", journal)
        self.assertIn("enabled=false", journal)
        self.assertIn("user-disabled", state)
        # Deleting a principal is the CTO's decision: never here.
        self.assertNotIn("delete", journal)

    def test_rollback_is_idempotent_when_the_user_is_absent(self):
        result, journal, _ = self.run_reconciler("rollback")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("remove-roles", journal)
        self.assertNotIn("update", journal)

    # ---- identity pins --------------------------------------------------

    def test_identity_cannot_be_repointed_by_environment(self):
        for var, value in (
            ("REALM", "other"),
            ("ROLE_NAME", "other-role"),
            ("USERNAME", "someone-else@e-dani.com"),
        ):
            result, journal, _ = self.run_reconciler("ensure", extra_env={var: value})
            self.assertNotEqual(0, result.returncode, f"{var} must be immutable")
            self.assertIn(f"{var} is immutable", result.stderr)
            self.assertNotIn("create users", journal)

    def test_unknown_mode_fails(self):
        result, _, _ = self.run_reconciler("ensure", extra_env={"MODE": "grant-everything"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("MODE must be ensure, audit, or rollback", result.stderr)


class WriteFixtureUserStaticTest(unittest.TestCase):
    def test_script_pins_the_reviewed_identity(self):
        script = SCRIPT.read_text()
        self.assertIn('REALM="${REALM:-edani}"', script)
        self.assertIn(f'ROLE_NAME="${{ROLE_NAME:-{ROLE}}}"', script)
        self.assertIn(f'USERNAME="${{USERNAME:-{FIXTURE}}}"', script)
        self.assertIn(f'[ "${{USERNAME}}" = "{FIXTURE}" ]', script)

    def test_script_only_invokes_image_safe_externals(self):
        # The Keycloak 26.6.2 image ships no awk/jq/python (SC-1215).
        code = _code(SCRIPT.read_text())
        for banned in ("awk", "jq ", "jq\n", "python3", "curl", "base64"):
            self.assertNotIn(banned, code, f"{banned} is not available in the pinned image")

    def test_password_reaches_kcadm_only_via_the_environment(self):
        code = _code(SCRIPT.read_text())
        self.assertIn('KC_CLI_PASSWORD="${FIXTURE_PASSWORD}"', code)
        # Never argv, never a JSON attribute, never echoed.
        self.assertNotIn("--new-password", code)
        self.assertNotIn("-s value=", code)
        self.assertNotIn('echo "${FIXTURE_PASSWORD}"', code)
        self.assertNotIn('printf \'%s\\n\' "${FIXTURE_PASSWORD}"', code)
        self.assertNotIn("set -x", code)

    def test_script_creates_users_but_never_deletes_anything(self):
        code = _code(SCRIPT.read_text())
        self.assertIn('"${KCADM}" create users', code)
        self.assertIn('"${KCADM}" set-password', code)
        self.assertIn('"${KCADM}" add-roles', code)
        self.assertIn('"${KCADM}" remove-roles', code)
        self.assertNotIn('"${KCADM}" delete', code)
        # The exact-username resolution, never a prefix search.
        self.assertIn('exact=true', code)

    def test_job_is_postsync_wave25_nonroot_pinned_and_tokenless(self):
        manifest = JOB.read_text()
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn('argocd.argoproj.io/sync-wave: "25"', manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertIn("name: keycloak-bootstrap", manifest)
        self.assertIn("value: edani", manifest)
        self.assertIn(f"value: {ROLE}", manifest)
        self.assertIn(f"value: {FIXTURE}", manifest)
        self.assertIn("name: FIXTURE_PASSWORD", manifest)
        self.assertIn(f"name: {ES_NAME}", manifest)
        self.assertNotIn("KC_BOOTSTRAP_ADMIN_PASSWORD\n              value:", manifest)
        self.assertNotIn(PASSWORD, manifest)

    def test_external_secret_follows_the_onepassword_onchange_pattern(self):
        manifest = JOB.read_text()
        self.assertIn("kind: ExternalSecret", manifest)
        self.assertIn(f"name: {ES_NAME}", manifest)
        # Kyverno externalsecret-onepassword-onchange + the 1000/day quota.
        self.assertIn("refreshPolicy: OnChange", manifest)
        self.assertIn("name: onepassword", manifest)
        self.assertIn("kind: ClusterSecretStore", manifest)
        self.assertIn(f"key: {ITEM}/password", manifest)
        self.assertIn("creationPolicy: Owner", manifest)
        self.assertIn("deletionPolicy: Retain", manifest)

    def test_wave_ordering_is_after_the_role_hook(self):
        role_job = (BASE / "agentgateway-write-role-job.yaml").read_text()
        self.assertIn('argocd.argoproj.io/sync-wave: "20"', role_job)
        self.assertIn('argocd.argoproj.io/sync-wave: "25"', JOB.read_text())

    def test_wired_into_kustomize_and_rollback_is_manual(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("agentgateway-write-fixture-user-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-write-fixture-user.sh", kustomization)
        self.assertIn("keycloak-agentgateway-write-fixture-user", kustomization)
        self.assertNotIn(
            "manual/agentgateway-write-fixture-user-rollback-job.yaml", kustomization
        )
        rollback = ROLLBACK_JOB.read_text()
        self.assertIn("value: rollback", rollback)
        self.assertIn(f"value: {ROLE}", rollback)
        self.assertIn(f"value: {FIXTURE}", rollback)
        self.assertIn("backoffLimit: 0", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    def test_catalog_and_principals_declare_the_fixture(self):
        catalog = json.loads((BASE / "ROLES.yaml").read_text())
        entry = next(r for r in catalog["roles"] if r["name"] == ROLE)
        self.assertEqual(entry["grantees"], sorted([FIXTURE, SA, "me@e-dani.com"]))
        defaults = next(r for r in catalog["roles"] if r["name"] == "default-roles-edani")
        self.assertIn(FIXTURE, defaults["grantees"])
        principals_text = (BASE / "PRINCIPALS.md").read_text()
        block = re.search(r"```json\n(.*?)\n```", principals_text, re.S).group(1)
        principals = json.loads(block)
        entry = next(p for p in principals["principals"] if p["username"] == FIXTURE)
        self.assertEqual(entry["realm_roles"], sorted(entry["realm_roles"]))
        self.assertIn(ROLE, entry["realm_roles"])
        self.assertEqual(entry["owner"], "QA")
        self.assertEqual(entry["type"], "humano")

    def test_write_role_hook_tolerates_exactly_this_fixture(self):
        script = (BASE / "scripts" / "agentgateway-write-role.sh").read_text()
        self.assertIn(
            f'FIXTURE_GRANTEE_USERNAME="${{FIXTURE_GRANTEE_USERNAME:-{FIXTURE}}}"', script
        )
        self.assertIn(f'[ "${{FIXTURE_GRANTEE_USERNAME}}" = "{FIXTURE}" ]', script)
        self.assertIn('[ "${username}" = "${FIXTURE_GRANTEE_USERNAME}" ]', script)

    def test_documented_in_readme_runbook_and_ci(self):
        readme = (BASE / "README.md").read_text()
        self.assertIn("agentgateway-write-fixture-user-job.yaml", readme)
        self.assertIn(FIXTURE, readme)
        runbook = (BASE / "RUNBOOK.md").read_text()
        self.assertIn("## 17. Write fixture user", runbook)
        self.assertIn("agentgateway-write-fixture-user-rollback-job.yaml", runbook)
        self.assertIn(ITEM, runbook)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn(
            "sh -n platform/keycloak-next/scripts/agentgateway-write-fixture-user.sh", ci
        )
        self.assertIn("tests/test_agentgateway_write_fixture_user_contract.py", ci)


if __name__ == "__main__":
    unittest.main()
