"""Shared harness for the platform/keycloak-next PostSync hook contract tests.

Owned by OWU-28-g (the hooks' bootstrap was extracted to
platform/keycloak-next/scripts/kc-admin-common.sh; the test-side equivalent
lives here): the fake-kcadm skeleton, the reconciler runner and the small
helpers every hook contract test needs. Used by
test_agentgateway_write_grant_daniel_contract.py,
test_agentgateway_write_fixture_user_contract.py and
test_keycloak_agentgateway_role_contract.py.
"""

import base64
import json
import os
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
COMMON = BASE / "scripts" / "kc-admin-common.sh"

# The reconcilers run inside the pinned Keycloak image, which ships no awk
# (SC-1215). Only these externals may be invoked.
IMAGE_SAFE_EXTERNS = ("kcadm", "sed", "grep", "tr", "wc", "rm", "sleep")

# The Keycloak 26.6.2 image ships no awk/jq/python (SC-1215).
BANNED_EXTERNS = ("awk", "jq ", "jq\n", "python3", "curl", "base64")


def code_lines(script_text):
    """Executable lines only (comments dropped): the comments name the very
    binaries and flags the contract forbids, to explain why."""
    return "\n".join(
        line for line in script_text.splitlines() if not lstrip_comment(line)
    )


def lstrip_comment(line):
    return line.lstrip().startswith("#")


def hook_code(*paths):
    """Executable lines of a hook script plus the shared bootstrap it sources."""
    return code_lines("".join(pathlib.Path(p).read_text() for p in paths))


