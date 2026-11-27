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

Tercera guardia del mismo fichero (INFRA-1625, regresión de la épica
INFRA-1295): el régimen de ociosas que qa valid a mano (70-qa.md C1–C4) queda
fijado como prueba de CI. Un PR futuro que quite cobertura (un `ALTER ROLE …
SET idle_session_timeout = '15min'` de más), meta un excluido en la lista o
ensanche la limpieza del backlog no puede fusionarse. La prueba lee el SQL del
ConfigMap del Job y no toca el clúster.
"""

import pathlib
import re
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


# ---------------------------------------------------------------------------
# INFRA-1625 (regresión de INFRA-1295): guardia del régimen de ociosas.
#
# Lo que qa valid a mano (70-qa.md de la épica, C1–C4) queda aquí como
# prueba automática: la lista de cubiertos del SET, los excluidos que jamás
# reciben SET ni entran en el barrido, el `keep` con su
# idle_in_transaction_session_timeout y la limpieza del backlog acotada a
# `state = 'idle'` y a los roles cubiertos. La verdad de estado es el SQL del
# ConfigMap `postgres-shared-role-settings-sql`; la prueba lo parsea y no
# habla con el clúster.
# ---------------------------------------------------------------------------

# Excluidos a propósito (comentario de cabecera de role-settings.yaml): ni
# ALTER ni terminate. synapse_adapter y los gestoria_*_app sostienen LISTEN
# sin supervisor; synapse_migration/synapse_owner son exclusión permanente por
# pg_advisory_lock; postgres y streaming_replica nunca; brain_openwebui_ro y
# synapse_app sin prueba B.
EXCLUIDOS = {
    "synapse_adapter", "synapse_migration", "synapse_owner", "postgres",
    "streaming_replica", "brain_openwebui_ro", "synapse_app",
}

# Roles fuera de cobertura cuyo GUC persiste en pg_db_role_setting y por tanto
# necesitan un RESET explícito (INFRA-1586: skirmshop, skirmbooks_ui_app;
# INFRA-1369: residuo de P1 en brain_openwebui_ro).
DEBEN_RESET = {"skirmshop", "skirmbooks_ui_app", "brain_openwebui_ro"}

SET_15MIN_RE = re.compile(
    r"^ALTER ROLE (\w+) SET idle_session_timeout = '15min';\s*$", re.M)
RESET_RE = re.compile(r"^ALTER ROLE (\w+) RESET idle_session_timeout;\s*$", re.M)
TERMINATE_BLOCK_RE = re.compile(
    r"SELECT pg_terminate_backend\(pid\) FROM pg_stat_activity\b(?P<body>.*?);",
    re.S)
ANY_ARRAY_RE = re.compile(r"usename = ANY \(ARRAY\[(?P<array>[^\]]*)\]\)", re.S)


def setup_sql(text=None):
    """El `setup.sql` del ConfigMap que el Job role-settings monta en /sql."""
    docs = [d for d in yaml.safe_load_all(
        text if text is not None else ROLE_SETTINGS.read_text()) if d]
    cm = next(d for d in docs if d.get("kind") == "ConfigMap"
              and d.get("metadata", {}).get("name")
              == "postgres-shared-role-settings-sql")
    return cm["data"]["setup.sql"]


def covered_roles(sql):
    """Roles con `ALTER ROLE … SET idle_session_timeout = '15min'`."""
    return set(SET_15MIN_RE.findall(sql))


def swept_roles(sql):
    """Roles del `usename = ANY (ARRAY[…])` del pg_terminate_backend del backlog."""
    block = TERMINATE_BLOCK_RE.search(sql)
    if not block:
        return set()
    array = ANY_ARRAY_RE.search(block.group("body"))
    if not array:
        return set()
    return {tok.strip().strip("'") for tok in array.group("array").split(",")
            if tok.strip()}


def regimen_violations(sql):
    """Incumplimientos del régimen de ociosas en este SQL (vacío = correcto).

    Un PR que quite un SET de un rol cubierto desalinea la lista del SET con
    la del barrido; uno que meta un excluido en cualquiera de las dos lo
    levanta; uno que ensanche la limpieza (sin filtro `state = 'idle'`, con
    `idle in transaction`, o sin el acotado `usename = ANY`) también.
    """
    v = []
    covered = covered_roles(sql)
    swept = swept_roles(sql)
    if not covered:
        v.append("no hay ningún ALTER ROLE … SET idle_session_timeout = '15min'")
        return v
    if covered != swept:
        v.append("la lista del SET y la del barrido del backlog difieren: "
                 f"solo-SET={sorted(covered - swept)}, "
                 f"solo-barrido={sorted(swept - covered)}")
    for rol in sorted(covered & EXCLUIDOS):
        v.append(f"rol excluido recibe SET idle_session_timeout: {rol}")
    for rol in sorted(swept & EXCLUIDOS):
        v.append(f"rol excluido entra en el barrido del backlog: {rol}")
    for rol in sorted(DEBEN_RESET - set(RESET_RE.findall(sql))):
        v.append(f"rol fuera de cobertura sin su RESET idle_session_timeout: {rol}")
    if ("ALTER ROLE keep SET idle_in_transaction_session_timeout = '5min';"
            not in sql):
        v.append("keep sin idle_in_transaction_session_timeout = '5min'")
    block = TERMINATE_BLOCK_RE.search(sql)
    if not block:
        v.append("falta el SELECT pg_terminate_backend del backlog")
    else:
        body = block.group("body")
        if not re.search(r"state\s*=\s*'idle'", body):
            v.append("la limpieza del backlog no filtra state = 'idle'")
        if "idle in transaction" in body:
            v.append("la limpieza del backlog menciona idle in transaction "
                     "(debe matar solo state='idle', nunca transacciones abiertas)")
        if "usename = ANY" not in body:
            v.append("la limpieza del backlog no acota por usename = ANY a los roles cubiertos")
    return v


class TestIdleSessionRegimen(unittest.TestCase):
    """Positiva (INFRA-1625): el role-settings.yaml de trunk cumple el régimen."""

    def setUp(self):
        self.sql = setup_sql()

    def test_regimen_violations(self):
        """(a) cubiertos con su SET, (b) excluidos sin SET ni barrido,
        (c) keep con su idle_in_transaction, (d) barrido solo idle y acotado."""
        self.assertEqual(regimen_violations(self.sql), [])

    def test_covered_list_not_empty(self):
        # Un SQL sin SET no es "cumplir": es el régimen entero borrado.
        self.assertGreaterEqual(len(covered_roles(self.sql)), 20)

    def test_brain_openwebui_ro_has_its_reset(self):
        # (b) del contrato: brain_openwebui_ro sin SET y con RESET explícito
        # (residuo del SET de P1: el GUC persiste en pg_db_role_setting).
        self.assertNotIn("brain_openwebui_ro", covered_roles(self.sql))
        self.assertIn("brain_openwebui_ro", set(RESET_RE.findall(self.sql)))


class TestRegimenGuardCatchesMutations(unittest.TestCase):
    """Negativa (INFRA-1625): la guardia falla si la regresión de INFRA-1295 vuelve."""

    def setUp(self):
        self.sql = setup_sql()

    def test_removing_a_covered_set_is_caught(self):
        """Quitar el SET de un rol cubierto (desalinea SET vs barrido)."""
        victim = sorted(covered_roles(self.sql))[0]
        mutated, n = re.subn(
            rf"^ALTER ROLE {victim} SET idle_session_timeout = '15min';\n",
            "", self.sql, flags=re.M)
        self.assertEqual(n, 1)
        v = regimen_violations(mutated)
        self.assertTrue(v, "la guardia no detectó el SET eliminado")
        self.assertIn(victim, " ".join(v))

    def test_adding_excluded_role_to_set_is_caught(self):
        """Meter synapse_owner (exclusión permanente) en la lista del SET."""
        mutated = self.sql.replace(
            "ALTER ROLE keep SET idle_session_timeout = '15min';",
            "ALTER ROLE synapse_owner SET idle_session_timeout = '15min';\n"
            "ALTER ROLE keep SET idle_session_timeout = '15min';", 1)
        self.assertNotEqual(mutated, self.sql)
        v = regimen_violations(mutated)
        self.assertTrue(v, "la guardia no detectó el excluido añadido")
        self.assertIn("synapse_owner", " ".join(v))

    def test_widening_the_sweep_is_caught(self):
        """Ensanchar la limpieza: matar también `idle in transaction`."""
        mutated = self.sql.replace(
            "WHERE state = 'idle'",
            "WHERE (state = 'idle' OR state = 'idle in transaction')", 1)
        self.assertNotEqual(mutated, self.sql)
        v = regimen_violations(mutated)
        self.assertTrue(v, "la guardia no detectó el barrido ensanchado")
        self.assertIn("idle in transaction", " ".join(v))

    def test_unscoped_sweep_is_caught(self):
        """Limpieza sin el acotado `usename = ANY` a los roles cubiertos."""
        mutated = TERMINATE_BLOCK_RE.sub(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
            " WHERE state = 'idle'", self.sql, count=1)
        self.assertNotEqual(mutated, self.sql)
        v = regimen_violations(mutated)
        self.assertTrue(v, "la guardia no detectó el barrido sin acotar")


if __name__ == "__main__":
    unittest.main()
