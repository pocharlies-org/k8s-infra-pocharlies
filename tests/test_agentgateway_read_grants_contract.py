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

# Measured 2026-09-12 (INFRA-44): agentgateway-mcp has fullScopeAllowed=true, so
# its minted token carries the reviewed 22 PLUS the flattened composites of the
# service account's default-roles-edani (25 exact). openclaw-readonly-agentgateway
# has fullScopeAllowed=false and measured exactly its reviewed 7 — the defaults
# do NOT travel there.
TOKEN_DEFAULT_ROLES = ["default-roles-edani", "offline_access", "uma_authorization"]
MCP_TOKEN_ROLES = READ_ROLE_NAMES + ["agentgateway-write"] + TOKEN_DEFAULT_ROLES


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
            agentgateway-mcp) token="$FAKE_TOKEN_MCP" ;;
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
                if [ "$endpoint" = clients/oc-uuid ]; then printf 'false\\n'; else printf 'true\\n'; fi
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
            if [ -f "$state/roles" ] && grep -Fxq "$role,false" "$state/roles"; then
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
    (state / "scope-mcp").write_text("".join(f"{role}\n" for role in READ_ROLE_NAMES))
    (state / "scope-oc").write_text(
        "cto-office-send\n" + "".join(f"{role}\n" for role in OPENCLAW_ROLE_NAMES)
    )
    (state / "grants-mcp-sa").write_text("".join(f"{role}\n" for role in READ_ROLE_NAMES))
    (state / "grants-oc-sa").write_text(
        "cto-office-send\n" + "".join(f"{role}\n" for role in OPENCLAW_ROLE_NAMES)
    )


