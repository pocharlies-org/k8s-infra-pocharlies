import functools
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPT = BASE / "scripts" / "admin-keycloack-impersonation-grant.sh"

# The reconciler runs inside the pinned Keycloak image, which is NOT a
# general-purpose shell image (SC-1215: it ships no awk and the reconciler died
# on "awk: command not found"). The image reference is read from the retire Job
# manifest (SC-1215 retirement: the ensure hook is gone, the pinned reference
# travels with the Job that still runs the script) so the tests audit exactly
# the image the Job runs.
_IMAGE_RE = re.compile(r"image: (\S+/keycloak:26\.6\.2@sha256:[0-9a-f]{64})")


def _pinned_image():
    manifest = (BASE / "admin-keycloack-impersonation-grant-retire-job.yaml").read_text()
    match = _IMAGE_RE.search(manifest)
    if not match:
        raise AssertionError("pinned keycloak 26.6.2 image not found in the retire Job manifest")
    return match.group(1)


DOCKER = shutil.which("docker")
IMAGE = _pinned_image()


def _image_ready():
    if not DOCKER:
        return False
    try:
        return subprocess.run(
            [DOCKER, "image", "inspect", IMAGE],
            capture_output=True, timeout=60,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


IMAGE_READY = _image_ready()

# CI must not go green on skipped in-image tests: the CI job docker-pulls the
# pinned image and sets REQUIRE_IMAGE_CONTRACT=1, which turns "image missing"
# from a skip into a hard failure.
REQUIRE_IMAGE_CONTRACT = os.environ.get("REQUIRE_IMAGE_CONTRACT") == "1"


def in_keycloak_image(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not IMAGE_READY:
            if REQUIRE_IMAGE_CONTRACT:
                self.fail(
                    "in-image contract test cannot run: docker or the pinned "
                    "keycloak image is unavailable while REQUIRE_IMAGE_CONTRACT=1 "
                    "(the CI job must docker-pull the image before this suite)"
                )
            self.skipTest("requires docker and the pinned keycloak 26.6.2 image")
        return func(self, *args, **kwargs)
    return wrapper


# POSIX-sh kcadm stub served to the reconciler inside the Keycloak image. It
# reproduces the two server behaviors the reconciler depends on: "-q
# clientId=" is a SUBSTRING match, and the role-mappings collection is mutable
# so ensure/rollback are observable. Every invocation is appended to STUB_LOG.
KCADM_STUB = textwrap.dedent("""\
    #!/bin/sh
    set -eu
    umask 022
    LOG="${STUB_LOG:?}"
    FIXTURE_DIR="${FIXTURE_DIR:?}"
    printf '%s\\n' "$*" >> "$LOG"
    sub="$1"; shift
    if [ "$sub" = config ]; then exit 0; fi
    if [ "$sub" = create ] || [ "$sub" = delete ]; then
      body=""; prev=""
      for a in "$@"; do
        if [ "$prev" = -f ]; then body="$a"; fi
        prev="$a"
      done
      [ -n "$body" ] && cat "$body" >> "$LOG"
      # The real server answers this collection with 204 on success and with
      # 4xx + a JSON error body otherwise; kcadm -H prints the response status
      # line on BOTH paths and its error message carries the body's error text
      # (measured in-image 2026-09-24). The stub replays that contract: the
      # status line comes from the optional create_status fixture (default
      # "204 No Content") and the body error from create_error.
      status="204 No Content"
      [ -f "${FIXTURE_DIR}/create_status" ] && status="$(cat "${FIXTURE_DIR}/create_status")"
      case "$status" in
        204*)
          printf 'HTTP/1.1 204 No Content\\n'
          if [ -f "${FIXTURE_DIR}/mapped_roles.csv" ]; then
            if [ "$sub" = create ]; then
              printf 'impersonation\\n' >> "${FIXTURE_DIR}/mapped_roles.csv"
            else
              sed -i '/^impersonation$/d' "${FIXTURE_DIR}/mapped_roles.csv"
            fi
          fi
          exit 0
          ;;
      esac
      error="server rejected the request"
      [ -f "${FIXTURE_DIR}/create_error" ] && error="$(cat "${FIXTURE_DIR}/create_error")"
      printf 'HTTP/1.1 %s\\n' "$status"
      printf 'Content-Type: application/json\\n\\n'
      printf 'null [%s]\\n' "$error"
      exit 1
    fi
    [ "$sub" = get ] || { printf 'stub: unsupported sub %s\\n' "$sub" >&2; exit 2; }
    res="$1"; shift
    fields=""; q=""; prev=""
    for a in "$@"; do
      case "$prev" in
        --fields) fields="$a" ;;
        -q) q="${a#clientId=}" ;;
      esac
      prev="$a"
    done
    case "$res" in
      clients)
        # server-side -q clientId= is a SUBSTRING match, like the real server
        grep -F "$q" "${FIXTURE_DIR}/clients.csv" || true
        ;;
      clients/*/service-account-user)
        case "$fields" in
          id) printf 'sa-user-uuid\\n' ;;
          username) printf 'service-account-admin-keycloack-server\\n' ;;
        esac
        ;;
      clients/*/roles/*)
        printf 'role-impersonation-uuid\\n' ;;
      clients/*)
        case "$fields" in
          enabled|serviceAccountsEnabled) printf 'true\\n' ;;
        esac
        ;;
      users/*/role-mappings/clients/*)
        [ -f "${FIXTURE_DIR}/mapped_roles.csv" ] && cat "${FIXTURE_DIR}/mapped_roles.csv" || true
        ;;
      *)
        printf 'stub: unsupported resource %s\\n' "$res" >&2; exit 2 ;;
    esac
""")

# Fixture for the substring-match trap the exact filter must survive: the
# aliases have near-miss siblings that the server-side "-q clientId=" filter
# also returns, and only the exact rows may be accepted.
CLIENTS_FIXTURE = textwrap.dedent("""\
    11111111-1111-1111-1111-111111111111,admin-keycloack-server
    22222222-2222-2222-2222-222222222222,admin-keycloack-server-v2
    33333333-3333-3333-3333-333333333333,edani-realm
    44444444-4444-4444-4444-444444444444,edani-realm-old
""")

# Same fixture minus the exact admin-keycloack-server row: the substring query
# still returns one row (the -v2 near-miss), so a run that accepted it would
# silently grant against the wrong client. The reconciler must fail closed.
CLIENTS_FIXTURE_NO_EXACT = textwrap.dedent("""\
    22222222-2222-2222-2222-222222222222,admin-keycloack-server-v2
    33333333-3333-3333-3333-333333333333,edani-realm
""")

SA_UUID = "11111111-1111-1111-1111-111111111111"
MAPPING_UUID = "33333333-3333-3333-3333-333333333333"


def _run_in_image(fixture_clients, fixture_mapped_roles, mode, extra_fixtures=None):
    """Run the reconciler script inside the pinned Keycloak image with the
    kcadm stub and CSV fixtures mounted. Returns (returncode, stdout, stderr,
    stub log)."""
    # The fixture dir is bind-mounted into the container, so it must live on a
    # path the docker daemon can see. On the ARC runners the daemon does not
    # share the job's /tmp (a /tmp fixture mounted empty, the kcadm stub was
    # "missing" and login_admin's 30x5s retry loop hung the run); RUNNER_TEMP
    # is under the shared runner home. Locally it falls back to the default.
    parent = os.environ.get("RUNNER_TEMP") or None
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="kc-impersonation-", dir=parent))
    try:
        (tmp / "kcadm.sh").write_text(KCADM_STUB)
        (tmp / "kcadm.sh").chmod(0o755)
        (tmp / "clients.csv").write_text(fixture_clients)
        (tmp / "mapped_roles.csv").write_text(fixture_mapped_roles)
        for name, content in (extra_fixtures or {}).items():
            (tmp / name).write_text(content)
        for f in tmp.iterdir():
            f.chmod(0o666)
        (tmp / "kcadm.sh").chmod(0o755)
        tmp.chmod(0o777)
        cmd = [
            DOCKER, "run", "--rm",
            "-v", f"{tmp}:/fixture",
            "-v", f"{BASE / 'scripts'}:/opt/bootstrap:ro",
            "-e", f"MODE={mode}",
            "-e", "KCADM=/fixture/kcadm.sh",
            "-e", "FIXTURE_DIR=/fixture",
            "-e", "STUB_LOG=/fixture/stub.log",
            "-e", "KC_BOOTSTRAP_ADMIN_USERNAME=stub-user",
            "-e", "KC_BOOTSTRAP_ADMIN_PASSWORD=stub-password",
            "-e", "KEYCLOAK_URL=http://keycloak.stub.invalid",
            "--entrypoint", "/bin/sh", IMAGE,
            "/opt/bootstrap/admin-keycloack-impersonation-grant.sh",
        ]
        # Fail fast and legibly if the mounts are not visible to the daemon
        # (empty bind mounts make the script's login retry loop hang).
        probe = subprocess.run(
            [DOCKER, "run", "--rm",
             "-v", f"{tmp}:/fixture",
             "-v", f"{BASE / 'scripts'}:/opt/bootstrap:ro",
             "--entrypoint", "/bin/sh", IMAGE, "-c",
             "test -x /fixture/kcadm.sh && test -f /fixture/clients.csv "
             "&& test -f /opt/bootstrap/admin-keycloack-impersonation-grant.sh"],
            capture_output=True, text=True, timeout=60,
        )
        if probe.returncode != 0:
            raise AssertionError(
                f"bind mounts not visible inside {IMAGE}: the fixture dir "
                f"{tmp} must be on a path the docker daemon shares with the "
                f"runner (RUNNER_TEMP); probe stderr: {probe.stderr.strip()}"
            )
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        log_file = tmp / "stub.log"
        log = log_file.read_text() if log_file.exists() else ""
        return proc.returncode, proc.stdout, proc.stderr, log
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class AdminKeycloackImpersonationGrantContractTest(unittest.TestCase):
    """SC-709 / SC-1215: the reconciler adds exactly one client-role mapping
    (impersonation of the edani realm-client "edani-realm", which lives in the
    master realm together with the admin-keycloack-server client and its
    service-account user) and is additive-only — it never enforces exclusivity,
    never creates or deletes the built-in role, and never touches other
    identities.

    The grant target is "edani-realm" in master, NOT "realm-management" in
    edani: the SA is a master-realm user and cannot hold client roles of
    another realm's realm-management; "edani-realm" (attribute
    realm_client=true) is the client through which this SA already exercises
    every other edani permission, and the measured 403 on
    POST /admin/realms/edani/users/<id>/impersonation is the one role missing
    there (SC-1215, measured 2026-09-24)."""

    def test_reconciler_is_additive_and_redacted(self):
        script = (BASE / "scripts" / "admin-keycloack-impersonation-grant.sh").read_text()
        self.assertIn('CLIENT_ID="${CLIENT_ID:-admin-keycloack-server}"', script)
        self.assertIn('REALM="${REALM:-master}"', script)
        self.assertIn('MAPPING_CLIENT="${MAPPING_CLIENT:-edani-realm}"', script)
        self.assertIn('ROLE_NAME="${ROLE_NAME:-impersonation}"', script)
        self.assertIn('service-account-${CLIENT_ID}', script)
        # Canonical REST collection with fully-resolved uuids (no --in-client).
        # The POST/DELETE target is the collection itself: the user's
        # client-role-mappings resource has NO "/roles" sub-resource (measured
        # 2026-09-24: a "/roles" suffix answers 404) — SC-1215 third failure.
        self.assertIn(
            'users/${SERVICE_ACCOUNT_ID}/role-mappings/clients/${MAPPING_CLIENT_UUID}"',
            script,
        )
        self.assertNotIn(
            'role-mappings/clients/${MAPPING_CLIENT_UUID}/roles', script
        )
        # The body must be an array of role REPRESENTATIONS: the server
        # resolves each entry by name (measured: a bare [{"id":...}] answers
        # 404 "Role not found").
        self.assertIn('"name":"%s"', script)
        self.assertIn('"containerId":"%s"', script)
        # The final POST/DELETE must surface the server's answer: -H makes
        # kcadm print the response status line, and the captured reply is
        # echoed into the failure message (SC-1215: the third apply swallowed
        # the response).
        self.assertIn('-H \\', script)
        self.assertIn('server replied [', script)
        # Raw REST, never the version-sensitive "kcadm add-roles --in-client".
        # Checked against executable code only: the header comment names the
        # flag precisely to explain why it is avoided.
        code = "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn('add-roles', code)
        # The built-in role is only read; a missing one fails closed.
        self.assertIn('clients/${MAPPING_CLIENT_UUID}/roles/${ROLE_NAME}', script)
        self.assertIn('refusing to create an IdP built-in', script)
        self.assertIn('MODE must be ensure, audit, or rollback', script)
        self.assertNotIn('set -x', script)
        self.assertNotIn('echo "${KC_BOOTSTRAP_ADMIN_PASSWORD}"', script)

    def test_reconciler_identity_is_immutable(self):
        script = (BASE / "scripts" / "admin-keycloack-impersonation-grant.sh").read_text()
        # The reconciler cannot be pointed at another realm, client or role.
        self.assertIn('[ "${REALM}" = "master" ]', script)
        self.assertIn('[ "${CLIENT_ID}" = "admin-keycloack-server" ]', script)
        self.assertIn('[ "${MAPPING_CLIENT}" = "edani-realm" ]', script)
        self.assertIn('[ "${ROLE_NAME}" = "impersonation" ]', script)

    def test_client_lookup_is_exact_and_diagnostics_report_rows(self):
        script = SCRIPT.read_text()
        # The server-side "-q clientId=" filter is a substring match; the alias
        # must additionally be matched exactly client-side (SC-1215).
        self.assertIn('if [ "${line#*,}" = "$1" ]; then', script)
        # The exact filter must be plain POSIX shell: the keycloak image ships
        # no awk, and #163 died on "awk: command not found" (SC-1215). Checked
        # against executable code only; the comments name awk to explain why.
        code = "\n".join(
            line for line in script.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn("awk", code)
        # A failed lookup reports both row counts and the clientIds involved,
        # so the operator can tell 0 rows from >1 without re-running anything.
        self.assertIn("expected exactly one client clientId=", script)
        self.assertIn("exact=${exact_count}", script)
        self.assertIn("substring=${fuzzy_count}", script)
        self.assertIn("cut -d, -f2", script)

    def test_reconciler_does_not_enforce_exclusivity_or_touch_the_role(self):
        script = (BASE / "scripts" / "admin-keycloack-impersonation-grant.sh").read_text()
        # Additive-only: no exclusivity auditing copied from write-role.
        self.assertNotIn('assert_effective_role_exclusivity', script)
        self.assertNotIn('another service account', script)
        # Never deletes the built-in role itself (only the user's mapping list).
        self.assertNotIn('delete "roles', script)
        self.assertNotIn('delete "clients/${MAPPING_CLIENT_UUID}/roles"', script)

    def test_retire_job_is_oneshot_nonroot_pinned_and_tokenless(self):
        """SC-1215 retirement: the ensure PostSync hook is gone; the mapping is
        removed ONCE by a plain Job running the reconciler's rollback mode. A
        hook would re-assert absence on every sync forever and silently revoke
        any future legitimate grant, so the manifest must carry no hook
        annotations; and with the app automated selfHeal=true / prune=false
        (measured on the live Application), a ttlSecondsAfterFinished would
        make selfHeal recreate and re-run the Job on every sync forever, so it
        must carry no TTL either. Every security invariant of the hook it
        replaces is kept."""
        manifest = (BASE / "admin-keycloack-impersonation-grant-retire-job.yaml").read_text()
        # Checked against manifest content only: the header comment names the
        # hook and the TTL precisely to explain why neither may appear.
        spec_text = "\n".join(
            line for line in manifest.splitlines() if not line.lstrip().startswith("#")
        )
        self.assertNotIn("argocd.argoproj.io/hook", spec_text)
        self.assertNotIn("ttlSecondsAfterFinished", spec_text)
        self.assertIn("value: rollback", manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn("capabilities:\n              drop: [\"ALL\"]", manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertIn("name: keycloak-bootstrap", manifest)
        self.assertIn("value: admin-keycloack-server", manifest)
        # The mapping being removed lives in master, on the edani realm-client
        # (SC-1215 fix): the retire Job must target exactly what the ensure
        # hook wrote, nothing else.
        self.assertIn("name: REALM\n              value: master", manifest)
        self.assertIn("name: MAPPING_CLIENT\n              value: edani-realm", manifest)
        self.assertNotIn("value: realm-management", manifest)
        self.assertIn("value: impersonation", manifest)
        self.assertNotIn("KC_BOOTSTRAP_ADMIN_PASSWORD\n              value:", manifest)

    def test_retirement_wired_into_argo_and_ensure_hook_is_gone(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "admin-keycloack-impersonation-grant-rollback-job.yaml").read_text()
        # The ensure hook is retired: neither the file nor its kustomization
        # entry may come back, or every future sync would re-grant
        # impersonation (the VP mandate: the grant must not stay permanent).
        self.assertFalse((BASE / "admin-keycloack-impersonation-grant-job.yaml").exists())
        self.assertNotIn("admin-keycloack-impersonation-grant-job.yaml", kustomization)
        # The one-shot retire Job is wired in, and the reconciler ConfigMap it
        # mounts is kept (the retire Job runs the same pinned script).
        self.assertIn("admin-keycloack-impersonation-grant-retire-job.yaml", kustomization)
        self.assertIn("keycloak-admin-keycloack-impersonation-grant\n    files:", kustomization)
        self.assertIn("scripts/admin-keycloack-impersonation-grant.sh", kustomization)
        # The manual rollback stays excluded from GitOps and still undoes
        # exactly what the ensure hook wrote: same realm, same mapping client.
        self.assertNotIn("manual/admin-keycloack-impersonation-grant-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("name: REALM\n              value: master", rollback)
        self.assertIn("name: MAPPING_CLIENT\n              value: edani-realm", rollback)
        self.assertNotIn("value: realm-management", rollback)
        self.assertIn("activeDeadlineSeconds: 900", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)

    # ------------------------------------------------------------------
    # In-image tests: the reconciler runs inside the pinned Keycloak image,
    # which is not a general-purpose shell image. These exercise the real
    # script inside the real image against a kcadm stub, so a missing binary
    # or a broken filter fails here, not on a PostSync hook ~75 min later.
    # ------------------------------------------------------------------

    @in_keycloak_image
    def test_ensure_grants_exact_match_inside_keycloak_image(self):
        """Full ensure run inside quay.io/keycloak/keycloak:26.6.2 with the
        substring-match fixture: the exact-match filter must pick the exact
        uuids (not the near-miss siblings) and write exactly the impersonation
        role mapping."""
        rc, out, err, log = _run_in_image(CLIENTS_FIXTURE, "", "ensure")
        self.assertEqual(rc, 0, f"script failed in image: rc={rc}\nstdout={out}\nstderr={err}\nlog={log}")
        self.assertIn('"present":true', out)
        self.assertIn('"changed":true', out)
        # The service-account client resolved to the EXACT uuid, never the
        # admin-keycloack-server-v2 near-miss.
        self.assertIn(f"get clients/{SA_UUID} --fields enabled", log)
        self.assertNotIn(SA_UUID.replace("11111111", "22222222"), log)
        # The mapping client resolved to the EXACT edani-realm uuid, never
        # edani-realm-old. The grant POSTs the role REPRESENTATION to the
        # role-mappings COLLECTION — no "/roles" suffix (the server answers
        # 404 there, SC-1215 third failure) — and never the near-miss client.
        self.assertIn(f"create users/sa-user-uuid/role-mappings/clients/{MAPPING_UUID} ", log)
        self.assertNotIn(f"role-mappings/clients/{MAPPING_UUID}/roles", log)
        self.assertNotIn(MAPPING_UUID.replace("33333333", "44444444"), log)
        self.assertIn(
            f'[{{"id":"role-impersonation-uuid","name":"impersonation",'
            f'"clientRole":true,"composite":false,"containerId":"{MAPPING_UUID}"}}]',
            log,
        )

    @in_keycloak_image
    def test_ensure_applies_grant_when_server_answers_204_inside_keycloak_image(self):
        """The live collection answers the successful grant with 204 No
        Content (measured 2026-09-24): with the stub replaying exactly that,
        the reconciler must report the grant as applied, POSTing the role
        representation to the collection itself."""
        rc, out, err, log = _run_in_image(
            CLIENTS_FIXTURE, "", "ensure",
            {"create_status": "204 No Content\n"},
        )
        self.assertEqual(rc, 0, f"script failed on 204: rc={rc}\nstdout={out}\nstderr={err}\nlog={log}")
        self.assertIn('"present":true', out)
        self.assertIn('"changed":true', out)
        self.assertIn(f"create users/sa-user-uuid/role-mappings/clients/{MAPPING_UUID} ", log)
        self.assertIn('"name":"impersonation"', log)

    @in_keycloak_image
    def test_ensure_400_reports_status_and_body_inside_keycloak_image(self):
        """When the server rejects the grant (measured failure class: 404/400
        with a JSON error body), the failure message must carry the response
        status AND the body error — the third apply died with the response
        swallowed (SC-1215). The stub replays kcadm's measured -H output for
        a 400."""
        rc, out, err, log = _run_in_image(
            CLIENTS_FIXTURE, "", "ensure",
            {"create_status": "400 Bad Request\n",
             "create_error": "Role not found\n"},
        )
        self.assertNotEqual(rc, 0, f"script wrongly succeeded: stdout={out}\nlog={log}")
        self.assertIn("failed to map impersonation (edani-realm)", err)
        # Response status line and body error, as kcadm -H prints them.
        self.assertIn("400 Bad Request", err)
        self.assertIn("Role not found", err)
        # Fails closed: no success line, and the mapping was never applied.
        self.assertNotIn('"present":true', out)

    @in_keycloak_image
    def test_audit_passes_when_role_already_mapped_inside_keycloak_image(self):
        rc, out, err, log = _run_in_image(CLIENTS_FIXTURE, "impersonation\n", "audit")
        self.assertEqual(rc, 0, f"stdout={out}\nstderr={err}\nlog={log}")
        self.assertIn('"present":true', out)
        # audit must be read-only: no create/delete reached the server.
        self.assertNotIn("create users/", log)
        self.assertNotIn("delete users/", log)

    @in_keycloak_image
    def test_rollback_removes_grant_and_verifies_absent_inside_keycloak_image(self):
        """SC-1215 retirement, the pinned behavior of the retire Job: with the
        mapping present (GET shows the role), MODE=rollback must DELETE it
        from the role-mappings collection — the role representation body, no
        "/roles" suffix — and READ THE COLLECTION AGAIN to verify the role is
        gone before reporting present:false. The stub replays the real
        server: its 204 delete mutates the mapped-roles fixture, so the
        post-delete GET proves the verification path ran against mutated
        state, not against a hardcoded success."""
        rc, out, err, log = _run_in_image(CLIENTS_FIXTURE, "impersonation\n", "rollback")
        self.assertEqual(rc, 0, f"script failed in image: rc={rc}\nstdout={out}\nstderr={err}\nlog={log}")
        self.assertIn('"present":false', out)
        self.assertNotIn('"present":true', out)
        # DELETE hits the collection itself with the role representation body.
        self.assertIn(f"delete users/sa-user-uuid/role-mappings/clients/{MAPPING_UUID} ", log)
        self.assertNotIn(f"role-mappings/clients/{MAPPING_UUID}/roles", log)
        self.assertNotIn(MAPPING_UUID.replace("33333333", "44444444"), log)
        self.assertIn('"name":"impersonation"', log)
        # Verified, not trusted: the collection is read before AND after the
        # DELETE (pre-check + post-verification).
        self.assertEqual(
            log.count(f"get users/sa-user-uuid/role-mappings/clients/{MAPPING_UUID}"), 2,
        )
        # The retire never grants: nothing was created by this run.
        self.assertNotIn("create users/", log)

    @in_keycloak_image
    def test_rollback_is_idempotent_when_already_absent_inside_keycloak_image(self):
        """Re-running the retire Job (selfHeal re-creation) or the manual
        rollback after the mapping is gone must be a read-only no-op success:
        present:false, exit 0, no write ever reaches the server."""
        rc, out, err, log = _run_in_image(CLIENTS_FIXTURE, "", "rollback")
        self.assertEqual(rc, 0, f"rollback not idempotent: rc={rc}\nstdout={out}\nstderr={err}\nlog={log}")
        self.assertIn('"present":false', out)
        self.assertNotIn("delete users/", log)
        self.assertNotIn("create users/", log)

    @in_keycloak_image
    def test_near_miss_only_fixture_fails_closed_inside_keycloak_image(self):
        """The substring query returns the -v2 near-miss but no exact row:
        the reconciler must fail closed with the full diagnostic, never grant
        against the wrong client."""
        rc, out, err, log = _run_in_image(CLIENTS_FIXTURE_NO_EXACT, "", "audit")
        self.assertNotEqual(rc, 0, f"script wrongly succeeded: stdout={out}\nlog={log}")
        self.assertIn("expected exactly one client clientId=admin-keycloack-server", err)
        self.assertIn("exact=0", err)
        self.assertIn("substring=1", err)
        self.assertIn("admin-keycloack-server-v2", err)
        # Nothing was written: the failure happened before any grant.
        self.assertNotIn("create users/", log)
        self.assertNotIn("delete users/", log)

    # ------------------------------------------------------------------
    # Static audit: every external command the script invokes must exist in
    # the image it runs in. This is the guard that would have caught the awk
    # failure on the day #163 merged, instead of on the next sync wave.
    # ------------------------------------------------------------------

    SHELL_KEYWORDS = {
        "if", "then", "else", "elif", "fi", "case", "esac", "while", "until",
        "for", "do", "done", "in", "function", "select", "time",
    }
    SHELL_BUILTINS = {
        "printf", "read", "set", "umask", "trap", "exit", "return", "break",
        "continue", "export", "unset", "local", "eval", "shift", "test",
        "command", ":", "[", "cd", "echo", "exec", "wait", "jobs",
    }

    def _external_commands(self, text):
        """Command-position tokens of a POSIX shell script: the first word of
        every fragment after a command separator, minus comments, function
        names, keywords, builtins and assignments. The KCADM variable resolves
        to the script's default absolute kcadm.sh path."""
        funcs = set(re.findall(r"(?m)^([A-Za-z_]\w*)\s*\(\)", text))
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        # Case-pattern prefixes ("ensure|audit|rollback)" or "*)") are labels,
        # not commands; blank them out but keep whatever follows the ")".
        code = re.sub(
            r"(?m)^(\s*(?:\*|[A-Za-z_]\w*)(?:\|(?:\*|[A-Za-z_]\w*))*\))",
            lambda m: " " * len(m.group(1)),
            code,
        )
        cmds = set()
        for frag in re.split(r"\$\(|[|;&\n]", code):
            parts = frag.split()
            if not parts:
                continue
            # "{ cmd ... }" brace blocks run cmd at command position.
            tok = parts[1] if parts[0] == "{" and len(parts) > 1 else parts[0]
            tok = tok.strip("\"'").rstrip("()")
            if re.fullmatch(r"\$\{?KCADM\}?", tok):
                cmds.add("/opt/keycloak/bin/kcadm.sh")
                continue
            if not tok or not tok[0].isalpha():
                continue
            if "=" in tok:
                continue
            if tok in self.SHELL_KEYWORDS or tok in self.SHELL_BUILTINS or tok in funcs:
                continue
            cmds.add(tok)
        return cmds

    @in_keycloak_image
    def test_every_external_command_exists_in_the_keycloak_image(self):
        cmds = self._external_commands(SCRIPT.read_text())
        # Sanity: the extraction must actually see the commands the script is
        # known to use, or the audit is vacuous.
        for expected in {"sed", "grep", "wc", "tr", "cut", "rm", "sleep",
                         "/opt/keycloak/bin/kcadm.sh"}:
            self.assertIn(expected, cmds, f"audit extraction lost {expected}")
        probe = (
            'for c in "$@"; do command -v "$c" >/dev/null 2>&1 '
            '&& echo "OK $c" || echo "MISSING $c"; done'
        )
        proc = subprocess.run(
            [DOCKER, "run", "--rm", "--entrypoint", "/bin/sh", IMAGE,
             "-c", probe, "sh"] + sorted(cmds),
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        missing = [
            line.split(" ", 1)[1] for line in proc.stdout.splitlines()
            if line.startswith("MISSING ")
        ]
        self.assertEqual(
            missing, [],
            f"binaries invoked by the reconciler but absent from {IMAGE}: "
            f"{', '.join(missing)} — the PostSync job will die with "
            f"'command not found' (SC-1215 awk regression class)",
        )


if __name__ == "__main__":
    unittest.main()
