"""OWU-80 (OWU-28 P6): contract of the human write grant to Daniel.

The reconciler agentgateway-write-grant-daniel.sh owns EXACTLY ONE IdP fact —
the direct realm-role mapping of agentgateway-write (realm edani) onto the
human user pinned by subject e51253a7-c137-4c6c-9fb9-af9cecd3b147
(username me@e-dani.com). These tests pin the identity of the grant, the
never-create-users / never-create-role limits, the post-ensure assertion, the
rollback scope, the wave/kustomization wiring and the catalog declarations
(ROLES.yaml + PRINCIPALS.md) that keep the keycloak-role-drift sweep green.
The functional tests drive the real script against a fake kcadm, the same
harness style as tests/test_agentgateway_read_grants_contract.py.
"""

import base64
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
SCRIPT = BASE / "scripts" / "agentgateway-write-grant-daniel.sh"
JOB = BASE / "agentgateway-write-grant-daniel-job.yaml"
ROLLBACK_JOB = BASE / "manual" / "agentgateway-write-grant-daniel-rollback-job.yaml"

SUBJECT = "e51253a7-c137-4c6c-9fb9-af9cecd3b147"
USERNAME = "me@e-dani.com"
ROLE = "agentgateway-write"
SA = "service-account-agentgateway-mcp"

# The reconciler runs inside the pinned Keycloak image, which ships no awk
# (SC-1215). Only these externals may be invoked.
IMAGE_SAFE_EXTERNS = ("kcadm", "sed", "grep", "tr", "wc", "rm", "sleep")

