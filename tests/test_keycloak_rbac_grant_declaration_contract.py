"""SC-4414: every grant applied by this repo must be declared in the catalog.

The keycloak-role-drift sweep fails the live realm whenever a role or grant
exists there without its entry in ROLES.yaml / PRINCIPALS.md (SC-4369: four
ops-watch Requests in 18 days, every one of them a grant that landed by Admin
API or by a reconciler before — or without — its declaration). The README
prose said "the same PR"; nothing enforced it. This test is that enforcement:

* the tree check walks every Job/CronJob manifest under platform/keycloak-next
  that declares or applies a grant (grant/revoke env parameters, or a command
  script that calls add-roles / grant_missing_roles / delete-roles) and fails
  if any role literal it references is missing from ROLES.yaml, or any grantee
  literal is missing from PRINCIPALS.md. A PR that adds a grant without its
  declaration fails here; the same PR that declares the entry in ROLES.yaml /
  PRINCIPALS.md passes — declaration and concession in one PR, by construction.
* the negative test drives the same checker against a fixture tree with an
  undeclared role and an undeclared grantee and requires it to report both,
  so the guard cannot rot into a no-op.

Realm-management CLIENT roles (impersonation, view-realm, ...) are not realm
roles: verify-role-catalog.py does not sweep them and neither does this check;
they live in CLIENT_ROLE_ALLOWLIST.

Stdlib only, like the rest of the keycloak-rbac-contract job.
"""

import json
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"
sys.path.insert(0, str(BASE / "scripts"))

import kc_rbac  # noqa: E402  (repo's own catalog loader)

# realm-management client roles granted by the auditor and impersonation
# reconcilers: client roles, outside the realm-role catalog and its sweep.
CLIENT_ROLE_ALLOWLIST = {
    "impersonation",
    "query-groups",
    "query-users",
    "view-realm",
    "view-users",
}

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ROLE_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*(:[a-z0-9][a-z0-9._-]*)?$")
GRANTEE_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9._@-]*$")
ROLE_ENV_RE = re.compile(r"ROLE|GRANT|GRANTEE")
GRANTEE_ENV_RE = re.compile(r"SERVICE_ACCOUNTS|USER_NAME|GRANTEE")
GRANT_CALL_RE = re.compile(r"add-roles|grant_missing_roles|delete-roles")
COMMAND_RE = re.compile(r'command: \["/bin/sh", "/opt/bootstrap/([a-z0-9._-]+\.sh)"\]')
SOURCE_RE = re.compile(r'^\.\s+"\$\{0%/\*\}/([a-z0-9._-]+\.sh)"', re.M)


def env_pairs(manifest_text):
    """(name, value) of every literal env entry, both flow and block styles."""
    pairs = []
    for m in re.finditer(r"- \{ name: ([A-Z0-9_]+), value: ([^}\n]+) \}", manifest_text):
        pairs.append((m.group(1), m.group(2).strip()))
    for m in re.finditer(r"^\s*- name: ([A-Z0-9_]+)\n\s+value: (.+)$", manifest_text, re.M):
        pairs.append((m.group(1), m.group(2).strip()))
    return pairs


def script_assignments(text):
    """(name, value) of literal uppercase assignments, with or without ${VAR:-default}."""
    pairs = []
    for m in re.finditer(r'^([A-Z][A-Z0-9_]*)="\$\{[A-Z0-9_]+:-([^}]*)\}"', text, re.M):
        pairs.append((m.group(1), m.group(2)))
    for m in re.finditer(r'^([A-Z][A-Z0-9_]*)="([^"$]*)"', text, re.M):
        pairs.append((m.group(1), m.group(2)))
    return pairs


def sourced_scripts(script):
    """The script plus everything it sources, transitively."""
    texts, todo = {}, [script]
    while todo:
        s = todo.pop()
        if s.name in texts:
            continue
        t = s.read_text()
        texts[s.name] = t
        for m in SOURCE_RE.finditer(t):
            lib = s.parent / m.group(1)
            if lib.exists() and lib.name not in texts:
                todo.append(lib)
    return texts


def grant_surface(base):
    """{manifest: {script_name: text}} of Job/CronJob manifests that declare or apply a grant."""
    scripts_dir = base / "scripts"
    out = {}
    for manifest in sorted(base.rglob("*.yaml")):
        if manifest.name == "ROLES.yaml":
            continue
        text = manifest.read_text()
        if "kind: Job" not in text and "kind: CronJob" not in text:
            continue
        texts = {}
        m = COMMAND_RE.search(text)
        if m and (scripts_dir / m.group(1)).exists():
            texts = sourced_scripts(scripts_dir / m.group(1))
        declares = any(
            ROLE_ENV_RE.search(n) or GRANTEE_ENV_RE.search(n) for n, _ in env_pairs(text)
        )
        applies = any(GRANT_CALL_RE.search(t) for t in texts.values())
        if declares or applies:
            out[manifest] = texts
    return out


