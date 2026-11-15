"""Contrato del grafo de imagenes (INFRA-1296, INFRA-536 P1, criterio C2).

Determinismo con la fixture fija: dos ejecuciones sobre el mismo inventario dan
bytes identicos (es lo que mide `git diff --exit-code` en C2). Cada imagen del
inventario aparece como nodo; las bases son raices y los despliegues, hojas.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scripts" / "image-inventory.py"
GRAPH = ROOT / "scripts" / "image-graph.py"
FIXTURES = ROOT / "tests" / "fixtures" / "image-inventory"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


class GraphContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._dir.name)
        r = run([sys.executable, str(INVENTORY), "--fixture-dir", str(FIXTURES),
                 "--out-dir", str(cls.tmp)])
        assert r.returncode == 0, f"image-inventory.py fallo: {r.stderr[-2000:]}"
        cls.inventario = json.loads((cls.tmp / "inventario.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def run_graph(self):
        return run([sys.executable, str(GRAPH), "--inventario", str(self.tmp / "inventario.json"),
                    "--out-dir", str(self.tmp)])

    def test_generates_dot_and_md(self):
        r = self.run_graph()
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertTrue((self.tmp / "grafo.dot").is_file())
        self.assertTrue((self.tmp / "grafo.md").is_file())

    def test_two_runs_are_byte_identical(self):
        self.assertEqual(self.run_graph().returncode, 0)
        first = ((self.tmp / "grafo.dot").read_bytes(), (self.tmp / "grafo.md").read_bytes())
        self.assertEqual(self.run_graph().returncode, 0)
        second = ((self.tmp / "grafo.dot").read_bytes(), (self.tmp / "grafo.md").read_bytes())
        self.assertEqual(first, second)

    def test_every_inventory_image_is_a_node(self):
        self.assertEqual(self.run_graph().returncode, 0)
        dot = (self.tmp / "grafo.dot").read_text(encoding="utf-8")
        for e in self.inventario:
            self.assertIn('"%s"' % e["repo"], dot, e["repo"])

    def test_bases_are_roots_and_deployments_are_leaves(self):
        self.assertEqual(self.run_graph().returncode, 0)
        dot = (self.tmp / "grafo.dot").read_text(encoding="utf-8")
        self.assertIn('"docker.io/library/python:3.12-slim"', dot)
        self.assertIn('"harbor.e-dani.com/homelab/base-python:3.12"', dot)
        self.assertIn('"demo/Deployment/multi-arch-app"', dot)
        # Una base es padre de su imagen propia:
        self.assertIn('"docker.io/library/python:3.12-slim" -> "ghcr.io/pocharlies-org/ghcr-app"', dot)
        # Y la imagen propia es padre de su despliegue:
        self.assertIn('"ghcr.io/pocharlies-org/ghcr-app" -> "demo/Deployment/ghcr-app"', dot)

    def test_no_runtime_timestamps(self):
        self.assertEqual(self.run_graph().returncode, 0)
        for name in ("grafo.dot", "grafo.md"):
            self.assertNotIn("generated_at", (self.tmp / name).read_text(encoding="utf-8"))


class GraphPublishedContractTest(unittest.TestCase):
    """El grafo publicado en el repo (INFRA-1296, hallazgo de qa al cierre de INFRA-536).

    C2 pide el grafo publicado y regenerable. `git diff --exit-code` sobre ficheros
    no trackeados pasa en falso porque git los ignora, asi que la publicacion se
    mide con `git ls-files`: si alguien borra los generados del tronco, falla en CI.
    """

    def test_generated_graph_files_are_tracked(self):
        for name in ("docs/images/grafo.md", "docs/images/grafo.dot"):
            r = subprocess.run(["git", "ls-files", "--error-unmatch", name],
                               capture_output=True, text=True, cwd=ROOT)
            self.assertEqual(
                r.returncode, 0,
                "%s no esta trackeado en el repo: debe generarse con "
                "scripts/image-graph.py y commitearse (C2)" % name)


class PublishedGraphMatchesInventoryContractTest(unittest.TestCase):
    """El grafo commiteado ES la regeneración del inventario commiteado (C2, regression).

    `GraphContractTest` fija el determinismo sobre la fixture y
    `GraphPublishedContractTest` que los ficheros están trackeados; falta la
    coherencia ENTRE los dos artefactos publicados: regenerar `scripts/image-graph.py`
    sobre `docs/images/inventario.json` debe reproducir byte a byte los
    `grafo.md`/`grafo.dot` del tronco (es exactamente lo que qa midió a mano con doble
    ejecución + diff, sin red). Si alguien actualiza el inventario sin regenerar el
    grafo, el grafo publicado queda obsoleto y esto lo pone en rojo.
    """

    INVENTARIO = ROOT / "docs" / "images" / "inventario.json"

    def test_grafo_commiteado_es_la_regeneracion_del_inventario_commiteado(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run([sys.executable, str(GRAPH), "--inventario", str(self.INVENTARIO),
                     "--out-dir", tmp])
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            for name in ("grafo.md", "grafo.dot"):
                self.assertEqual(
                    (ROOT / "docs" / "images" / name).read_bytes(),
                    (Path(tmp) / name).read_bytes(),
                    "%s no es la regeneración de docs/images/inventario.json: "
                    "regenerar con scripts/image-graph.py y commitear (C2)" % name)


if __name__ == "__main__":
    unittest.main()
