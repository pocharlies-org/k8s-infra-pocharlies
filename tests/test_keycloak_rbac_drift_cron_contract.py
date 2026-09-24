"""INFRA-250 (INFRA-219 C5): contract of the keycloak-role-drift CronJob.

Two halves:

* the manifest, read as text (no PyYAML in the keycloak-rbac-contract job):
  pinned image equal to the one of storage/longhorn/system-backup-cron.yaml,
  no keycloak-bootstrap / keycloak-automation, history/deadline/backoff
  limits, ks5 placement (never the Sparks), a restricted pod, and egress only
  to keycloak:8080 plus DNS;
* the entrypoint, run end to end: the files of the keycloak-role-drift
  configMapGenerator are laid out exactly as the ConfigMap mounts them, the
  auditor credential is two files, and the real verifiers talk to a stdlib
  fake Keycloak on 127.0.0.1 built from ROLES.yaml and PRINCIPALS.md.
"""

import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
SCRIPTS = BASE / "scripts"
CRON = BASE / "keycloak-role-drift-cron.yaml"
KUSTOMIZATION = BASE / "kustomization.yaml"
BACKUP_CRON = ROOT / "storage" / "longhorn" / "system-backup-cron.yaml"
ENTRYPOINT = SCRIPTS / "keycloak-role-drift.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"

sys.path.insert(0, str(SCRIPTS))
import kc_rbac  # noqa: E402

CLIENT_ID = "keycloak-rbac-auditor"
CLIENT_SECRET = "fake-secret-not-real"
SA_PREFIX = "service-account-"


def manifest_lines():
    """The CronJob manifest without comment lines."""
    return [line for line in CRON.read_text().splitlines() if not line.lstrip().startswith("#")]


def manifest_text():
    return "\n".join(manifest_lines())


def int_field(name):
    values = re.findall(rf"^\s*{name}:\s*(\d+)\s*$", manifest_text(), re.MULTILINE)
    return [int(v) for v in values]


def generator_files(name):
    """(key, source) pairs of one configMapGenerator entry of kustomization.yaml."""
    lines = KUSTOMIZATION.read_text().splitlines()
    start = lines.index(f"  - name: {name}")
    pairs, in_files = [], False
    for line in lines[start + 1:]:
        if line.startswith("  - name: ") or not line.startswith("    "):
            break
        if line.strip() == "files:":
            in_files = True
            continue
        if in_files and line.startswith("      - "):
            item = line.strip()[2:]
            key, _, source = item.partition("=")
            pairs.append((key, source or key) if source else (pathlib.PurePath(key).name, key))
        elif not line.startswith("      "):
            in_files = False
    return pairs