def find_violations(base):
    """Every role/grantee literal of the grant surface missing from the catalog."""
    catalog = json.loads((base / "ROLES.yaml").read_text())
    declared_roles = {r["name"] for r in catalog["roles"]}
    declared_principals = {
        p["username"] for p in kc_rbac.load_json_block(base / "PRINCIPALS.md")["principals"]
    }
    violations = []

    def check_role(token, origin):
        if UUID_RE.match(token) or not ROLE_TOKEN_RE.match(token):
            return
        if token not in declared_roles and token not in CLIENT_ROLE_ALLOWLIST:
            violations.append(f"{origin}: role {token!r} not declared in ROLES.yaml")

    def check_grantee(token, origin):
        if UUID_RE.match(token) or not GRANTEE_TOKEN_RE.match(token):
            return
        if token not in declared_principals:
            violations.append(f"{origin}: grantee {token!r} not declared in PRINCIPALS.md")

    def check_pairs(pairs, origin):
        for name, value in pairs:
            is_role = bool(ROLE_ENV_RE.search(name))
            is_grantee = bool(GRANTEE_ENV_RE.search(name))
            if not is_role and not is_grantee:
                continue
            for token in value.split(","):
                token = token.strip()
                if not token:
                    continue
                if "=" in token:
                    role, grantee = token.split("=", 1)
                    check_role(role.strip(), origin)
                    check_grantee(grantee.strip(), origin)
                elif is_role and not is_grantee:
                    check_role(token, origin)
                elif is_grantee and not is_role:
                    check_grantee(token, origin)
                elif ROLE_TOKEN_RE.match(token):
                    check_role(token, origin)
                else:
                    check_grantee(token, origin)

    for manifest, texts in grant_surface(base).items():
        origin = str(manifest.relative_to(base))
        check_pairs(env_pairs(manifest.read_text()), origin)
        for script_name, script_text in texts.items():
            check_pairs(script_assignments(script_text), f"{origin}<-{script_name}")
    return violations


class GrantDeclarationContractTest(unittest.TestCase):
    def test_grant_surface_is_not_empty(self):
        # The guard must actually see the reconcilers: a silent empty surface
        # would make the tree check below a no-op.
        surface = grant_surface(BASE)
        names = {m.name for m in surface}
        for expected in (
            "agentgateway-read-grants-job.yaml",
            "agentgateway-domain-roles-job.yaml",
            "agentgateway-write-grant-daniel-job.yaml",
            "photos-confirm-delete-grant-daniel-job.yaml",
        ):
            self.assertIn(expected, names)
        self.assertGreaterEqual(len(surface), 20)

    def test_every_grant_is_declared_in_the_catalog(self):
        violations = find_violations(BASE)
        self.assertEqual(
            violations,
            [],
            "grant without declaration (SC-4414: declare it in ROLES.yaml / "
            "PRINCIPALS.md in this same PR):\n" + "\n".join(sorted(violations)),
        )


class GuardFiresTest(unittest.TestCase):
    """The checker must reject the SC-4304 / SC-3805 shape, not just pass trunk."""

    FIXTURE_ROLES = {
        "schema": "keycloak-role-catalog/v1",
        "realm": "edani",
        "roles": [{"name": "agentgateway-write", "status": "active", "grantees": []}],
    }
    FIXTURE_PRINCIPALS = """# principals

```json
{"principals": [{"username": "service-account-known", "realm_roles": []}]}
```
"""
    FIXTURE_JOB = """apiVersion: batch/v1
kind: Job
metadata:
  name: grant-nueva-ruta
  namespace: keycloak
spec:
  template:
    spec:
      containers:
        - name: reconcile
          command: ["/bin/sh", "/opt/bootstrap/grant-nueva-ruta.sh"]
          env:
            - name: ROLE_NAME
              value: agentgateway-read:nueva-ruta
            - name: USER_NAME
              value: alguien@e-dani.com
"""
    FIXTURE_SCRIPT = """#!/bin/sh
ROLE_NAME="${ROLE_NAME:-agentgateway-read:nueva-ruta}"
"${KCADM}" add-roles -r edani --rolename "${ROLE_NAME}"
"""

    def test_undeclared_role_and_grantee_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            (base / "scripts").mkdir()
            (base / "ROLES.yaml").write_text(json.dumps(self.FIXTURE_ROLES))
            (base / "PRINCIPALS.md").write_text(self.FIXTURE_PRINCIPALS)
            (base / "grant-nueva-ruta-job.yaml").write_text(self.FIXTURE_JOB)
            (base / "scripts" / "grant-nueva-ruta.sh").write_text(self.FIXTURE_SCRIPT)
            violations = find_violations(base)
        joined = "\n".join(violations)
        self.assertIn("role 'agentgateway-read:nueva-ruta' not declared in ROLES.yaml", joined)
        self.assertIn("grantee 'alguien@e-dani.com' not declared in PRINCIPALS.md", joined)

    def test_declared_grant_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            (base / "scripts").mkdir()
            roles = json.loads(json.dumps(self.FIXTURE_ROLES))
            roles["roles"].append(
                {"name": "agentgateway-read:nueva-ruta", "status": "active", "grantees": ["alguien@e-dani.com"]}
            )
            (base / "ROLES.yaml").write_text(json.dumps(roles))
            (base / "PRINCIPALS.md").write_text(
                self.FIXTURE_PRINCIPALS.replace(
                    '{"username": "service-account-known", "realm_roles": []}',
                    '{"username": "service-account-known", "realm_roles": []}, '
                    '{"username": "alguien@e-dani.com", "realm_roles": ["agentgateway-read:nueva-ruta"]}',
                )
            )
            (base / "grant-nueva-ruta-job.yaml").write_text(self.FIXTURE_JOB)
            (base / "scripts" / "grant-nueva-ruta.sh").write_text(self.FIXTURE_SCRIPT)
            self.assertEqual(find_violations(base), [])


if __name__ == "__main__":
    unittest.main()
