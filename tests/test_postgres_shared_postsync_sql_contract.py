"""INFRA-1599: guardia CI del SQL de los Job PostSync de postgres-shared.

Antecedente medido (INFRA-1369): tres líneas de comentario `#` dentro del block
scalar SQL que recibe psql. psql comenta con `--`, no con `#`: error de
sintaxis → BackoffLimitExceeded en cada sync → `operationState: Failed`
(incidente ARGO-20896, SC-6618). El fix de los `#` ya está fusionado
(k8s-infra#645); esta guardia evita que la clase de bug vuelva a entrar.

Segunda mitad del contrato (SC-6473): el 24-11 el Job
`postgres-shared-role-settings` murió al primer error mientras el primario
estaba saturado (SC-6471/SC-6543) porque, a diferencia de sus hermanos
agent-transcripts-schema.yaml y catalogo-schema.yaml, no tenía bucle de espera.
El test fija que el Job tiene el bucle de reintento de conexión (patrón de los
hermanos: sonda `SELECT 1`, 60 intentos × 5 s) antes de agotar el backoff, y
que el SQL conserva su semántica (los ALTER/RESET/CONNECTION LIMIT y la
limpieza del backlog siguen todos ahí).

Positiva: el SQL real de los tres Job del directorio pasa. Negativa: el mismo
comprobador falla si se reintroduce una línea de comentario `#` en el SQL, en
sus dos formas: block scalar de un ConfigMap montado con `-f` (la forma del
Job role-settings tras INFRA-1599) y argumento inline `psql -c` (la forma de
INFRA-1369).
"""

import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIR = ROOT / "databases" / "postgres-shared"
ROLE_SETTINGS = DIR / "role-settings.yaml"


def sql_strings(text):
    """SQL que el manifiesto pasa a psql: `(nombre, sql)`.

    Dos formas, las únicas del directorio:
    * claves `*.sql` de los ConfigMap (montadas en /sql y ejecutadas con
      `psql -f`);
    * argumentos que siguen a `-c` cuando el argv del contenedor arranca en
      `psql` (la forma inline de INFRA-1369).
    """
    for doc in yaml.safe_load_all(text):
        if not doc:
            continue
        kind = doc.get("kind")
        if kind == "ConfigMap":
            name = doc.get("metadata", {}).get("name", "?")
            for key, val in (doc.get("data") or {}).items():
                if key.endswith(".sql") and isinstance(val, str):
                    yield f"{name}/{key}", val
        elif kind == "Job":
            name = doc.get("metadata", {}).get("name", "?")
            containers = doc.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
            for c in containers:
                argv = list(c.get("command") or []) + list(c.get("args") or [])
                if not argv or not str(argv[0]).endswith("psql"):
                    continue
                for i, tok in enumerate(argv[:-1]):
                    if tok == "-c":
                        yield f"{name} -c[{i}]", argv[i + 1]


def hash_comment_violations(text):
    """Líneas de comentario `#` (psql no las reconoce) en el SQL del manifiesto."""
    out = []
    for name, sql in sql_strings(text):
        for n, line in enumerate(sql.splitlines(), 1):
            if line.lstrip().startswith("#"):
                out.append((name, n, line.strip()))
    return out


class TestNoHashCommentsInRealSql(unittest.TestCase):
    """Positiva: ningún Job de databases/postgres-shared/ pasa `#` a psql hoy."""

    def test_all_files_clean(self):
        for path in sorted(DIR.glob("*.yaml")):
            with self.subTest(file=path.name):
                self.assertEqual(hash_comment_violations(path.read_text()), [])