class CronManifestContractTest(unittest.TestCase):
    def test_image_is_the_pinned_python_of_the_longhorn_backup_cron(self):
        pattern = r"image:\s*(python:3\.13\.5-alpine3\.22@sha256:[0-9a-f]{64})"
        reference = re.findall(pattern, BACKUP_CRON.read_text())
        ours = re.findall(pattern, manifest_text())
        self.assertEqual(len(reference), 1)
        self.assertEqual(ours, reference)
        self.assertEqual(len(re.findall(r"^\s*image:", manifest_text(), re.MULTILINE)), 1)

    def test_no_admin_credential_and_no_kcadm(self):
        text = manifest_text()
        for forbidden in ("keycloak-bootstrap", "keycloak-automation", "KC_BOOTSTRAP", "kcadm", "quay.io/keycloak"):
            self.assertNotIn(forbidden, text)
        self.assertIn("secretName: keycloak-rbac-auditor", text)
        self.assertIn("KC_CLIENT_ID_FILE, value: /var/run/secrets/keycloak-rbac-auditor/client_id", text)
        self.assertIn("KC_CLIENT_SECRET_FILE, value: /var/run/secrets/keycloak-rbac-auditor/client_secret", text)
        self.assertNotIn("secretKeyRef", text)
        self.assertNotIn("envFrom", text)

    def test_schedule_limits_history_and_deadline(self):
        text = manifest_text()
        self.assertIn("kind: CronJob", text)
        self.assertIn("name: keycloak-role-drift\n", text + "\n")
        self.assertIn('schedule: "*/15 * * * *"', text)
        self.assertIn("concurrencyPolicy: Forbid", text)
        self.assertEqual(int_field("backoffLimit"), [0])
        (failed,) = int_field("failedJobsHistoryLimit")
        self.assertGreaterEqual(failed, 1)
        (ttl,) = int_field("ttlSecondsAfterFinished")
        self.assertGreaterEqual(ttl, 3600)
        (deadline,) = int_field("activeDeadlineSeconds")
        # K8sCronJobFailed looks back 4 h: a longer deadline would hide the failure.
        self.assertLess(deadline, 4 * 3600)
        self.assertNotIn("suspend: true", text)

    def test_placement_is_ks5_never_the_sparks(self):
        text = manifest_text()
        self.assertIn("node-pool: ks5-nvme", text)
        self.assertIn("key: node-role.kubernetes.io/control-plane", text)
        for node in ("nvidia-dgx", "gx10-ec3d", "nvidia.com/gpu"):
            self.assertNotIn(node, text)

    def test_pod_is_restricted(self):
        text = manifest_text()
        for needle in (
            "automountServiceAccountToken: false",
            "enableServiceLinks: false",
            "runAsNonRoot: true",
            "type: RuntimeDefault",
            "allowPrivilegeEscalation: false",
            "readOnlyRootFilesystem: true",
            'capabilities: { drop: ["ALL"] }',
            "restartPolicy: Never",
        ):
            self.assertIn(needle, text)
        self.assertNotIn("privileged: true", text)
        self.assertNotIn("hostNetwork", text)

    def test_egress_only_to_keycloak_and_dns(self):
        text = manifest_text()
        policy = text[text.index("kind: NetworkPolicy"):]
        self.assertIn("app.kubernetes.io/component: keycloak-role-drift", policy)
        self.assertIn("policyTypes: [Egress]", policy)
        ports = sorted(set(int(p) for p in re.findall(r"port:\s*(\d+)", policy)))
        self.assertEqual(ports, [53, 8080])
        self.assertIn("matchLabels: { app: keycloak }", policy)
        self.assertIn("k8s-app: kube-dns", policy)
        self.assertNotIn("ipBlock", policy)
        self.assertIn("KEYCLOAK_URL, value: http://keycloak.keycloak.svc.cluster.local", text)

    def test_configmap_carries_the_verifiers_and_their_data(self):
        kustomization = KUSTOMIZATION.read_text()
        self.assertIn("  - keycloak-role-drift-cron.yaml\n", kustomization)
        keys = sorted(key for key, _ in generator_files("keycloak-role-drift"))
        self.assertEqual(keys, sorted([
            "keycloak-role-drift.sh", "kc_rbac.py", "verify-role-catalog.py",
            "verify-principals.py", "ROLES.yaml", "PRINCIPALS.md",
        ]))
        for _, source in generator_files("keycloak-role-drift"):
            self.assertTrue((BASE / source).is_file(), source)

    def test_ci_runs_this_contract(self):
        ci = CI.read_text()
        self.assertIn("python3 -m unittest discover -s tests -p 'test_keycloak_rbac_*.py'", ci)
        self.assertIn("sh -n platform/keycloak-next/scripts/keycloak-role-drift.sh", ci)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_kustomize_renders_the_cronjob(self):
        rendered = subprocess.run(["kubectl", "kustomize", str(BASE)], check=True, text=True, capture_output=True).stdout
        self.assertIn("name: keycloak-role-drift\n", rendered)
        self.assertIn("kind: CronJob", rendered)
        self.assertIn("name: keycloak-role-drift-egress", rendered)
        self.assertIn("verify-principals.py: |", rendered)


