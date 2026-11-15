"""SKIRM-184 (17-10-2026): la UI de gestión de Skirmbooks entra a postgres-shared con su
propio rol, `skirmbooks_ui_app`, y no con `skirmshop` (el rol compartido que además lee la
base SII de la tienda).

Fija la pareja de ficheros que poseen el rol; cada uno se puede romper solo y la UI se
queda sin credenciales o con más permisos de los que debe:

  - databases/postgres-shared/cluster.yaml: CNPG declara el rol (ensure present, login,
    connectionLimit, passwordSecret). Una migración no crea roles con contraseña: lo
    declara CNPG aquí (hallazgo 5 del architect, SKIRM-177).
  - databases/postgres-shared/app-credentials.yaml: el ExternalSecret que proyecta el ítem
    `skirmbooks-ui-db` de 1Password en el Secret que lee CNPG, en forma Connect
    (key = ítem, property = campo) para no gastar el cupo diario de la cuenta.

Los GRANT sobre los esquemas `gestoria_*` no viven aquí: son la migración del producto
(patrón 0058) y que el rol no lea la base SII de la tienda lo mide qa en producción.
"""
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLUSTER = ROOT / "databases" / "postgres-shared" / "cluster.yaml"
CREDENTIALS = ROOT / "databases" / "postgres-shared" / "app-credentials.yaml"

ROL = "skirmbooks_ui_app"
SECRET = "skirmbooks-ui-db-credentials"
ITEM = "skirmbooks-ui-db"


def docs(path):
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def role():
    cluster = yaml.safe_load(CLUSTER.read_text(encoding="utf-8"))
    return next(r for r in cluster["spec"]["managed"]["roles"] if r["name"] == ROL)


def externalsecret():
    return next(d for d in docs(CREDENTIALS)
                if d.get("kind") == "ExternalSecret" and d["metadata"]["name"] == SECRET)


class RolDeclarado(unittest.TestCase):
    def test_el_rol_existe_con_login_y_tope(self):
        r = role()
        self.assertEqual(r["ensure"], "present")
        self.assertTrue(r["login"])
        # connectionLimit medido: el pool de la UI es max 8
        # (skirmbooks-ui/app/lib/db.server.ts:105) con 1 réplica; el tope va en el
        # servidor, como en `horarios` (SC-2495).
        self.assertGreater(r["connectionLimit"], 8)
        self.assertLessEqual(r["connectionLimit"], 20)
        self.assertEqual(r["passwordSecret"]["name"], SECRET)

    def test_el_comentario_lleva_la_historia(self):
        self.assertIn("SKIRM-184", role()["comment"])


class ExternalSecretDelRol(unittest.TestCase):
    def setUp(self):
        self.es = externalsecret()

    def test_forma_connect_y_namespace(self):
        self.assertEqual(self.es["metadata"]["namespace"], "databases")
        self.assertEqual(self.es["spec"]["secretStoreRef"],
                         {"name": "onepassword-connect", "kind": "ClusterSecretStore"})
        self.assertEqual(self.es["spec"]["refreshPolicy"], "OnChange")

    def test_proyecta_username_y_password_del_item(self):
        data = {d["secretKey"]: d["remoteRef"] for d in self.es["spec"]["data"]}
        self.assertEqual(sorted(data), ["password", "username"])
        self.assertEqual(data["username"], {"key": ITEM, "property": "DB_USER"})
        self.assertEqual(data["password"], {"key": ITEM, "property": "DB_PASSWORD"})

    def test_target_basic_auth_recargable_por_cnpg(self):
        target = self.es["spec"]["target"]
        self.assertEqual(target["name"], SECRET)
        self.assertEqual(target["template"]["type"], "kubernetes.io/basic-auth")
        self.assertEqual(target["template"]["metadata"]["labels"]["cnpg.io/reload"], "true")

    def test_materializa_antes_que_el_cluster(self):
        # El rol se crea con contraseña: el Secret tiene que existir cuando CNPG
        # procesa el Cluster del mismo sync (patrón de los *-db-credentials con wave).
        wave = (self.es["metadata"].get("annotations") or {}
                ).get("argocd.argoproj.io/sync-wave")
        self.assertEqual(wave, "-1")


if __name__ == "__main__":
    unittest.main()