def make_token(roles, azp):
    claims = json.dumps(
        {"azp": azp, "aud": "mcp.lan.e-dani.com", "realm_access": {"roles": roles}},
        separators=(",", ":"),
    )
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(claims.encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


def run_hook(script, fake_kcadm, *, mode="ensure", fixtures=None, flags=None,
             extra_env=None):
    """Drive a real reconciler script against a fake kcadm.

    fixtures: dict of state-file name -> content. flags: state-file names
    touched with "1" (the boolean fixtures). Returns (result, journal,
    state_files).
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = pathlib.Path(tmp)
        state = tmp_path / "state"
        state.mkdir()
        journal = tmp_path / "journal"
        journal.touch()
        fake = tmp_path / "kcadm.sh"
        fake.write_text(fake_kcadm)
        fake.chmod(0o755)
        for name, content in (fixtures or {}).items():
            (state / name).write_text(content)
        for name in flags or ():
            (state / name).write_text("1")
        env = os.environ.copy()
        env.update(
            {
                "MODE": mode,
                "KCADM": str(fake),
                "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-a-real-secret",
                "KEYCLOAK_URL": "http://keycloak.stub.invalid",
                "FAKE_STATE": str(state),
                "FAKE_JOURNAL": str(journal),
            }
        )
        env.update(extra_env or {})
        result = subprocess.run(
            ["/bin/sh", str(script)], capture_output=True, text=True, env=env
        )
        state_files = {p.name: p.read_text() for p in sorted(state.iterdir())}
        return result, journal.read_text(), state_files


# ---------------------------------------------------------------------------
# Fake kcadm assembly. The hooks' fakes share the journal preamble and the
# add-roles/remove-roles block; only the get dispatch and the extra commands
# differ per hook.

_PREAMBLE = """\
#!/bin/sh
command="$1"
shift
state="$FAKE_STATE"
journal="$FAKE_JOURNAL"
printf '%s %s\\n' "$command" "$*" >>"$journal"
"""


def add_remove_roles_case(uid_guard):
    """The add-roles/remove-roles case shared by the grant hooks: the write is
    journaled, guarded by uid, and honours the addroles-fail /
    addroles-silent-noop state fixtures (SC-1215: a 0-exit write that did not
    land must be caught by the post-ensure read)."""
    return f"""\
      add-roles|remove-roles)
        uid=""; rolename=""; prev=""
        for a in "$@"; do
          [ "$prev" = "--uid" ] && uid="$a"
          [ "$prev" = "--rolename" ] && rolename="$a"
          prev="$a"
        done
        [ "$uid" = {uid_guard} ] || exit 65
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
"""


def build_fake_kcadm(config_body, get_body, write_cases, tail=""):
    return (
        _PREAMBLE
        + "\ncase \"$command\" in\n"
        + "  config)\n" + config_body + "    ;;\n"
        + "  get)\n" + get_body + "    ;;\n"
        + write_cases
        + (tail or "  *)\n    exit 66\n    ;;\n")
        + "esac\n"
    )


class BootstrapSourceContractMixin:
    """The hook must source kc-admin-common.sh (no local bootstrap copy) and,
    together with it, only invoke externals the pinned Keycloak image ships
    (SC-1215). Mixed into the hook static tests, which provide SCRIPT."""

    def test_script_sources_the_shared_bootstrap(self):
        script = self.SCRIPT.read_text()
        self.assertIn('. "${0%/*}/kc-admin-common.sh"', script)
        self.assertNotIn("login_admin() {", script)
        self.assertIn('KCADM_TMP_FILES="${KCADM_OUT}"', script)

    def test_script_only_invokes_image_safe_externals(self):
        # The Keycloak 26.6.2 image ships no awk/jq/python (SC-1215). The
        # shared bootstrap runs in the same image, so it is audited too.
        code = hook_code(self.SCRIPT, COMMON)
        for banned in BANNED_EXTERNS:
            self.assertNotIn(banned, code, f"{banned} is not available in the pinned image")


def assert_job_hardened(test, manifest):
    """The PostSync Job shape every write-grant hook shares: PostSync wave 25,
    non-root, tokenless, pinned image, bootstrap env."""
    test.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
    test.assertIn('argocd.argoproj.io/sync-wave: "25"', manifest)
    test.assertIn("activeDeadlineSeconds: 900", manifest)
    test.assertIn("automountServiceAccountToken: false", manifest)
    test.assertIn("runAsNonRoot: true", manifest)
    test.assertIn("readOnlyRootFilesystem: true", manifest)
    test.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
    test.assertIn("name: keycloak-bootstrap", manifest)
    test.assertIn("value: edani", manifest)


class SilentWriteContractMixin:
    """SC-1215: kcadm can swallow server answers. A write that fails must
    surface the server reply, and a 0-exit write that did not land must be
    caught by the post-ensure read, not reported as granted. Mixed into the
    write-grant functional tests, which provide run_reconciler(mode,
    fixtures=...) and may override NOOP_FIXTURES."""

    ROLE = "agentgateway-write"
    NOOP_FIXTURES = {"addroles-silent-noop": "1"}

    def test_ensure_surfaces_server_reply_on_write_failure(self):
        result, _, _ = self.run_reconciler("ensure", fixtures={"addroles-fail": "1"})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("server replied", result.stderr)

    def test_ensure_post_assertion_fails_when_the_write_silently_noops(self):
        result, _, state = self.run_reconciler("ensure", fixtures=self.NOOP_FIXTURES)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("post-ensure assertion failed", result.stderr)
        self.assertNotIn(self.ROLE, state.get("user-roles", ""))


# The get dispatch tail shared by the grant-hook fakes: the role lookup
# (missing = fail closed) and the unknown-endpoint trap.
_GET_TAIL = """\
          roles/*)
            if [ -f "$state/role-missing" ]; then exit 1; fi
            printf 'role-uuid\\n'
            ;;
          *)
            exit 64
            ;;
        esac
        exit 0
"""

# --- grant-daniel (OWU-80): the pinned human's direct realm-role mapping ----

_DANIEL_GET = """\
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
            if [ -f "$state/user-roles" ]; then cat "$state/user-roles"; else printf '\\n'; fi
            ;;
          users/*)
            if [ -f "$state/user-missing" ]; then exit 1; fi
            case "$fields" in
              id) printf '%s\\n' "${endpoint#users/}" ;;
              username) if [ -f "$state/user-username" ]; then cat "$state/user-username"; else printf 'me@e-dani.com\\n'; fi ;;
              enabled) if [ -f "$state/user-enabled" ]; then cat "$state/user-enabled"; else printf 'true\\n'; fi ;;
              serviceAccountClientId) if [ -f "$state/user-sa" ]; then cat "$state/user-sa"; else printf '\\n'; fi ;;
              *) exit 63 ;;
            esac
            ;;
""" + _GET_TAIL

DANIEL_FAKE_KCADM = build_fake_kcadm(
    "        exit 0\n",
    _DANIEL_GET,
    add_remove_roles_case('"$FAKE_SUBJECT"'),
)


# --- fixture user (OWU-28-g): creates the user, re-applies the password -----

_FIXTURE_GET = """\
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
""" + _GET_TAIL

_FIXTURE_WRITE_CASES = """\
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
""" + add_remove_roles_case('"fixture-user-id"')

FIXTURE_FAKE_KCADM = build_fake_kcadm("        exit 0\n", _FIXTURE_GET,
                                      _FIXTURE_WRITE_CASES)


# --- write-role (SC-44 + OWU-80 + OWU-28-g): the exclusivity auditor ---------

_WRITE_ROLE_GET = """\
        res="$1"
        shift
        fields=""; q=""; exact=""
        prev=""
        for a in "$@"; do
          [ "$prev" = "--fields" ] && fields="$a"
          case "$a" in clientId=*) q="${a#clientId=}";; max=*) q="list";; username=*) exact="yes";; esac
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
            printf 'service-account-agentgateway-mcp\\n'
            if fx intruder; then
              printf 'intruder@e-dani.com\\n'
            elif fx fixture_present; then
              printf 'qa-write-sin-vinculo@e-dani.com\\n'
            elif ! fx human_absent; then
              printf 'me@e-dani.com\\n'
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
            if [ -n "$exact" ]; then
              # exact-username search of the OWU-28-g fixture tolerance
              if fx fixture_present; then printf 'fixture-id\\n'; fi
              exit 0
            fi
            if fx human_absent; then printf 'other-id\\n'
            elif fx intruder; then printf "$FAKE_SUBJECT\\nintruder-id\\nother-id\\n"
            else printf "$FAKE_SUBJECT\\nother-id\\n"; fi
            if fx fixture_present; then printf 'fixture-id\\n'; fi
            ;;
          users/*/role-mappings/realm/composite)
            uid="${res#users/}"; uid="${uid%/role-mappings/realm/composite}"
            case "$uid" in
              sa-mcp) printf 'agentgateway-write\\ndefault-roles-edani\\n' ;;
              sa-chat) printf 'default-roles-edani\\n' ;;
              "$FAKE_SUBJECT")
                if fx human_absent; then printf 'default-roles-edani\\n'
                else printf 'agentgateway-write\\ndefault-roles-edani\\n'; fi ;;
              fixture-id)
                if fx fixture_present; then printf 'agentgateway-write\\ndefault-roles-edani\\n'
                else printf 'default-roles-edani\\n'; fi ;;
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
              fixture-id)
                if fx fixture_present; then printf 'agentgateway-write\\ndefault-roles-edani\\n'
                else printf 'default-roles-edani\\n'; fi ;;
              *) printf 'default-roles-edani\\n' ;;
            esac
            ;;
          *) exit 62 ;;
        esac
        exit 0
"""

WRITE_ROLE_FAKE_KCADM = build_fake_kcadm(
    """\
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
""",
    _WRITE_ROLE_GET,
    "      add-roles|remove-roles|create|delete|update)\n        exit 0\n        ;;\n",
    tail="      *) exit 63 ;;\n",
)

# The write-role fake needs the fx() state helper right after the preamble.
WRITE_ROLE_FAKE_KCADM = WRITE_ROLE_FAKE_KCADM.replace(
    "printf '%s %s\\n' \"$command\" \"$*\" >>\"$journal\"\n",
    "printf '%s %s\\n' \"$command\" \"$*\" >>\"$journal\"\nfx() { [ -f \"$state/$1\" ]; }\n",
    1,
)
