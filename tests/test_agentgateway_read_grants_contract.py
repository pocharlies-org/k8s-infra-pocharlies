import base64
import json
import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"

READ_ROUTES = [
    "analytics", "atlassian", "brain", "dgx-control", "gsc", "image",
    "merchant", "offers", "picqer", "shopify", "shopify-admin",
    "skirmshop-plugins", "social", "stt", "studio", "synapse", "synapse-sre",
    "synapse-tools", "tts", "weight", "workspace",
]
OPENCLAW_ROUTES = ["gsc", "offers", "skirmshop-plugins", "studio", "synapse", "synapse-tools"]

READ_ROLE_NAMES = [f"agentgateway-read:{route}" for route in READ_ROUTES]
OPENCLAW_ROLE_NAMES = [f"agentgateway-read:{route}" for route in OPENCLAW_ROUTES]
MCP_SA = "service-account-agentgateway-mcp"
OC_SA = "service-account-openclaw-readonly-agentgateway"

# Measured 2026-09-12 (INFRA-44/INFRA-46): agentgateway-mcp with
# fullScopeAllowed=true carries the reviewed 22 PLUS the flattened composites
# of the service account's default-roles-edani (25 exact). With
# fullScopeAllowed=false the defaults do NOT travel — openclaw-readonly-
# agentgateway measured exactly its reviewed 7 — so after INFRA-45's flip the
# exact expected agentgateway-mcp set is the reviewed 22.
TOKEN_DEFAULT_ROLES = ["default-roles-edani", "offline_access", "uma_authorization"]
MCP_TOKEN_ON_ROLES = READ_ROLE_NAMES + ["agentgateway-write"] + TOKEN_DEFAULT_ROLES
MCP_TOKEN_OFF_ROLES = ["agentgateway-write"] + READ_ROLE_NAMES
DEFAULT_OC_ROLES = ["cto-office-send"] + OPENCLAW_ROLE_NAMES


