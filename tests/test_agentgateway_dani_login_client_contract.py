"""OWU-75 (OWU-28 P1; security ruling OWU-100): contract of the confidential
ROPC test client `dani-login-test`.

The reconciler agentgateway-dani-login-client.sh owns EXACTLY ONE IdP fact —
the client itself: direct access grants on, every other flow off, no redirect
URIs, access-token TTL 900 s with refresh tokens off (OWU-100 condition 3), the
house audience mapper `aud-mcp` to mcp.lan.e-dani.com, and a realm scope
mapping that EMITS (never concedes) exactly `agentgateway-write` (#190
pattern). These tests pin those facts, the two-ExternalSecret split (A: client
secret, seeded before the merge; B: Daniel's password, seeded with his gesture
— the Job must never reference B, whose absence is the expected state), the
never-create-the-role limit, the rollback scope (client only), the
wave/kustomization wiring and the additive documentation. The auditor's
two-holder tolerance is NOT re-affirmed here: it is already covered by
test_keycloak_agentgateway_role_contract.py and
test_agentgateway_write_fixture_user_contract.py. The functional tests drive
the real script against a fake kcadm through the shared harness in
tests/keycloak_hook_testlib.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # unittest from the repo root
from keycloak_hook_testlib import (BASE, COMMON, ROLE, ROOT,
                                   BootstrapSourceContractMixin,
                                   assert_job_hardened, hook_code, run_hook)

SCRIPT = BASE / "scripts" / "agentgateway-dani-login-client.sh"
JOB = BASE / "agentgateway-dani-login-client-job.yaml"
ROLLBACK_JOB = BASE / "manual" / "agentgateway-dani-login-client-rollback-job.yaml"

CLIENT = "dani-login-test"
AUDIENCE = "mcp.lan.e-dani.com"
ES_SECRET = "agentgateway-dani-login-client-secret"
ES_PASSWORD = "agentgateway-dani-login-password"
FAKE_SECRET = "test-dani-login-secret-not-real"

# The state a fully reconciled client leaves behind (what the fake kcadm serves
# as the "in sync" server for audit and idempotent-ensure runs).
IN_SYNC_FLAGS = "\n".join([
    "clientId=dani-login-test",
    "enabled=true",
    "publicClient=false",
    "standardFlowEnabled=false",
    "directAccessGrantsEnabled=true",
    "implicitFlowEnabled=false",
    "serviceAccountsEnabled=false",
    "fullScopeAllowed=false",
    "protocol=openid-connect",
    "redirectUris=[]",
    'attributes."access.token.lifespan"=900',
    'attributes."use.refresh.tokens"=false',
]) + "\n"

# Fake kcadm simulating the client endpoints this reconciler touches: the
# client list/lookup, the client document (booleans via --fields, attributes
# and redirectUris only in the FULL document — INFRA-197), the protocol
# mappers, the client realm scope, and the role lookup. create/update record
# the -s flags as the server would store them, so the post-ensure reads check
# what the script actually sent. The journal masks the client secret: a leak
# into the journal or stdout is what the redaction contract is about.
FAKE_KCADM = r"""
#!/bin/sh
command="$1"
shift
state="$FAKE_STATE"
journal="$FAKE_JOURNAL"
printf '%s %s\n' "$command" "$*" | sed "s|$FAKE_SECRET|[REDACTED]|g" >>"$journal"
fx() { [ -f "$state/$1" ]; }

field_value() {
  if fx flags; then
    sed -n "s|^$1=||p" "$state/flags" | tail -n 1
  fi
}

attr_val() {
  if fx flags; then
    grep "^attributes\.\"$1\"=" "$state/flags" | tail -n 1 | sed 's/^[^=]*=//'
  fi
}

json_doc() {
  printf '{\n'
  printf '  "id": "client-uuid",\n'
  printf '  "clientId": "dani-login-test",\n'
  for f in enabled publicClient standardFlowEnabled directAccessGrantsEnabled implicitFlowEnabled serviceAccountsEnabled fullScopeAllowed; do
    v="$(field_value "$f")"; [ -n "$v" ] || v="false"
    printf '  "%s": %s,\n' "$f" "$v"
  done
  r="$(field_value redirectUris)"; [ -n "$r" ] || r="[]"
  printf '  "redirectUris": %s,\n' "$r"
  printf '  "attributes": { "access.token.lifespan": "%s", "use.refresh.tokens": "%s" }\n' \
    "$(attr_val access.token.lifespan)" "$(attr_val use.refresh.tokens)"
  printf '}\n'
}