FAKE_KCADM = textwrap.dedent(
    """\
    #!/bin/sh
    command="$1"
    shift
    state="$FAKE_STATE"
    journal="$FAKE_JOURNAL"
    printf '%s %s\\n' "$command" "$*" >>"$journal"

    read_fixture() {
      # $1: fixture file name. stdout: its content, or the default ($2) when absent.
      if [ -f "$state/$1" ]; then cat "$state/$1"; else printf '%s\\n' "$2"; fi
    }

    case "$command" in
      config)
        exit 0
        ;;
      get)
        endpoint="$1"
        shift
        fields=""
        prev=""
        for a in "$@"; do
          [ "$prev" = "--fields" ] && fields="$a"
          prev="$a"
        done
        case "$endpoint" in
          users/*/role-mappings/realm)
            read_fixture user-roles ""
            ;;
          users/*)
            if [ -f "$state/user-missing" ]; then exit 1; fi
            case "$fields" in
              id) printf '%s\\n' "${endpoint#users/}" ;;
              username) read_fixture user-username "me@e-dani.com" ;;
              enabled) read_fixture user-enabled "true" ;;
              serviceAccountClientId) read_fixture user-sa "" ;;
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
      add-roles|remove-roles)
        uid=""; rolename=""; prev=""
        for a in "$@"; do
          [ "$prev" = "--uid" ] && uid="$a"
          [ "$prev" = "--rolename" ] && rolename="$a"
          prev="$a"
        done
        [ "$uid" = "$FAKE_SUBJECT" ] || exit 65
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


class WriteGrantDanielFunctionalTest(unittest.TestCase):
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
                    "FAKE_STATE": str(state),
                    "FAKE_JOURNAL": str(journal),
                    "FAKE_SUBJECT": SUBJECT,
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

    def test_ensure_grants_the_pinned_user_and_asserts_after(self):
        result, journal, state = self.run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn(f"--uid {SUBJECT} --rolename {ROLE}", journal)
        self.assertIn(ROLE, state.get("user-roles", ""))
        # The post-ensure assertion re-reads the user's direct realm-role
        # mappings (OWU-80 spec): the mapping collection was queried AFTER the
        # add-roles call, not only before it.
        self.assertGreater(journal.rindex("role-mappings/realm"), journal.index("add-roles"))

    def test_ensure_is_idempotent_when_already_granted(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-roles": ROLE + "\n"}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("add-roles", journal)

    def test_ensure_fails_loud_on_absent_subject_and_never_creates_users(self):
        result, journal, _ = self.run_reconciler("ensure", fixtures={"user-missing": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("does not exist", result.stderr)
        self.assertIn("refusing to create a human user", result.stderr)
        self.assertNotIn("add-roles", journal)
        self.assertNotIn("create", journal)

    def test_ensure_fails_on_username_drift_of_the_pinned_subject(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-username": "someone-else@e-dani.com\n"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not the pinned", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_fails_on_disabled_user(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-enabled": "false\n"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("disabled", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_refuses_a_service_account_identity(self):
        result, journal, _ = self.run_reconciler(
            "ensure", fixtures={"user-sa": "some-client\n"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("service account", result.stderr)
        self.assertNotIn("add-roles", journal)

    def test_ensure_never_creates_the_role(self):
        result, journal, _ = self.run_reconciler("ensure", fixtures={"role-missing": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to create it here", result.stderr)
        self.assertNotIn("add-roles", journal)
        self.assertNotIn("create", journal)

    def test_ensure_surfaces_server_reply_on_write_failure(self):
        result, _, _ = self.run_reconciler("ensure", fixtures={"addroles-fail": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("server replied", result.stderr)
        self.assertIn("400 Bad Request", result.stderr)

    def test_ensure_post_assertion_fails_when_the_write_silently_noops(self):
        # SC-1215 lesson: kcadm can swallow server answers. A 0-exit write that
        # did not land must be caught by the post-ensure read, not reported as
        # granted.
        result, _, state = self.run_reconciler(
            "ensure", fixtures={"addroles-silent-noop": "1"}
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("post-ensure assertion failed", result.stderr)
        self.assertNotIn(ROLE, state.get("user-roles", ""))

    # ---- audit / rollback ---------------------------------------------

    def test_audit_passes_when_present_and_fails_when_absent(self):
        ok, _, _ = self.run_reconciler("audit", fixtures={"user-roles": ROLE + "\n"})
        self.assertEqual(0, ok.returncode, ok.stderr)
        self.assertIn('"present":true', ok.stdout)
        bad, journal, _ = self.run_reconciler("audit")
        self.assertNotEqual(0, bad.returncode)
        self.assertIn("audit:", bad.stderr)
        self.assertNotIn("add-roles", journal)
        self.assertNotIn("remove-roles", journal)

    def test_rollback_removes_only_the_human_mapping(self):
        result, journal, state = self.run_reconciler(
            "rollback", fixtures={"user-roles": ROLE + "\n"}
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn('"changed":true', result.stdout)
        self.assertIn(f"--uid {SUBJECT} --rolename {ROLE}", journal)
        self.assertNotIn(ROLE, state.get("user-roles", ""))
        # The role itself is never deleted by this hook.
        self.assertNotIn("delete", journal)

    def test_rollback_is_idempotent_when_absent_or_user_gone(self):
        result, journal, _ = self.run_reconciler("rollback")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn('"changed":false', result.stdout)
        self.assertNotIn("remove-roles", journal)
        gone, _, _ = self.run_reconciler("rollback", fixtures={"user-missing": "1"})
        self.assertEqual(0, gone.returncode, gone.stderr)
        self.assertIn('"present":false', gone.stdout)

    # ---- identity pins --------------------------------------------------

    def test_identity_cannot_be_repointed_by_environment(self):
        for var, value in (
            ("REALM", "other"),
            ("ROLE_NAME", "other-role"),
            ("USER_ID", "00000000-0000-0000-0000-000000000000"),
            ("USER_NAME", "someone-else@e-dani.com"),
        ):
            result, journal, _ = self.run_reconciler("ensure", extra_env={var: value})
            self.assertNotEqual(0, result.returncode, f"{var} must be immutable")
            self.assertIn(f"{var} is immutable", result.stderr)
            self.assertNotIn("add-roles", journal)

    def test_unknown_mode_fails(self):
        result, _, _ = self.run_reconciler("ensure", extra_env={"MODE": "grant-everything"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("MODE must be ensure, audit, or rollback", result.stderr)


class WriteGrantDanielStaticTest(unittest.TestCase):
    def test_script_pins_the_reviewed_identity(self):
        script = SCRIPT.read_text()
        self.assertIn(f'REALM="${{REALM:-edani}}"', script)
        self.assertIn(f'ROLE_NAME="${{ROLE_NAME:-{ROLE}}}"', script)
        self.assertIn(f'USER_ID="${{USER_ID:-{SUBJECT}}}"', script)
        self.assertIn(f'USER_NAME="${{USER_NAME:-{USERNAME}}}"', script)
        self.assertIn(f'[ "${{USER_ID}}" = "{SUBJECT}" ]', script)
        self.assertIn(f'[ "${{USER_NAME}}" = "{USERNAME}" ]', script)

    def test_script_only_invokes_image_safe_externals(self):
        # The Keycloak 26.6.2 image ships no awk/jq/python (SC-1215).
        code = _code(SCRIPT.read_text())
        for banned in ("awk", "jq ", "jq\n", "python3", "curl", "base64"):
            self.assertNotIn(banned, code, f"{banned} is not available in the pinned image")

    def test_script_never_mutates_users_or_the_role(self):
        code = _code(SCRIPT.read_text())
        # Only add-roles / remove-roles touch the realm, and only for the
        # pinned uid and role: no create, update or delete of any resource.
        self.assertNotIn('"${KCADM}" create', code)
        self.assertNotIn('"${KCADM}" update', code)
        self.assertNotIn('"${KCADM}" delete', code)
        self.assertNotIn('"${KCADM}" set', code)
        self.assertIn('"${KCADM}" add-roles', code)
        self.assertIn('"${KCADM}" remove-roles', code)

    def test_script_is_redacted(self):
        code = _code(SCRIPT.read_text())
        self.assertNotIn("set -x", code)
        self.assertNotIn('echo "${KC_BOOTSTRAP_ADMIN_PASSWORD}"', code)
        self.assertNotIn('printf \'%s\\n\' "${KC_BOOTSTRAP_ADMIN_PASSWORD}"', code)

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
        self.assertIn(f"value: {SUBJECT}", manifest)
        self.assertIn(f"value: {USERNAME}", manifest)
        self.assertNotIn("KC_BOOTSTRAP_ADMIN_PASSWORD\n              value:", manifest)

    def test_wired_into_kustomize_and_rollback_is_manual(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("agentgateway-write-grant-daniel-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-write-grant-daniel.sh", kustomization)
        self.assertNotIn(
            "manual/agentgateway-write-grant-daniel-rollback-job.yaml", kustomization
        )
        rollback = ROLLBACK_JOB.read_text()
        self.assertIn("value: rollback", rollback)
        self.assertIn(f"value: {SUBJECT}", rollback)
        self.assertIn(f"value: {ROLE}", rollback)
        self.assertIn("backoffLimit: 0", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    def test_catalog_and_principals_declare_the_grant(self):
        catalog = json.loads((BASE / "ROLES.yaml").read_text())
        entry = next(r for r in catalog["roles"] if r["name"] == ROLE)
        self.assertEqual(entry["grantees"], sorted([USERNAME, SA]))
        self.assertIn("OWU-80", entry["origin"])
        self.assertIn("OWU-80", entry["privilege"]["denies"])
        principals_text = (BASE / "PRINCIPALS.md").read_text()
        block = re.search(r"```json\n(.*?)\n```", principals_text, re.S).group(1)
        principals = json.loads(block)
        entry = next(
            p for p in principals["principals"] if p["username"] == USERNAME
        )
        self.assertIn(ROLE, entry["realm_roles"])
        self.assertEqual(entry["realm_roles"], sorted(entry["realm_roles"]))

    def test_write_role_hook_tolerates_exactly_this_human(self):
        script = (BASE / "scripts" / "agentgateway-write-role.sh").read_text()
        self.assertIn(f'HUMAN_GRANTEE_ID="${{HUMAN_GRANTEE_ID:-{SUBJECT}}}"', script)
        self.assertIn(
            f'HUMAN_GRANTEE_USERNAME="${{HUMAN_GRANTEE_USERNAME:-{USERNAME}}}"', script
        )
        self.assertIn(
            f'[ "${{HUMAN_GRANTEE_ID}}" = "{SUBJECT}" ]', script
        )
        # The tolerance is by subject id in the effective-role audit and by
        # pinned username in the direct-mapping audit; the role rollback
        # refuses to delete the role while the human grant exists.
        self.assertIn('[ "${user_id}" = "${HUMAN_GRANTEE_ID}" ]', script)
        self.assertIn('[ "${username}" = "${HUMAN_GRANTEE_USERNAME}" ]', script)
        self.assertIn("agentgateway-write-grant-daniel-rollback-job.yaml first", script)

    def test_documented_in_readme_runbook_and_ci(self):
        readme = (BASE / "README.md").read_text()
        self.assertIn("agentgateway-write-grant-daniel-job.yaml", readme)
        self.assertIn(SUBJECT, readme)
        self.assertIn("OWU-77", readme)
        runbook = (BASE / "RUNBOOK.md").read_text()
        self.assertIn("## 16. Human write grant", runbook)
        self.assertIn("agentgateway-write-grant-daniel-rollback-job.yaml", runbook)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("sh -n platform/keycloak-next/scripts/agentgateway-write-grant-daniel.sh", ci)
        self.assertIn("tests/test_agentgateway_write_grant_daniel_contract.py", ci)


def make_token(roles, azp):
    claims = json.dumps(
        {"azp": azp, "aud": "mcp.lan.e-dani.com", "realm_access": {"roles": roles}},
        separators=(",", ":"),
    )
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(claims.encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


# Functional harness for the AMENDED exclusivity logic of
# agentgateway-write-role.sh (SC-44's hook now tolerates the pinned human).
# That PostSync runs on every sync of the k8s-infra app, so the new control
# flow is exercised against a fake kcadm, not just grepped: same harness style
# as tests/test_agentgateway_read_grants_contract.py.
WRITE_ROLE_FAKE_KCADM = textwrap.dedent(
    """\
    #!/bin/sh
    command="$1"
    shift
    state="$FAKE_STATE"
    journal="$FAKE_JOURNAL"
    printf '%s %s\\n' "$command" "$*" >>"$journal"
    fx() { [ -f "$state/$1" ]; }

    case "$command" in
      config)
        cfg=""; cli=""; prev=""
        for a in "$@"; do
          [ "$prev" = "--config" ] && cfg="$a"
          [ "$prev" = "--client" ] && cli="$a"
          prev="$a"
        done
        if [ -n "$cli" ] && [ -n "$cfg" ]; then
          printf '{"token": "%s"}\\n' "$FAKE_MCP_TOKEN" > "$cfg"
        fi
        exit 0
        ;;
      get)
        res="$1"
        shift
        fields=""; q=""
        prev=""
        for a in "$@"; do
          [ "$prev" = "--fields" ] && fields="$a"
          case "$a" in clientId=*) q="${a#clientId=}";; max=*) q="list";; esac
          prev="$a"
        done
        case "$res" in
          clients)
            if [ "$q" = "agentgateway-mcp" ]; then printf 'mcp-uuid\\n'; exit 0; fi
            if [ "$fields" = "id,clientId,serviceAccountsEnabled" ]; then
              printf 'mcp-uuid,agentgateway-mcp,true\\nchat-uuid,chat-agentgateway,true\\n'
              exit 0
            fi
            exit 61
            ;;
          clients/*/service-account-user)
            case "$res" in
              clients/mcp-uuid/service-account-user)
                case "$fields" in
                  id) printf 'sa-mcp\\n' ;;
                  username) printf 'service-account-agentgateway-mcp\\n' ;;
                esac ;;
              clients/chat-uuid/service-account-user)
                case "$fields" in
                  id) printf 'sa-chat\\n' ;;
                  username) printf 'service-account-chat-agentgateway\\n' ;;
                esac ;;
            esac
            exit 0
            ;;
          clients/*/client-secret)
            printf 'not-a-real-secret\\n'
            ;;
          clients/mcp-uuid)
            case "$fields" in
              enabled|serviceAccountsEnabled) printf 'true\\n' ;;
              *) printf '\\n' ;;
            esac
            ;;
          roles/*/users)
            if fx intruder; then
              printf 'service-account-agentgateway-mcp\\nintruder@e-dani.com\\n'
            elif fx human_absent; then
              printf 'service-account-agentgateway-mcp\\n'
            else
              printf 'service-account-agentgateway-mcp\\nme@e-dani.com\\n'
            fi
            ;;
          roles/*/groups)
            printf ''
            ;;
          roles/agentgateway-write)
            case "$fields" in
              composite) printf 'false\\n' ;;
              *) printf 'role-uuid\\n' ;;
            esac
            ;;
          users)
            if fx human_absent; then printf 'other-id\\n'
            elif fx intruder; then printf "$FAKE_SUBJECT\\nintruder-id\\nother-id\\n"
            else printf "$FAKE_SUBJECT\\nother-id\\n"; fi
            ;;
          users/*/role-mappings/realm/composite)
            uid="${res#users/}"; uid="${uid%/role-mappings/realm/composite}"
            case "$uid" in
              sa-mcp) printf 'agentgateway-write\\ndefault-roles-edani\\n' ;;
              sa-chat) printf 'default-roles-edani\\n' ;;
              "$FAKE_SUBJECT")
                if fx human_absent; then printf 'default-roles-edani\\n'
                else printf 'agentgateway-write\\ndefault-roles-edani\\n'; fi ;;
              intruder-id) printf 'agentgateway-write\\n' ;;
              *) printf 'default-roles-edani\\n' ;;
            esac
            ;;
          users/*/role-mappings/realm)
            uid="${res#users/}"; uid="${uid%/role-mappings/realm}"
            case "$uid" in
              sa-mcp) printf 'agentgateway-write\\n' ;;
              "$FAKE_SUBJECT")
                if fx human_absent || fx intruder; then printf 'default-roles-edani\\n'
                else printf 'agentgateway-write\\ndefault-roles-edani\\n'; fi ;;
              *) printf 'default-roles-edani\\n' ;;
            esac
            ;;
          *) exit 62 ;;
        esac
        exit 0
        ;;
      add-roles|remove-roles|create|delete|update)
        exit 0
        ;;
      *) exit 63 ;;
    esac
    """
)


class WriteRoleHookToleratesPinnedHumanTest(unittest.TestCase):
    """The SC-44 hook keeps running every sync; after OWU-80 it must pass with
    the human grant present, pass before it lands, still fail on any other
    holder, and its role rollback must refuse to run while the human holds."""

    def run_write_role(self, mode, fixtures=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            state = tmp_path / "state"
            state.mkdir()
            journal = tmp_path / "journal"
            journal.touch()
            fake_kcadm = tmp_path / "kcadm.sh"
            fake_kcadm.write_text(WRITE_ROLE_FAKE_KCADM)
            fake_kcadm.chmod(0o755)
            for name in fixtures or ():
                (state / name).write_text("1")
            env = os.environ.copy()
            env.update(
                {
                    "MODE": mode,
                    "KCADM": str(fake_kcadm),
                    "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-a-real-secret",
                    "KEYCLOAK_URL": "http://keycloak.stub.invalid",
                    "FAKE_STATE": str(state),
                    "FAKE_JOURNAL": str(journal),
                    "FAKE_SUBJECT": SUBJECT,
                    "FAKE_MCP_TOKEN": make_token(
                        [ROLE, "default-roles-edani"], "agentgateway-mcp"
                    ),
                }
            )
            result = subprocess.run(
                ["/bin/sh", str(BASE / "scripts" / "agentgateway-write-role.sh")],
                capture_output=True,
                text=True,
                env=env,
            )
            return result, journal.read_text()

    def test_ensure_passes_with_the_human_grantee_present(self):
        result, journal = self.run_write_role("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"human_grantee_holds":true', result.stdout)
        # steady state: nothing to add, the SA already holds the role
        self.assertNotIn("add-roles", journal)

    def test_ensure_passes_before_the_grant_lands(self):
        # First sync after the merge: wave 20 runs before this grant hook's
        # wave 25, so the human is not a holder yet — tolerated, not required.
        result, _ = self.run_write_role("ensure", fixtures=["human_absent"])
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"human_grantee_holds":false', result.stdout)

    def test_ensure_still_fails_on_any_other_holder(self):
        result, _ = self.run_write_role("ensure", fixtures=["intruder"])
        self.assertNotEqual(0, result.returncode)
        self.assertIn("unauthorized user", result.stderr)

    def test_role_rollback_refuses_while_the_human_holds(self):
        result, journal = self.run_write_role("rollback")
        self.assertNotEqual(0, result.returncode)
        self.assertIn(
            "agentgateway-write-grant-daniel-rollback-job.yaml first", result.stderr
        )
        # Refused BEFORE any mutation: the SA grant and the role are intact.
        self.assertNotIn("remove-roles", journal)
        self.assertNotIn("delete", journal)


if __name__ == "__main__":
    unittest.main()
