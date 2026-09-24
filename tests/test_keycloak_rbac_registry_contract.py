"""INFRA-247 (INFRA-219 C2): the registry contract of ROLES.yaml between trunk and branch.

check-catalog-evolution.py is what the keycloak-rbac-contract CI job runs on
every pull_request against the trunk copy of the catalog. Two sample catalogs
stand for trunk and branch.
"""

import contextlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "platform" / "keycloak-next" / "scripts"
CHECK = SCRIPTS / "check-catalog-evolution.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

_spec = importlib.util.spec_from_file_location("check_catalog_evolution", CHECK)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def role(name, status="active"):
    return {
        "name": name,
        "status": status,
        "meaning": f"rol de ejemplo {name}",
        "grantees": [],
        "privilege": {"allows": "algo", "denies": "lo demás"},
        "origin": "test",
    }


TRUNK = [role("agentgateway-read:weight"), role("agentgateway-write:sauvage", "deprecated"), role("synapse-sre-m2m")]


class CatalogEvolutionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, roles):
        path = self.dir / name
        path.write_text(json.dumps({"schema": "keycloak-role-catalog/v1", "realm": "edani", "roles": roles}))
        return path

    def run_check(self, head_roles, base_roles=TRUNK):
        base = self.write("base.yaml", base_roles) if base_roles is not None else self.dir / "absent.yaml"
        head = self.write("head.yaml", head_roles)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check.main(["--base", str(base), "--head", str(head)])
        return code, out.getvalue().splitlines()

    def test_unchanged_catalog_passes(self):
        code, lines = self.run_check(TRUNK)
        self.assertEqual((code, lines), (0, ["OK: 3 roles del tronco presentes, 0 borrados, 0 deprecated reactivados"]))

    def test_new_role_passes(self):
        code, lines = self.run_check(TRUNK + [role("agentgateway-read:nueva")])
        self.assertEqual(code, 0, lines)

    def test_active_to_deprecated_passes(self):
        head = [role("agentgateway-read:weight", "deprecated")] + TRUNK[1:]
        code, lines = self.run_check(head)
        self.assertEqual(code, 0, lines)

    def test_deleted_role_fails(self):
        code, lines = self.run_check([r for r in TRUNK if r["name"] != "synapse-sre-m2m"])
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["CONTRATO: rol synapse-sre-m2m está en el catálogo del tronco y la rama lo borra (se depreca, no se borra)"])

    def test_deprecated_back_to_active_fails(self):
        head = [TRUNK[0], role("agentgateway-write:sauvage", "active"), TRUNK[2]]
        code, lines = self.run_check(head)
        self.assertEqual(code, 1)
        self.assertEqual(lines, ["CONTRATO: rol agentgateway-write:sauvage es deprecated en el tronco y la rama lo vuelve a active"])

    def test_trunk_without_catalog_is_skipped_explicitly(self):
        code, lines = self.run_check(TRUNK, base_roles=None)
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("SKIP: el tronco no tiene"), lines)

    def test_broken_branch_catalog_exits_2(self):
        code, lines = self.run_check([role("x"), role("x")])
        self.assertEqual(code, 2)
        self.assertIn("duplicado", lines[0])

    def test_cli_entrypoint_against_the_repo_catalog(self):
        repo_catalog = ROOT / "platform" / "keycloak-next" / "ROLES.yaml"
        completed = subprocess.run(
            [sys.executable, str(CHECK), "--base", str(repo_catalog)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(completed.stdout.startswith("OK: "), completed.stdout)

    def test_ci_job_runs_the_check_on_pull_requests_against_the_trunk(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        job = workflow.split("  keycloak-rbac-contract:", 1)[1].split("\n  velero-operability-contract:", 1)[0]
        self.assertIn("if: github.event_name == 'pull_request'", job)
        self.assertIn('git fetch --depth=1 origin "$GITHUB_BASE_REF"', job)
        self.assertIn("check-catalog-evolution.py --base", job)
        self.assertIn("SKIP:", job)


if __name__ == "__main__":
    unittest.main()