class FakeRealm:
    """Stdlib Keycloak: token endpoint plus the read-only admin API of both verifiers."""

    def __init__(self, roles, usernames):
        # roles: {name: {"users": [...], "groups": [...], "composites": [...]}}
        self.roles = roles
        self.usernames = sorted(usernames)
        self.token_status = 200
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, payload):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                form = self.rfile.read(length).decode()
                fake.requests.append(("POST", self.path))
                if self.path != "/realms/edani/protocol/openid-connect/token":
                    return self._send(404, {"error": "not found"})
                if fake.token_status != 200:
                    return self._send(fake.token_status, {"error": "unauthorized_client"})
                expected = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
                if self.headers.get("Authorization") != f"Basic {expected}" or form != "grant_type=client_credentials":
                    return self._send(401, {"error": "invalid_client"})
                return self._send(200, {"access_token": "fake-token", "token_type": "Bearer"})

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                fake.requests.append(("GET", url.path))
                if self.headers.get("Authorization") != "Bearer fake-token":
                    return self._send(401, {"error": "HTTP 401 Unauthorized"})
                query = urllib.parse.parse_qs(url.query)
                first = int(query.get("first", ["0"])[0])
                size = int(query.get("max", ["100"])[0])
                parts = [urllib.parse.unquote(p) for p in url.path.split("/")]
                if parts[:4] != ["", "admin", "realms", "edani"] or len(parts) < 5:
                    return self._send(404, {"error": "not found"})
                if parts[4] == "users" and len(parts) == 5:
                    search = query.get("username", [None])[0]
                    if search is None:
                        names = [n for n in fake.usernames if not n.startswith(SA_PREFIX)]
                    else:
                        names = [n for n in fake.usernames if search in n]
                    items = [{"id": f"id-{n}", "username": n} for n in names]
                elif parts[4] != "roles":
                    # The auditor has no view-clients: anything else is refused.
                    return self._send(403, {"error": "HTTP 403 Forbidden"})
                elif len(parts) == 5:
                    items = [{"name": name} for name in sorted(fake.roles)]
                elif len(parts) == 7 and parts[5] in fake.roles and parts[6] == "composites":
                    return self._send(200, [{"name": c, "clientRole": False} for c in fake.roles[parts[5]]["composites"]])
                elif len(parts) == 7 and parts[5] in fake.roles and parts[6] in ("users", "groups"):
                    key = "username" if parts[6] == "users" else "path"
                    items = [{key: value} for value in fake.roles[parts[5]][parts[6]]]
                else:
                    return self._send(404, {"error": "Could not find role"})
                return self._send(200, items[first:first + size])

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def realm_as_declared():
    catalog = kc_rbac.load_role_catalog(BASE / "ROLES.yaml")
    roles = {
        name: {"users": list(entry["grantees"]), "groups": [], "composites": list(entry.get("composites", []))}
        for name, entry in catalog.items()
    }
    usernames = [p["username"] for p in kc_rbac.load_json_block(BASE / "PRINCIPALS.md")["principals"]]
    return roles, usernames


class CronEntrypointTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        # The ConfigMap as mounted at /opt/rbac: one flat directory, keys as names.
        self.rbac = tmp / "rbac"
        self.rbac.mkdir()
        for key, source in generator_files("keycloak-role-drift"):
            shutil.copy(BASE / source, self.rbac / key)
        # The auditor secret as mounted (client_id, client_secret).
        self.secret = tmp / "auditor"
        self.secret.mkdir()
        (self.secret / "client_id").write_text(CLIENT_ID)
        (self.secret / "client_secret").write_text(CLIENT_SECRET)
        self.work = tmp / "work"
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_cron(self, url, **overrides):
        env = {
            "PATH": os.environ["PATH"],
            "KEYCLOAK_URL": url,
            "KC_REALM": "edani",
            "KC_CLIENT_ID_FILE": str(self.secret / "client_id"),
            "KC_CLIENT_SECRET_FILE": str(self.secret / "client_secret"),
            "RBAC_DIR": str(self.rbac),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHON": sys.executable,
            "TMPDIR": str(self.work),
        }
        env.update(overrides)
        result = subprocess.run(["sh", str(self.rbac / "keycloak-role-drift.sh")], env=env,
                                text=True, capture_output=True, timeout=120)
        self.assertNotIn(CLIENT_SECRET, result.stdout + result.stderr)
        return result.returncode, result.stdout.splitlines()

    def test_realm_as_declared_is_ok(self):
        roles, usernames = realm_as_declared()
        with FakeRealm(roles, usernames) as realm:
            code, lines = self.run_cron(realm.url)
            touched = {path for _, path in realm.requests}
        self.assertEqual(code, 0, lines)
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].startswith("OK: "), lines)
        self.assertTrue(lines[1].startswith("OK: "), lines)
        # Read-only and without view-clients: only token, roles and users.
        self.assertFalse([p for p in touched if "/clients" in p or "role-mappings" in p])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_qa_drift_is_exit_1_with_the_named_finding(self):
        # The C5 drift proof qa runs live: an undeclared agentgateway-read:* on qa-con-rol.
        roles, usernames = realm_as_declared()
        roles["agentgateway-read:gsc"]["users"].append("qa-con-rol@e-dani.com")
        with FakeRealm(roles, usernames) as realm:
            code, lines = self.run_cron(realm.url)
        self.assertEqual(code, 1, lines)
        self.assertIn("DRIFT: qa-con-rol@e-dani.com tiene agentgateway-read:gsc no declarada", lines)

    def test_group_grant_and_unowned_principal_are_drift(self):
        roles, usernames = realm_as_declared()
        roles["agentgateway-write"]["groups"].append("/edani-operators")
        with FakeRealm(roles, usernames + ["service-account-nuevo"]) as realm:
            code, lines = self.run_cron(realm.url)
        self.assertEqual(code, 1, lines)
        self.assertIn("DRIFT: grupo /edani-operators tiene agentgateway-write (R2: sin role-mapping por grupo)", lines)
        self.assertIn("DRIFT: principal service-account-nuevo existe en el realm y no tiene entrada en PRINCIPALS.md", lines)

    def test_auth_failure_is_exit_2_even_with_drift_elsewhere(self):
        roles, usernames = realm_as_declared()
        with FakeRealm(roles, usernames) as realm:
            realm.token_status = 401
            code, lines = self.run_cron(realm.url)
        self.assertEqual(code, 2, lines)
        self.assertTrue(all(line.startswith("ERROR: ") for line in lines), lines)

    def test_missing_credential_file_is_exit_2(self):
        (self.secret / "client_secret").unlink()
        code, lines = self.run_cron("http://127.0.0.1:9")
        self.assertEqual(code, 2, lines)

    def test_a_verifier_that_dies_without_verdict_is_error_not_drift(self):
        fake_python = self.work.parent / "fake-python"
        fake_python.write_text("#!/bin/sh\necho 'Traceback (most recent call last):' >&2\nexit 1\n")
        fake_python.chmod(0o755)
        code, lines = self.run_cron("http://127.0.0.1:9", PYTHON=str(fake_python))
        self.assertEqual(code, 2, lines)
        self.assertIn("ERROR: verify-role-catalog.py terminó con código 1 sin línea DRIFT:", lines)

    def test_entrypoint_only_calls_the_verifiers(self):
        source = ENTRYPOINT.read_text()
        self.assertNotIn("kcadm", source)
        self.assertNotIn("curl", source)
        self.assertIn("verify-role-catalog.py", source)
        self.assertIn("verify-principals.py", source)


if __name__ == "__main__":
    unittest.main()