class AgentgatewayReadGrantsContractTest(unittest.TestCase):
    def run_reconciler(self, mode="ensure", seed=None, expect_ok=True):
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
                    "FAKE_TOKEN_MCP": make_token(MCP_TOKEN_ROLES, "agentgateway-mcp"),
                    "FAKE_TOKEN_OC": make_token(
                        ["cto-office-send"] + OPENCLAW_ROLE_NAMES,
                        "openclaw-readonly-agentgateway",
                    ),
                }
            )
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
        self.assertIn("roles/${role}/users", script)
        self.assertIn("roles/${role}/groups", script)
        self.assertIn("mcp.lan.e-dani.com", script)
        # The exact MCP token expectation is the 22 reviewed roles plus the
        # three measured flattened composites (25 total, INFRA-44).
        self.assertIn("TOKEN_DEFAULT_ROLE_NAMES", script)
        for role in TOKEN_DEFAULT_ROLES:
            self.assertIn(role, script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${token}"', script)
        self.assertNotIn('echo "${client_secret}"', script)

    def test_ensure_from_empty_creates_roles_maps_grants_and_verifies_tokens(self):
        result, journal, state_files = self.run_reconciler(mode="ensure", seed=None)
        self.assertIn('"roles":21,"created":21', result.stdout)
        self.assertIn('"tokens_verified":true', result.stdout)
        self.assertEqual(21, journal.count("create roles "))
        self.assertEqual(1, journal.count("create clients/mcp-uuid/scope-mappings/realm"))
        self.assertEqual(1, journal.count("create clients/oc-uuid/scope-mappings/realm"))
        self.assertEqual(1, journal.count("create users/mcp-sa/role-mappings/realm"))
        self.assertEqual(1, journal.count("create users/oc-sa/role-mappings/realm"))
        self.assertEqual(21, len(state_files["scope-mcp"].split()))
        # cto-office-send belongs to the openclaw reconciler: this one maps
        # and grants exactly its six reviewed roles on that client.
        self.assertEqual(6, len(state_files["scope-oc"].split()))
        self.assertEqual(21, len(state_files["grants-mcp-sa"].split()))
        self.assertEqual(6, len(state_files["grants-oc-sa"].split()))

    def test_ensure_is_no_op_when_full_state_is_present(self):
        result, journal, _ = self.run_reconciler(mode="ensure", seed=seed_full_state)
        self.assertIn('"roles":21,"created":0', result.stdout)
        self.assertNotIn("create roles ", journal)
        self.assertNotIn("create clients/", journal)
        self.assertNotIn("create users/", journal)

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
        script = BASE / "scripts" / "agentgateway-read-grants.sh"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            state = tmp_path / "state"
            state.mkdir()
            seed_full_state(state)
            journal = tmp_path / "journal"
            journal.touch()
            fake_kcadm = tmp_path / "kcadm.sh"
            fake_kcadm.write_text(FAKE_KCADM)
            fake_kcadm.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "MODE": "audit",
                    "KCADM": str(fake_kcadm),
                    "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-a-real-secret",
                    "FAKE_STATE": str(state),
                    "FAKE_JOURNAL": str(journal),
                    "FAKE_TOKEN_MCP": make_token(READ_ROLE_NAMES, "agentgateway-mcp"),
                    "FAKE_TOKEN_OC": make_token(
                        ["cto-office-send"] + OPENCLAW_ROLE_NAMES,
                        "openclaw-readonly-agentgateway",
                    ),
                }
            )
            result = subprocess.run(
                ["/bin/sh", str(script)], capture_output=True, text=True, env=env
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("not exactly the reviewed matrix", result.stderr)

    def run_audit_with_tokens(self, mcp_roles, oc_roles):
        script = BASE / "scripts" / "agentgateway-read-grants.sh"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            state = tmp_path / "state"
            state.mkdir()
            seed_full_state(state)
            journal = tmp_path / "journal"
            journal.touch()
            fake_kcadm = tmp_path / "kcadm.sh"
            fake_kcadm.write_text(FAKE_KCADM)
            fake_kcadm.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "MODE": "audit",
                    "KCADM": str(fake_kcadm),
                    "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-a-real-secret",
                    "FAKE_STATE": str(state),
                    "FAKE_JOURNAL": str(journal),
                    "FAKE_TOKEN_MCP": make_token(mcp_roles, "agentgateway-mcp"),
                    "FAKE_TOKEN_OC": make_token(
                        oc_roles, "openclaw-readonly-agentgateway"
                    ),
                }
            )
            return subprocess.run(
                ["/bin/sh", str(script)], capture_output=True, text=True, env=env
            )

    def test_mcp_token_with_extra_role_fails_closed(self):
        # The comparison is EXACT, never a subset: a role an attacker added to
        # the service account must fail the hook even though the reviewed 25
        # are all present.
        result = self.run_audit_with_tokens(
            MCP_TOKEN_ROLES + ["create-realm"],
            ["cto-office-send"] + OPENCLAW_ROLE_NAMES,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed matrix", result.stderr)

    def test_mcp_token_missing_a_measured_default_fails_closed(self):
        # The 25 are the measured exact set: dropping one of the flattened
        # composites (e.g. a scope-mapping regression) must also fail closed.
        result = self.run_audit_with_tokens(
            [role for role in MCP_TOKEN_ROLES if role != "uma_authorization"],
            ["cto-office-send"] + OPENCLAW_ROLE_NAMES,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed matrix", result.stderr)

    def test_openclaw_token_with_travelling_defaults_fails_closed(self):
        # INFRA-45 guard: openclaw measured exactly 7 (fullScopeAllowed=false
        # filters the realm defaults out). If a flip starts shipping the
        # defaults, this assertion must fail closed until re-reviewed.
        result = self.run_audit_with_tokens(
            MCP_TOKEN_ROLES,
            ["cto-office-send"] + OPENCLAW_ROLE_NAMES + TOKEN_DEFAULT_ROLES,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("not exactly the reviewed matrix", result.stderr)

    def test_job_is_postsync_nonroot_pinned_and_network_limited(self):
        manifest = (BASE / "agentgateway-read-grants-job.yaml").read_text()
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn('argocd.argoproj.io/sync-wave: "20"', manifest)
        # 1800s: ~630s measured to the mint path at 500m CPU (INFRA-44); the
        # previous 900s budget was exceeded on the first attempt.
        self.assertIn("activeDeadlineSeconds: 1800", manifest)
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
        self.assertIn("value: rollback", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

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