def make_token(roles, azp):
    claims = json.dumps(
        {
            "azp": azp,
            "aud": "mcp.lan.e-dani.com",
            "realm_access": {"roles": roles},
        },
        separators=(",", ":"),
    )
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(claims.encode()).decode().rstrip("=")
    return f"{header}.{payload}.sig"


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
        client=""
        config=""
        prev=""
        for a in "$@"; do
          [ "$prev" = "--config" ] && config="$a"
          [ "$prev" = "--client" ] && client="$a"
          prev="$a"
        done
        if [ -n "$client" ]; then
          case "$client" in
            agentgateway-mcp)
              # Model the measured Keycloak behavior (INFRA-46): the realm
              # defaults travel in the token only while fullScopeAllowed is
              # true. The fake serves the ON token when the flag is true
              # (or unset — a fresh realm starts with the flag on) and the
              # OFF token when it is false.
              if [ -f "$state/fullscope-mcp" ] && grep -qx false "$state/fullscope-mcp"; then
                token="$FAKE_TOKEN_MCP_OFF"
              else
                token="$FAKE_TOKEN_MCP_ON"
              fi
              ;;
            openclaw-readonly-agentgateway) token="$FAKE_TOKEN_OC" ;;
            *) exit 61 ;;
          esac
          printf '{"token": "%s"}\\n' "$token" >"$config"
        fi
        exit 0
        ;;
      get)
        endpoint="$1"
        shift
        fields=""
        query=""
        prev=""
        for a in "$@"; do
          [ "$prev" = "--fields" ] && fields="$a"
          case "$a" in clientId=*) query="$a" ;; esac
          prev="$a"
        done
        case "$endpoint" in
          clients)
            case "$query" in
              clientId=agentgateway-mcp) printf 'mcp-uuid\\n' ;;
              clientId=openclaw-readonly-agentgateway) printf 'oc-uuid\\n' ;;
              *) exit 62 ;;
            esac
            ;;
          clients/mcp-uuid|clients/oc-uuid)
            case "$fields" in
              id) printf '%s\\n' "${endpoint#clients/}" ;;
              enabled|serviceAccountsEnabled) printf 'true\\n' ;;
              fullScopeAllowed)
                if [ "$endpoint" = clients/oc-uuid ]; then
                  printf 'false\\n'
                elif [ -f "$state/fullscope-mcp" ]; then
                  cat "$state/fullscope-mcp"
                else
                  printf 'true\\n'
                fi
                ;;
              *) exit 63 ;;
            esac
            ;;
          clients/mcp-uuid/service-account-user)
            case "$fields" in
              id) printf 'mcp-sa\\n' ;;
              username) printf '%s\\n' 'service-account-agentgateway-mcp' ;;
              *) exit 64 ;;
            esac
            ;;
          clients/oc-uuid/service-account-user)
            case "$fields" in
              id) printf 'oc-sa\\n' ;;
              username) printf '%s\\n' 'service-account-openclaw-readonly-agentgateway' ;;
              *) exit 65 ;;
            esac
            ;;
          clients/mcp-uuid/scope-mappings/realm)
            [ -f "$state/scope-mcp" ] && cat "$state/scope-mcp"
            ;;
          clients/oc-uuid/scope-mappings/realm)
            [ -f "$state/scope-oc" ] && cat "$state/scope-oc"
            ;;
          clients/mcp-uuid/client-secret|clients/oc-uuid/client-secret)
            printf 'not-a-real-secret\\n'
            ;;
          roles)
            [ -f "$state/roles" ] && cat "$state/roles"
            ;;
          roles/*/users)
            role="${endpoint#roles/}"
            role="${role%/users}"
            if [ -f "$state/users" ]; then
              sed -n "s#^$role|\\(..*\\)#\\1#p" "$state/users"
            fi
            ;;
          roles/*/groups)
            [ -f "$state/group-violation" ] && printf '/edani-admins\\n'
            ;;
          roles/*)
            role="${endpoint#roles/}"
            if [ "$role" = agentgateway-write ]; then
              # Pre-existing role owned by the write-role reconciler: always
              # resolvable, never created or deleted by this script.
              case "$fields" in
                id) printf 'id-write\\n' ;;
                composite) printf 'false\\n' ;;
              esac
            elif [ -f "$state/roles" ] && grep -Fxq "$role,false" "$state/roles"; then
              case "$fields" in
                id) printf 'id-%s\\n' "$role" ;;
                composite) printf 'false\\n' ;;
              esac
            else
              exit 1
            fi
            ;;
          users/*/role-mappings/realm)
            uid="${endpoint#users/}"
            uid="${uid%/role-mappings/realm}"
            [ -f "$state/grants-$uid" ] && cat "$state/grants-$uid"
            ;;
          *)
            exit 66
            ;;
        esac
        ;;
      create)
        endpoint="$1"
        shift
        body=""
        name=""
        prev=""
        for a in "$@"; do
          [ "$prev" = "-b" ] && body="$a"
          prev="$a"
          case "$a" in name=*) name="$a" ;; esac
        done
        extract_names() {
          printf '%s\\n' "$body" | tr ',' '\\n' | sed -n 's/.*"name":"\\([^"]*\\)".*/\\1/p'
        }
        case "$endpoint" in
          roles)
            printf '%s,false\\n' "${name#name=}" >>"$state/roles"
            ;;
          clients/mcp-uuid/scope-mappings/realm)
            extract_names >>"$state/scope-mcp"
            ;;
          clients/oc-uuid/scope-mappings/realm)
            extract_names >>"$state/scope-oc"
            ;;
          users/mcp-sa/role-mappings/realm)
            extract_names >>"$state/grants-mcp-sa"
            extract_names | sed 's/$/|service-account-agentgateway-mcp/' >>"$state/users"
            ;;
          users/oc-sa/role-mappings/realm)
            extract_names >>"$state/grants-oc-sa"
            extract_names | sed 's/$/|service-account-openclaw-readonly-agentgateway/' >>"$state/users"
            ;;
          *) exit 67 ;;
        esac
        ;;
      update)
        endpoint="$1"
        shift
        for a in "$@"; do
          case "$a" in
            fullScopeAllowed=false) printf 'false\\n' > "$state/fullscope-mcp" ;;
            fullScopeAllowed=true)
              if [ -n "$FAKE_UPDATE_REJECT_RESTORE" ]; then exit 1; fi
              printf 'true\\n' > "$state/fullscope-mcp" ;;
          esac
        done
        ;;
      delete)
        endpoint="$1"
        shift
        case "$endpoint" in
          roles/*)
            # Mimic Keycloak cascade: deleting a realm role removes its
            # members, user grants and client scope mappings.
            role="${endpoint#roles/}"
            for f in grants-mcp-sa grants-oc-sa scope-mcp scope-oc; do
              if [ -f "$state/$f" ]; then
                grep -Fxv "$role" "$state/$f" > "$state/$f.tmp" || true
                mv "$state/$f.tmp" "$state/$f"
              fi
            done
            if [ -f "$state/roles" ]; then
              grep -Fxv "$role,false" "$state/roles" > "$state/roles.tmp" || true
              mv "$state/roles.tmp" "$state/roles"
            fi
            if [ -f "$state/users" ]; then
              sed "\\|^${role}||d" "$state/users" > "$state/users.tmp"
              mv "$state/users.tmp" "$state/users"
            fi
            ;;
          *) exit 69 ;;
        esac
        ;;
      *)
        exit 68
        ;;
    esac
    exit 0
    """
)


def seed_full_state(state):
    (state / "roles").write_text("".join(f"{role},false\n" for role in READ_ROLE_NAMES))
    users = [f"{role}|{MCP_SA}\n" for role in READ_ROLE_NAMES]
    users += [f"{role}|{OC_SA}\n" for role in OPENCLAW_ROLE_NAMES]
    (state / "users").write_text("".join(users))
    # Post-INFRA-45 steady state: the mcp client scope carries
    # agentgateway-write plus the 21 read roles and fullScopeAllowed is false.
    (state / "scope-mcp").write_text(
        "agentgateway-write\n" + "".join(f"{role}\n" for role in READ_ROLE_NAMES)
    )
    (state / "scope-oc").write_text(
        "cto-office-send\n" + "".join(f"{role}\n" for role in OPENCLAW_ROLE_NAMES)
    )
    (state / "grants-mcp-sa").write_text(
        "agentgateway-write\n" + "".join(f"{role}\n" for role in READ_ROLE_NAMES)
    )
    (state / "grants-oc-sa").write_text(
        "cto-office-send\n" + "".join(f"{role}\n" for role in OPENCLAW_ROLE_NAMES)
    )
    (state / "fullscope-mcp").write_text("false\n")


def seed_full_state_fullscope_on(state):
    seed_full_state(state)
    (state / "fullscope-mcp").write_text("true\n")


class AgentgatewayReadGrantsContractTest(unittest.TestCase):
    def run_reconciler(
        self,
        mode="ensure",
        seed=None,
        expect_ok=True,
        mcp_on_roles=None,
        mcp_off_roles=None,
        oc_roles=None,
        extra_env=None,
    ):
        script = BASE / "scripts" / "agentgateway-read-grants.sh"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            state = tmp_path / "state"
            state.mkdir()
            journal = tmp_path / "journal"
            journal.touch()
            fake_kcadm = tmp_path / "kcadm.sh"
            fake_kcadm.write_text(FAKE_KCADM)
            fake_kcadm.chmod(0o755)
            if seed is not None:
                seed(state)
            env = os.environ.copy()
            env.update(
                {
                    "MODE": mode,
                    "KCADM": str(fake_kcadm),
                    "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-a-real-secret",
                    "FAKE_STATE": str(state),
                    "FAKE_JOURNAL": str(journal),
                    "FAKE_TOKEN_MCP_ON": make_token(
                        mcp_on_roles if mcp_on_roles is not None else MCP_TOKEN_ON_ROLES,
                        "agentgateway-mcp",
                    ),
                    "FAKE_TOKEN_MCP_OFF": make_token(
                        mcp_off_roles
                        if mcp_off_roles is not None
                        else MCP_TOKEN_OFF_ROLES,
                        "agentgateway-mcp",
                    ),
                    "FAKE_TOKEN_OC": make_token(
                        oc_roles if oc_roles is not None else DEFAULT_OC_ROLES,
                        "openclaw-readonly-agentgateway",
                    ),
                }
            )
            if extra_env:
                env.update(extra_env)
            result = subprocess.run(
                ["/bin/sh", str(script)],
                capture_output=True,
                text=True,
                env=env,
            )
            state_files = {
                path.name: path.read_text() for path in sorted(state.iterdir())
            }
            if expect_ok:
                self.assertEqual(0, result.returncode, result.stderr)
            return result, journal.read_text(), state_files

    def test_matrix_is_immutable_and_exactly_the_reviewed_routes(self):
        script = (BASE / "scripts" / "agentgateway-read-grants.sh").read_text()
        self.assertEqual(21, len(READ_ROLE_NAMES))
        for role in READ_ROLE_NAMES:
            self.assertIn(role, script)
        self.assertIn("READ_ROLE_NAMES is immutable", script)
        self.assertIn("OPENCLAW_READ_ROLE_NAMES is immutable", script)
        self.assertIn("group role-mapping is forbidden (SC-44 C6)", script)
        # INFRA-45: fullScopeAllowed=false is part of the owned matrix.
        self.assertIn("must keep fullScopeAllowed=false", script)
        self.assertIn("fullScopeAllowed=false", script)
        # INFRA-45 v2: the flip is fail-closed with auto-restore — the
        # post-flip mismatch restores the flag (read-back + confirmation
        # mint) before aborting, and a failed restore escalates loudly.
        self.assertIn("before fullScopeAllowed=false", script)
        self.assertIn("restored to true", script)
        self.assertIn("manual intervention required", script)
        self.assertIn("roles/${role}/users", script)
        self.assertIn("roles/${role}/groups", script)
        self.assertIn("mcp.lan.e-dani.com", script)
        # The exact MCP token expectation is the 22 reviewed roles plus the
        # three measured flattened composites (25 total) while the flag is
        # true, and the exact reviewed 22 with the flag off (INFRA-44/45).
        self.assertIn("TOKEN_DEFAULT_ROLE_NAMES", script)
        for role in TOKEN_DEFAULT_ROLES:
            self.assertIn(role, script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${token}"', script)
        self.assertNotIn('echo "${client_secret}"', script)

    def test_ensure_from_empty_creates_roles_maps_grants_and_verifies_tokens(self):
        result, journal, state_files = self.run_reconciler(mode="ensure", seed=None)
        self.assertIn('"roles":21,"created":21', result.stdout)
        self.assertIn('"fullscope_allowed":false', result.stdout)
        self.assertIn('"tokens_verified":true', result.stdout)
        self.assertEqual(21, journal.count("create roles "))
        self.assertEqual(1, journal.count("create clients/mcp-uuid/scope-mappings/realm"))
        self.assertEqual(1, journal.count("create clients/oc-uuid/scope-mappings/realm"))
        self.assertEqual(1, journal.count("create users/mcp-sa/role-mappings/realm"))
        self.assertEqual(1, journal.count("create users/oc-sa/role-mappings/realm"))
        # INFRA-45: the mcp client scope is agentgateway-write plus the 21
        # read roles (22), and the flag ends up false.
        self.assertEqual(22, len(state_files["scope-mcp"].split()))
        self.assertIn("agentgateway-write", state_files["scope-mcp"].split())
        self.assertEqual("false\n", state_files["fullscope-mcp"])
        # cto-office-send belongs to the openclaw reconciler: this one maps
        # and grants exactly its six reviewed roles on that client.
        self.assertEqual(6, len(state_files["scope-oc"].split()))
        self.assertEqual(21, len(state_files["grants-mcp-sa"].split()))
        self.assertEqual(6, len(state_files["grants-oc-sa"].split()))

    def test_ensure_is_no_op_when_full_state_is_present(self):
        result, journal, state_files = self.run_reconciler(
            mode="ensure", seed=seed_full_state
        )
        self.assertIn('"roles":21,"created":0', result.stdout)
        self.assertIn('"fullscope_allowed":false', result.stdout)
        self.assertNotIn("create roles ", journal)
        self.assertNotIn("create clients/", journal)
        self.assertNotIn("create users/", journal)
        # fullScopeAllowed=false is part of the owned matrix: an idempotent
        # run must not even issue the update.
        self.assertNotIn("update ", journal)
        self.assertEqual("false\n", state_files["fullscope-mcp"])

    def test_audit_passes_against_full_state(self):
        result, journal, _ = self.run_reconciler(mode="audit", seed=seed_full_state)
        self.assertIn('"tokens_verified":true', result.stdout)
        self.assertNotIn("create ", journal)

    def test_group_mapping_fails_closed(self):
        def seed(state):
            seed_full_state(state)
            (state / "group-violation").touch()

        result, _, _ = self.run_reconciler(mode="ensure", seed=seed, expect_ok=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("group role-mapping is forbidden", result.stderr)

    def test_unauthorized_token_roles_fail_closed(self):
        # A minted agentgateway-mcp token missing agentgateway-write (the 21
        # read roles only) is off-matrix and must abort, in audit mode too.
        result, _, _ = self.run_reconciler(
            mode="audit", seed=seed_full_state, expect_ok=False,
            mcp_off_roles=list(READ_ROLE_NAMES),
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed matrix", result.stderr)

    def test_mcp_token_with_extra_role_fails_closed(self):
        # The comparison is EXACT, never a subset: a role an attacker added to
        # the service account must fail the hook even though the reviewed 22
        # (steady state, flag off) are all present.
        result, _, _ = self.run_reconciler(
            mode="audit", seed=seed_full_state, expect_ok=False,
            mcp_off_roles=MCP_TOKEN_OFF_ROLES + ["create-realm"],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed matrix", result.stderr)

    def test_pre_flip_token_missing_a_measured_default_fails_closed(self):
        # The 25 are the measured exact set WHILE fullScopeAllowed is true:
        # dropping one of the flattened composites (e.g. a scope-mapping
        # regression) must abort the run BEFORE the flip.
        result, journal, state_files = self.run_reconciler(
            mode="ensure", seed=seed_full_state_fullscope_on, expect_ok=False,
            mcp_on_roles=[role for role in MCP_TOKEN_ON_ROLES if role != "uma_authorization"],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed matrix", result.stderr)
        self.assertNotIn("update clients/mcp-uuid", journal)
        self.assertEqual("true\n", state_files["fullscope-mcp"])

    def test_openclaw_token_with_travelling_defaults_fails_closed(self):
        # INFRA-45 guard: openclaw measured exactly 7 (fullScopeAllowed=false
        # filters the realm defaults out). If a flip starts shipping the
        # defaults, this assertion must fail closed until re-reviewed.
        result, _, _ = self.run_reconciler(
            mode="audit", seed=seed_full_state, expect_ok=False,
            oc_roles=["cto-office-send"] + OPENCLAW_ROLE_NAMES + TOKEN_DEFAULT_ROLES,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed matrix", result.stderr)

    def test_ensure_flips_fullscope_off_in_the_fail_closed_order(self):
        # From an empty realm the order must be: map write into the client
        # scope, mint a token and verify the exact 25 (flag still true) BEFORE
        # the flip, then flip, then mint again and verify the exact 22 AFTER
        # the flag is off.
        result, journal, state_files = self.run_reconciler(mode="ensure", seed=None)
        self.assertIn('"fullscope_allowed":false', result.stdout)
        self.assertIn('"tokens_verified":true', result.stdout)
        lines = journal.splitlines()
        mints = [
            i for i, line in enumerate(lines)
            if "config credentials" in line and "--client agentgateway-mcp" in line
        ]
        updates = [i for i, line in enumerate(lines) if line.startswith("update clients/mcp-uuid")]
        scope_create = [
            i for i, line in enumerate(lines)
            if "create clients/mcp-uuid/scope-mappings/realm" in line
        ]
        self.assertEqual(1, len(updates))
        self.assertIn("fullScopeAllowed=false", lines[updates[0]])
        self.assertLess(scope_create[0], updates[0])  # (a) write mapped first
        self.assertLess(mints[0], updates[0])         # (b) 25 verified before flip
        self.assertLess(updates[0], mints[1])         # (d) 22 verified after flip
        self.assertEqual(3, len(mints))               # pre, post, final
        self.assertEqual("false\n", state_files["fullscope-mcp"])

    def test_pre_flip_token_mismatch_blocks_the_flip(self):
        # Scope and grants are complete but fullScope is still true and the
        # minted token (flag on, so the ON set is expected) is off-matrix:
        # the reconciler must abort BEFORE touching fullScopeAllowed, so live
        # traffic never loses roles.
        result, journal, state_files = self.run_reconciler(
            mode="ensure", seed=seed_full_state_fullscope_on, expect_ok=False,
            mcp_on_roles=list(READ_ROLE_NAMES),
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed matrix", result.stderr)
        self.assertNotIn("update clients/mcp-uuid", journal)
        self.assertEqual("true\n", state_files["fullscope-mcp"])

    def test_audit_fails_when_fullscope_is_still_on(self):
        result, _, _ = self.run_reconciler(
            mode="audit", seed=seed_full_state_fullscope_on, expect_ok=False
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("must keep fullScopeAllowed=false", result.stderr)

    def test_mcp_scope_outside_matrix_fails_closed(self):
        # The mcp client scope still rejects anything outside write+21: an
        # extra mapped role widens the reviewed matrix and aborts.
        def seed(state):
            seed_full_state(state)
            with (state / "scope-mcp").open("a") as handle:
                handle.write("some-other-role\n")

        result, _, _ = self.run_reconciler(mode="ensure", seed=seed, expect_ok=False)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("widens the reviewed matrix", result.stderr)

    def test_ensure_auto_restores_fullscope_when_post_flip_token_is_off_matrix(self):
        # The flip is the live step (~9465 requests/4h on this SA): if the
        # post-flip mint is not exactly the 22, the reconciler must restore
        # fullScopeAllowed=true (update, read-back, confirmation mint of the
        # exact 25) BEFORE aborting.
        result, journal, state_files = self.run_reconciler(
            mode="ensure", seed=seed_full_state_fullscope_on, expect_ok=False,
            mcp_off_roles=MCP_TOKEN_OFF_ROLES + ["create-realm"],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("restored to true", result.stderr)
        lines = journal.splitlines()
        updates = [line for line in lines if line.startswith("update clients/mcp-uuid")]
        self.assertEqual(2, len(updates))
        self.assertIn("fullScopeAllowed=false", updates[0])
        self.assertIn("fullScopeAllowed=true", updates[1])
        mints = [i for i, line in enumerate(lines)
                 if "config credentials" in line and "--client agentgateway-mcp" in line]
        self.assertEqual(3, len(mints))  # pre-flip, post-flip, confirmation
        self.assertEqual("true\n", state_files["fullscope-mcp"])

    def test_ensure_does_not_restore_when_flag_was_already_false(self):
        # Steady-state drift is not this run's flip: with the flag already
        # false and an off-matrix token, the run fails closed WITHOUT
        # mutation — restoring true would undo the owned INFRA-45 state.
        result, journal, state_files = self.run_reconciler(
            mode="ensure", seed=seed_full_state, expect_ok=False,
            mcp_off_roles=MCP_TOKEN_OFF_ROLES + ["create-realm"],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed 22", result.stderr)
        self.assertNotIn("update clients/mcp-uuid", journal)
        self.assertEqual("false\n", state_files["fullscope-mcp"])

    def test_ensure_auto_restore_failure_fails_loud_for_manual_intervention(self):
        # If even the emergency restore is rejected, the hook must abort
        # loudly pointing at manual intervention — never silently leave the
        # token in the broken post-flip shape.
        result, _, state_files = self.run_reconciler(
            mode="ensure", seed=seed_full_state_fullscope_on, expect_ok=False,
            mcp_off_roles=MCP_TOKEN_OFF_ROLES + ["create-realm"],
            extra_env={"FAKE_UPDATE_REJECT_RESTORE": "1"},
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("manual intervention required", result.stderr)
        self.assertEqual("false\n", state_files["fullscope-mcp"])

    def test_fullscope_rollback_mode_restores_true_and_verifies(self):
        result, journal, state_files = self.run_reconciler(
            mode="fullscope-rollback", seed=seed_full_state
        )
        self.assertIn('"mode":"fullscope-rollback"', result.stdout)
        self.assertIn('"tokens_verified":true', result.stdout)
        updates = [line for line in journal.splitlines() if line.startswith("update clients/mcp-uuid")]
        self.assertEqual(1, len(updates))
        self.assertIn("fullScopeAllowed=true", updates[0])
        self.assertEqual("true\n", state_files["fullscope-mcp"])

    def test_fullscope_rollback_fails_closed_on_off_matrix_token(self):
        # The flag is restored first (it is what brings traffic back), but an
        # off-matrix token must still abort loudly afterwards.
        result, _, state_files = self.run_reconciler(
            mode="fullscope-rollback", seed=seed_full_state, expect_ok=False,
            mcp_on_roles=MCP_TOKEN_ON_ROLES + ["some-other-role"],
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("widens the reviewed matrix", result.stderr)
        self.assertEqual("true\n", state_files["fullscope-mcp"])

    def test_fullscope_rollback_tolerates_rolled_back_read_grants(self):
        # If the read grants were already rolled back, the token carries
        # agentgateway-write plus the three measured defaults (which travel
        # with the flag on): accepted, the emergency path stays usable.
        result, _, _ = self.run_reconciler(
            mode="fullscope-rollback", seed=seed_full_state,
            mcp_on_roles=["agentgateway-write"] + TOKEN_DEFAULT_ROLES,
        )
        self.assertIn('"tokens_verified":true', result.stdout)

    def test_fullscope_rollback_fails_closed_when_defaults_do_not_travel(self):
        # Measured (INFRA-46): with fullScopeAllowed=true the three realm
        # defaults travel again. A restored flag whose token lacks them means
        # the flag is not effective for this token — fail closed.
        result, _, state_files = self.run_reconciler(
            mode="fullscope-rollback", seed=seed_full_state, expect_ok=False,
            mcp_on_roles=list(MCP_TOKEN_OFF_ROLES),
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing the measured realm default", result.stderr)
        self.assertEqual("true\n", state_files["fullscope-mcp"])

    def test_rollback_mode_deletes_read_roles_and_keeps_write_surface(self):
        result, journal, state_files = self.run_reconciler(
            mode="rollback", seed=seed_full_state
        )
        self.assertIn('"roles_deleted":21,"present":false', result.stdout)
        self.assertEqual(21, journal.count("delete roles/agentgateway-read:"))
        self.assertNotIn("delete roles/agentgateway-write", journal)
        self.assertNotIn("agentgateway-read:", state_files.get("roles", ""))
        self.assertNotIn("agentgateway-read:", state_files["scope-mcp"])
        # The write surface predates this reconciler and stays: while
        # fullScopeAllowed=false it is what keeps write traffic alive.
        self.assertEqual("agentgateway-write\n", state_files["scope-mcp"])
        self.assertEqual("false\n", state_files["fullscope-mcp"])

    def test_job_is_postsync_nonroot_pinned_and_network_limited(self):
        manifest = (BASE / "agentgateway-read-grants-job.yaml").read_text()
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn('argocd.argoproj.io/sync-wave: "20"', manifest)
        # 2700s: ~630s measured to the mint path at 500m CPU (INFRA-44) and
        # a >=135s per-mint floor (first 900s attempt died DeadlineExceeded
        # with two mints pending). INFRA-45 raises the path to FOUR mints
        # (pre-flip, post-flip, final, openclaw); 1800s (INFRA-46) only fit
        # it under ~280s per mint, so the budget is 2700s — ~3.6x the
        # measured per-mint floor.
        self.assertIn("activeDeadlineSeconds: 2700", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertIn("app.kubernetes.io/component: agentgateway-read-grants", manifest)
        self.assertNotIn("0.0.0.0/0", manifest)

    def test_kustomize_owns_job_and_script_and_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "agentgateway-read-grants-rollback-job.yaml").read_text()
        self.assertIn("agentgateway-read-grants-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-read-grants.sh", kustomization)
        self.assertNotIn("manual/agentgateway-read-grants-rollback-job.yaml", kustomization)
        self.assertNotIn("manual/agentgateway-fullscope-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    def test_manual_fullscope_rollback_job_is_manual_and_hardened(self):
        manifest = (BASE / "manual" / "agentgateway-fullscope-rollback-job.yaml").read_text()
        self.assertIn("value: fullscope-rollback", manifest)
        self.assertIn("keycloak-agentgateway-read-grants", manifest)
        # Applied by hand only: no ArgoCD hook may ever run or delete it.
        self.assertNotIn("argocd.argoproj.io/hook", manifest)
        # Light path (login, resolve, one update, one mint): 900s stays
        # ample — the 2700s budget is for the hook's ~165-call reconcile.
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)

    def test_openclaw_reconciler_asserts_read_roles_in_its_tokens(self):
        script = (BASE / "scripts" / "openclaw-readonly-clients.sh").read_text()
        for role in OPENCLAW_ROLE_NAMES:
            self.assertIn(role, script)
        self.assertIn("realm roles are not exactly", script)
        # The negative check (no agentgateway-write in the read-only token)
        # stays literal, and the expected mint set stays the measured exact 7:
        # the realm defaults must NOT be folded into this client's assertion.
        self.assertIn('fail "minted read-only token contains ${FORBIDDEN_REALM_ROLE}"', script)
        # The expected mint set stays the measured exact 7 (base + 6 reads):
        # the realm defaults must NOT be folded into this client's assertion.
        self.assertIn(
            'expected_roles="$(printf \'%s\\n%s\\n\' "${REQUIRED_REALM_ROLE}" "${EXPECTED_READ_ROLES}"',
            script,
        )


if __name__ == "__main__":
    unittest.main()