record_flags() {
  prev=""
  for a in "$@"; do
    if [ "$prev" = "-s" ]; then printf '%s\n' "$a" >> "$state/flags"; fi
    prev="$a"
  done
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
      clients)
        if fx client-exists; then printf 'client-uuid\n'; fi
        exit 0
        ;;
      clients/*/protocol-mappers/models)
        if fx mapper; then printf 'mapper-uuid,aud-mcp\n'; fi
        exit 0
        ;;
      clients/*/scope-mappings/realm)
        if fx scope-roles; then cat "$state/scope-roles"; fi
        exit 0
        ;;
      clients/*)
        if ! fx client-exists; then exit 1; fi
        case "$fields" in
          "") json_doc ;;
          id) printf 'client-uuid\n' ;;
          *) field_value "$fields" ;;
        esac
        exit 0
        ;;
      roles/*)
        if fx role-missing; then exit 1; fi
        printf 'role-uuid\n'
        exit 0
        ;;
      *) exit 64 ;;
    esac
    ;;
  create)
    endpoint="$1"
    shift
    case "$endpoint" in
      clients)
        if fx create-fail; then
          printf 'Error: conflict\n' >&2
          exit 1
        fi
        if fx create-silent-noop; then exit 0; fi
        : > "$state/flags"
        record_flags "$@"
        touch "$state/client-exists"
        ;;
      clients/*/scope-mappings/realm)
        body=""
        prev=""
        for a in "$@"; do
          if [ "$prev" = "-b" ]; then body="$a"; fi
          prev="$a"
        done
        printf '%s\n' "$body" | sed -n 's/.*"name":"\([^"]*\)".*/\1/p' >> "$state/scope-roles"
        ;;
      clients/*/protocol-mappers/models)
        touch "$state/mapper"
        ;;
      *) exit 67 ;;
    esac
    exit 0
    ;;
  update)
    endpoint="$1"
    shift
    case "$endpoint" in
      clients/*) record_flags "$@" ;;
      clients/*/protocol-mappers/models/*) touch "$state/mapper" ;;
    esac
    exit 0
    ;;
  delete)
    endpoint="$1"
    case "$endpoint" in
      clients/*)
        rm -f "$state/client-exists" "$state/flags" "$state/mapper" "$state/scope-roles"
        ;;
      *) exit 68 ;;
    esac
    exit 0
    ;;
  *) exit 66 ;;
esac
"""


class DaniLoginClientFunctionalTest(unittest.TestCase):
    def run_reconciler(self, mode="ensure", fixtures=None, flags=None, extra_env=None):
        env = {"DANI_LOGIN_CLIENT_SECRET": FAKE_SECRET, "FAKE_SECRET": FAKE_SECRET}
        env.update(extra_env or {})
        return run_hook(SCRIPT, FAKE_KCADM, mode=mode, fixtures=fixtures,
                        flags=flags, extra_env=env)

    def in_sync(self, **kw):
        fixtures = {"flags": IN_SYNC_FLAGS, "scope-roles": ROLE + "\n"}
        fixtures.update(kw.pop("fixtures", {}))
        return self.run_reconciler(kw.pop("mode", "ensure"), fixtures=fixtures,
                                   flags=kw.pop("flags", ["client-exists", "mapper"]), **kw)

    # ---- ensure ---------------------------------------------------------

    def test_ensure_creates_the_client_with_the_pinned_facts(self):
        result, journal, state = self.run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)
        self.assertIn('"ropc":true', result.stdout)
        self.assertIn("create clients ", journal)
        flags = state.get("flags", "")
        for fact in (
            "publicClient=false",
            "standardFlowEnabled=false",
            "directAccessGrantsEnabled=true",
            "implicitFlowEnabled=false",
            "serviceAccountsEnabled=false",
            "fullScopeAllowed=false",
            "redirectUris=[]",
            'attributes."access.token.lifespan"=900',
            'attributes."use.refresh.tokens"=false',
        ):
            self.assertIn(fact, flags)
        self.assertIn("create clients/client-uuid/protocol-mappers/models", journal)
        self.assertEqual(ROLE + "\n", state.get("scope-roles", ""))

    def test_client_secret_never_reaches_stdout_or_the_journal(self):
        result, journal, _ = self.run_reconciler("ensure")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn(FAKE_SECRET, result.stdout)
        self.assertNotIn(FAKE_SECRET, journal)
        # the -s secret=... write IS performed — it just travels redacted
        self.assertIn("secret=[REDACTED]", journal)

    def test_ensure_updates_in_place_when_the_client_exists(self):
        result, journal, _ = self.in_sync()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("update clients/client-uuid ", journal)
        self.assertNotIn("create clients ", journal)

    def test_ensure_fails_closed_on_an_empty_client_secret(self):
        result, journal, _ = self.run_reconciler(
            "ensure", extra_env={"DANI_LOGIN_CLIENT_SECRET": ""})
        self.assertNotEqual(0, result.returncode)
        self.assertIn("client secret is empty", result.stderr)
        self.assertNotIn("create", journal)

    def test_ensure_never_creates_the_role(self):
        result, journal, _ = self.run_reconciler("ensure", flags=["role-missing"])
        self.assertNotEqual(0, result.returncode)
        self.assertIn("refusing to create it here", result.stderr)
        self.assertNotIn("create clients ", journal)

    def test_ensure_surfaces_write_failure_and_silent_noop(self):
        failed, _, _ = self.run_reconciler("ensure", flags=["create-fail"])
        self.assertNotEqual(0, failed.returncode)
        self.assertIn("failed to create client dani-login-test", failed.stderr)
        # SC-1215: a 0-exit create that stored nothing must be caught by the
        # post-ensure read, not reported as reconciled.
        noop, _, _ = self.run_reconciler("ensure", flags=["create-silent-noop"])
        self.assertNotEqual(0, noop.returncode)
        self.assertIn("client dani-login-test is missing", noop.stderr)

    # ---- audit ----------------------------------------------------------

    def test_audit_passes_when_everything_is_in_sync(self):
        result, _, _ = self.in_sync(mode="audit")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":true', result.stdout)

    def test_audit_fails_when_the_client_is_absent(self):
        result, _, _ = self.run_reconciler(
            "audit", fixtures={"flags": IN_SYNC_FLAGS}, flags=["mapper"])
        self.assertNotEqual(0, result.returncode)
        self.assertIn("client dani-login-test is missing", result.stderr)

    def test_audit_fails_on_ttl_and_refresh_drift(self):
        for old, new, needle in (
            ('"access.token.lifespan"=900', '"access.token.lifespan"=86400',
             "access.token.lifespan is not 900"),
            ('"use.refresh.tokens"=false', '"use.refresh.tokens"=true',
             "use.refresh.tokens is not false"),
        ):
            drifted = IN_SYNC_FLAGS.replace(old, new)
            result, _, _ = self.run_reconciler(
                "audit", fixtures={"flags": drifted, "scope-roles": ROLE + "\n"},
                flags=["client-exists", "mapper"])
            self.assertNotEqual(0, result.returncode, needle)
            self.assertIn(needle, result.stderr)

    def test_audit_fails_on_a_registered_redirect_uri(self):
        drifted = IN_SYNC_FLAGS.replace("redirectUris=[]",
                                        'redirectUris=["https://evil.example/callback"]')
        result, _, _ = self.run_reconciler(
            "audit", fixtures={"flags": drifted, "scope-roles": ROLE + "\n"},
            flags=["client-exists", "mapper"])
        self.assertNotEqual(0, result.returncode)
        self.assertIn("carries redirect URIs", result.stderr)

    def test_audit_fails_on_scope_mapping_drift(self):
        missing, _, _ = self.run_reconciler(
            "audit", fixtures={"flags": IN_SYNC_FLAGS}, flags=["client-exists", "mapper"])
        self.assertNotEqual(0, missing.returncode)
        self.assertIn("client realm scope mapping is missing " + ROLE, missing.stderr)
        extra, _, _ = self.run_reconciler(
            "audit", fixtures={"flags": IN_SYNC_FLAGS,
                               "scope-roles": ROLE + "\nsome-other-role\n"},
            flags=["client-exists", "mapper"])
        self.assertNotEqual(0, extra.returncode)
        self.assertIn("expected exactly " + ROLE, extra.stderr)

    def test_audit_fails_on_a_missing_audience_mapper(self):
        result, _, _ = self.run_reconciler(
            "audit", fixtures={"flags": IN_SYNC_FLAGS, "scope-roles": ROLE + "\n"},
            flags=["client-exists"])
        self.assertNotEqual(0, result.returncode)
        self.assertIn("audience mapper aud-mcp is missing", result.stderr)

    # ---- rollback ---------------------------------------------------------

    def test_rollback_deletes_only_the_client(self):
        result, journal, state = self.in_sync(mode="rollback")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertIn("delete clients/client-uuid ", journal)
        self.assertNotIn("client-exists", state)
        # the role, its holders and any other resource are never touched
        self.assertNotIn("delete roles", journal)
        self.assertNotIn("remove-roles", journal)

    def test_rollback_needs_no_client_secret_and_is_idempotent(self):
        result, journal, _ = self.run_reconciler(
            "rollback", extra_env={"DANI_LOGIN_CLIENT_SECRET": ""})
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"present":false', result.stdout)
        self.assertNotIn("delete", journal)

    # ---- identity pins ----------------------------------------------------

    def test_identity_cannot_be_repointed_by_environment(self):
        for var, value in (
            ("CLIENT_ID", "other-client"),
            ("REALM", "other"),
            ("AGENTGATEWAY_AUDIENCE", "other-audience"),
            ("MAPPER_NAME", "other-mapper"),
            ("ROLE_NAME", "other-role"),
            ("ACCESS_TOKEN_LIFESPAN", "86400"),
            ("USE_REFRESH_TOKENS", "true"),
        ):
            result, journal, _ = self.run_reconciler("ensure", extra_env={var: value})
            self.assertNotEqual(0, result.returncode, f"{var} must be immutable")
            self.assertIn(f"{var} is immutable", result.stderr)
            self.assertNotIn("create", journal)

    def test_unknown_mode_fails(self):
        result, _, _ = self.run_reconciler("grant-everything")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("MODE must be ensure, audit, or rollback", result.stderr)


class DaniLoginClientStaticTest(BootstrapSourceContractMixin, unittest.TestCase):
    SCRIPT = SCRIPT

    def test_script_pins_the_reviewed_identity(self):
        script = SCRIPT.read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-dani-login-test}"', script)
        self.assertIn('REALM="${REALM:-edani}"', script)
        self.assertIn('AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"', script)
        self.assertIn('MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"', script)
        self.assertIn(f'ROLE_NAME="${{ROLE_NAME:-{ROLE}}}"', script)
        self.assertIn('ACCESS_TOKEN_LIFESPAN="${ACCESS_TOKEN_LIFESPAN:-900}"', script)
        self.assertIn('USE_REFRESH_TOKENS="${USE_REFRESH_TOKENS:-false}"', script)
        # the client facts as written to kcadm (ROPC on, everything else off)
        self.assertIn("-s publicClient=false", script)
        self.assertIn("-s standardFlowEnabled=false", script)
        self.assertIn("-s directAccessGrantsEnabled=true", script)
        self.assertIn("-s implicitFlowEnabled=false", script)
        self.assertIn("-s serviceAccountsEnabled=false", script)
        self.assertIn("-s fullScopeAllowed=false", script)
        self.assertIn('-s "redirectUris=[]"', script)
        self.assertIn('attributes.\\"access.token.lifespan\\"', script)
        self.assertIn('attributes.\\"use.refresh.tokens\\"', script)

    def test_script_uses_the_shared_helpers_without_rewriting_them(self):
        script = SCRIPT.read_text()
        self.assertIn('. "$(dirname "$0")/keycloak-reconcile-lib.sh"', script)
        # the scope-mapping and mapper mechanics come from the library
        self.assertNotIn("upsert_audience_mapper() {", script)
        self.assertNotIn("ensure_role_in_client_scope() {", script)
        self.assertNotIn("role_scope_has_direct_role() {", script)
        self.assertIn("ensure_role_in_client_scope", script)
        self.assertIn("upsert_audience_mapper", script)

    def test_script_reads_attributes_from_the_full_document(self):
        # INFRA-197: kcadm serializes map fields EMPTY through --fields; the
        # TTL/refresh pins must be checked against the full JSON (the
        # agentgateway-mcp-token-ttl.sh pattern).
        script = SCRIPT.read_text()
        self.assertIn('kget "clients/${CLIENT_UUID}" --format json', script)
        self.assertNotIn("--fields attributes", script)

    def test_script_never_prints_the_client_secret(self):
        code = hook_code(SCRIPT, COMMON)
        # exactly two uses: the fail-closed emptiness check and the -s write
        self.assertEqual(2, code.count("DANI_LOGIN_CLIENT_SECRET"))
        self.assertNotIn('echo "${DANI_LOGIN_CLIENT_SECRET}"', code)
        self.assertNotIn("set -x", code)
        # the create/update reply is discarded: it carries the secret
        self.assertIn('>/dev/null 2>&1 || \\\n    fail "failed to ${action} client', code)

    def test_job_is_hardened_and_wires_only_the_client_secret(self):
        manifest = JOB.read_text()
        assert_job_hardened(self, manifest)
        self.assertIn(f"value: {CLIENT}", manifest)
        self.assertIn("value: \"900\"", manifest)
        self.assertIn("value: \"false\"", manifest)
        self.assertIn("name: " + ES_SECRET, manifest)
        # the Job section (from kind: Job onwards) must never reference the
        # password Secret: ES B's absence is the expected pre-consent state and
        # must not be able to redden the PostSync (the lesson of #231).
        job_part = manifest.split("kind: Job", 1)[1]
        self.assertNotIn(ES_PASSWORD, job_part)
        self.assertNotIn("DANI_PASSWORD", job_part)

    def test_two_external_secrets_are_split_and_hardened(self):
        manifest = JOB.read_text()
        self.assertEqual(2, manifest.count("kind: ExternalSecret"))
        self.assertIn("key: keycloak-next-dani-login-test/client_secret", manifest)
        self.assertIn("key: keycloak-next-dani-login/password", manifest)
        self.assertEqual(2, manifest.count("refreshPolicy: OnChange"))
        self.assertEqual(2, manifest.count("creationPolicy: Owner"))
        self.assertEqual(2, manifest.count("deletionPolicy: Retain"))
        self.assertEqual(2, manifest.count("kind: ClusterSecretStore"))
        # never one mixed ExternalSecret
        self.assertNotIn("keycloak-next-dani-login-test/password", manifest)

    def test_wired_into_kustomize_and_rollback_is_manual_client_only(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("agentgateway-dani-login-client-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-dani-login-client.sh", kustomization)
        self.assertIn("keycloak-agentgateway-dani-login-client", kustomization)
        self.assertIn("kc-admin-common.sh=scripts/kc-admin-common.sh", kustomization)
        self.assertIn("keycloak-reconcile-lib.sh=scripts/keycloak-reconcile-lib.sh",
                      kustomization)
        self.assertNotIn("manual/agentgateway-dani-login-client-rollback-job.yaml",
                         kustomization)
        rollback = ROLLBACK_JOB.read_text()
        self.assertIn("value: rollback", rollback)
        self.assertIn("backoffLimit: 0", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)
        # rollback deletes the client with no credential of its own
        self.assertNotIn("secretKeyRef", rollback)
        self.assertNotIn("DANI_LOGIN_CLIENT_SECRET", rollback)
        self.assertNotIn("DANI_PASSWORD", rollback)

    def test_documented_in_readme_runbook_and_ci(self):
        readme = (BASE / "README.md").read_text()
        self.assertIn("agentgateway-dani-login-client-job.yaml", readme)
        self.assertIn("dani-login-test", readme)
        runbook = (BASE / "RUNBOOK.md").read_text()
        self.assertIn("keycloak-next-dani-login-test", runbook)
        self.assertIn("keycloak-next-dani-login", runbook)
        self.assertIn("agentgateway-dani-login-client-rollback-job.yaml", runbook)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertIn("sh -n platform/keycloak-next/scripts/agentgateway-dani-login-client.sh", ci)
        self.assertIn("tests/test_agentgateway_dani_login_client_contract.py", ci)

    def test_no_principal_or_role_catalog_entry(self):
        # Architect ruling (nota-architect-plan.md, corrección A): the client
        # has no service account, so PRINCIPALS.md must NOT list it — an entry
        # would make verify-principals.py report permanent drift. Same for the
        # role catalog: the client is not a grantee.
        self.assertNotIn("dani-login-test", (BASE / "PRINCIPALS.md").read_text())
        self.assertNotIn("dani-login-test", (BASE / "ROLES.yaml").read_text())


if __name__ == "__main__":
    unittest.main()