class TestGuardCatchesHashComments(unittest.TestCase):
    """Negativa: la guardia falla si la clase de bug de INFRA-1369 vuelve."""

    def test_configmap_block_scalar(self):
        """`#` reintroducido en el block scalar SQL del Job role-settings."""
        docs = [d for d in yaml.safe_load_all(ROLE_SETTINGS.read_text()) if d]
        cm = next(d for d in docs if d["kind"] == "ConfigMap")
        cm["data"]["setup.sql"] = "# comentario prohibido\n" + cm["data"]["setup.sql"]
        v = hash_comment_violations(yaml.safe_dump_all(docs))
        self.assertEqual(len(v), 1, v)
        self.assertIn("setup.sql", v[0][0])
        self.assertIn("comentario prohibido", v[0][2])

    def test_inline_psql_c(self):
        """`#` en un `-c` inline (la forma exacta de INFRA-1369)."""
        manifest = {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": "job-inline"},
            "spec": {"template": {"spec": {"containers": [{
                "name": "psql",
                "command": ["psql", "-v", "ON_ERROR_STOP=1",
                            "-c", "SELECT 1;\n# otra línea prohibida\nSELECT 2;"],
            }]}}},
        }
        v = hash_comment_violations(yaml.safe_dump(manifest))
        self.assertEqual(len(v), 1, v)
        self.assertIn("otra línea prohibida", v[0][2])

    def test_dash_dash_comments_are_fine(self):
        """`--` sí es comentario SQL: la guardia no lo marca."""
        manifest = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "cm"},
            "data": {"setup.sql": "-- comentario SQL válido\nSELECT 1;\n"},
        }
        self.assertEqual(hash_comment_violations(yaml.safe_dump(manifest)), [])


class TestRoleSettingsWaitLoop(unittest.TestCase):
    """SC-6473: el Job tolera la indisponibilidad transitoria del primario."""

    def setUp(self):
        self.docs = [d for d in yaml.safe_load_all(ROLE_SETTINGS.read_text()) if d]
        self.job = next(d for d in self.docs
                        if d["kind"] == "Job"
                        and d["metadata"]["name"] == "postgres-shared-role-settings")
        self.container = self.job["spec"]["template"]["spec"]["containers"][0]
        self.script = self.container["command"][2]

    def test_wait_loop_pattern_of_the_siblings(self):
        # Mismo patrón que agent-transcripts-schema.yaml y catalogo-schema.yaml.
        self.assertEqual(self.container["command"][:2], ["/bin/bash", "-c"])
        self.assertIn("for i in $(seq 1 60)", self.script)
        self.assertIn("sleep 5", self.script)
        self.assertIn("SELECT 1", self.script)
        self.assertIn("psql -v ON_ERROR_STOP=1 -f /sql/setup.sql", self.script)

    def test_sql_mounted_from_configmap(self):
        cm_name = self.job["spec"]["template"]["spec"]["volumes"][0]["configMap"]["name"]
        cm = next(d for d in self.docs if d["kind"] == "ConfigMap"
                  and d["metadata"]["name"] == cm_name)
        self.assertIn("setup.sql", cm["data"])
        mounts = [m["mountPath"] for m in self.container["volumeMounts"]]
        self.assertIn("/sql", mounts)

    def test_semantics_preserved(self):
        """El SQL sigue siendo los mismos ALTER idempotentes + limpieza."""
        cm = next(d for d in self.docs if d["kind"] == "ConfigMap")
        sql = cm["data"]["setup.sql"]
        self.assertIn("ALTER ROLE keep SET idle_in_transaction_session_timeout = '5min';", sql)
        self.assertEqual(sql.count("SET idle_session_timeout = '15min';"), 26)
        self.assertIn("ALTER ROLE skirmshop RESET idle_session_timeout;", sql)
        self.assertIn("ALTER ROLE skirmbooks_ui_app RESET idle_session_timeout;", sql)
        self.assertIn("ALTER ROLE hindsight CONNECTION LIMIT 100;", sql)
        self.assertIn("ALTER ROLE dgxskills CONNECTION LIMIT 5;", sql)
        self.assertIn("pg_terminate_backend(pid)", sql)
        self.assertIn("state = 'idle'", sql)
        # La limpieza nunca toca idle in transaction.
        self.assertNotIn("idle in transaction'", sql)

    def test_backoff_like_the_siblings(self):
        self.assertEqual(self.job["spec"]["backoffLimit"], 5)


if __name__ == "__main__":
    unittest.main()
