"""Contrato del inventario regenerable de imagenes (INFRA-1296, INFRA-536 P1).

Corre sin red ni cluster contra la fixture fija de tests/fixtures/image-inventory
(salida kubectl + respuestas crane/gh). Cubre el contrato JSON de C1: las 7 claves
de toda propia siempre presentes y no nulas, el no-dato como marcador `sin_dato`
dentro del propio campo, y el jq EXACTO del criterio C1 dando 0.
"""
import json
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "image-inventory.py"
FIXTURES = ROOT / "tests" / "fixtures" / "image-inventory"

# El jq exacto del criterio C1 del 00-spec.md (no tocar: es el criterio).
C1_JQ = ('[.[]|select(.clase=="propia")|select(.dockerfile==null or .base_digest==null '
         'or .comprimido==null or .descomprimido==null or .capas_top==null '
         'or .build_fecha==null or (.deployments|length)==0)]|length')

SIETE_CLAVES = ("dockerfile", "base_digest", "comprimido", "descomprimido",
                "capas_top", "build_fecha", "deployments")

HOST_ARQ = "arm64" if platform.machine() in ("aarch64", "arm64") else "amd64"


def run_inventory(out_dir):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--fixture-dir", str(FIXTURES), "--out-dir", str(out_dir)],
        capture_output=True, text=True)


def inventario_de(tmp):
    return json.loads((tmp / "inventario.json").read_text(encoding="utf-8"))


def buscar(inventario, sufijo):
    return next(e for e in inventario if e["repo"].endswith("/" + sufijo))


class InventoryContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._dir = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._dir.name)
        r = run_inventory(cls.tmp)
        assert r.returncode == 0, f"image-inventory.py fallo: {r.stderr[-2000:]}"
        cls.inventario = inventario_de(cls.tmp)

    @classmethod
    def tearDownClass(cls):
        cls._dir.cleanup()

    def test_generates_the_three_files(self):
        for name in ("inventario.json", "inventario.md", "sizes-baseline.json"):
            self.assertTrue((self.tmp / name).is_file(), name)

    def test_scope_filters_out_unscoped_images(self):
        repos = {e["repo"] for e in self.inventario}
        self.assertFalse([r for r in repos if "nginx" in r])
        self.assertTrue(any(r.endswith("/multi-arch-app") for r in repos))

    def test_seven_keys_present_and_non_null_for_every_propia(self):
        for e in self.inventario:
            if e["clase"] != "propia":
                continue
            for clave in SIETE_CLAVES:
                self.assertIn(clave, e, f"{e['repo']} sin clave {clave}")
                self.assertIsNotNone(e[clave], f"{e['repo']} con {clave}=null")
            self.assertGreater(len(e["deployments"]), 0, e["repo"])

    def test_multiarch_index_resolves_to_host_platform(self):
        e = buscar(self.inventario, "multi-arch-app")
        self.assertEqual(e["plataforma"], f"linux/{HOST_ARQ}")
        esperado = 400 if HOST_ARQ == "amd64" else 3000
        self.assertEqual(e["comprimido"], esperado)
        self.assertEqual(e["build_fecha"],
                         "2026-10-01T10:00:00Z" if HOST_ARQ == "amd64" else "2026-10-01T09:00:00Z")

    def test_single_platform_index_resolves(self):
        # Indice OCI con una sola plataforma real (arm64) + una de atestiguacion
        # (architecture "unknown", como adjunta buildx): se resuelve el hijo arm64
        # aunque el host sea amd64, y la atestiguacion se descarta.
        e = buscar(self.inventario, "single-plat-app")
        self.assertEqual(e["plataforma"], "linux/arm64")
        self.assertEqual(e["comprimido"], 700)
        self.assertEqual(e["descomprimido"], 3000)

    def test_multiword_upstream_in_homelab_is_espejo(self):
        # "onepassword-connect" es espejo conocido a pesar del guion: el patron
        # completo casa con el nombre entero, no solo con segmentos.
        e = buscar(self.inventario, "onepassword-connect")
        self.assertEqual(e["clase"], "espejo")
        self.assertIn("onepassword-connect", e["origen"])

    def test_simple_image_resolves(self):
        # Imagen simple (manifiesto, no indice) con tag real del cluster: nunca se
        # consulta `latest` (la fixture no tiene ninguna clave con :latest: si el
        # script la inventara, la resolucion daria error y el tamano seria marcador).
        e = buscar(self.inventario, "simple-app")
        self.assertEqual(e["comprimido"], 110)
        self.assertEqual(e["build_fecha"], "2026-08-01T00:00:00Z")
        self.assertEqual(e["capas_top"], [
            {"digest": "sha256:" + "2" * 64, "tamano": 60},
            {"digest": "sha256:" + "1" * 64, "tamano": 50},
        ])

    def test_known_upstream_in_homelab_is_espejo_without_seven_keys(self):
        # El espejo no lleva los 6 campos propios de la construccion (dockerfile,
        # base_digest, tamanos, capas, build_fecha); deployments si: son consumidores
        # reales y el grafo los necesita como hojas.
        e = buscar(self.inventario, "redis")
        self.assertEqual(e["clase"], "espejo")
        for clave in SIETE_CLAVES:
            if clave == "deployments":
                continue
            self.assertNotIn(clave, e)
        self.assertGreater(len(e["deployments"]), 0)
        self.assertIn("redis", e["origen"])

    def test_ghcr_repo_without_github_repo_is_espejo(self):
        e = buscar(self.inventario, "upstream-mirror")
        self.assertEqual(e["clase"], "espejo")
        self.assertNotIn("dockerfile", e)

    def test_two_harbor_hosts_one_logical_entry(self):
        propias = [e for e in self.inventario if e["repo"].endswith("/multi-arch-app")]
        self.assertEqual(len(propias), 1)
        e = propias[0]
        self.assertEqual(e["repo"], "harbor.e-dani.com/homelab/multi-arch-app")
        self.assertEqual(sorted(e["deployments"]),
                         ["demo/Deployment/multi-arch-app", "demo2/StatefulSet/multi-arch-app"])
        # El host preferido (harbor.e-dani.com) resuelve aunque el cluster cite el LAN.
        self.assertTrue(e["resuelta"].startswith("harbor.e-dani.com/"))

    def test_dockerfile_resolved_from_build_workflow_envs(self):
        e = buscar(self.inventario, "multi-arch-app")
        self.assertEqual(e["dockerfile"],
                         "pocharlies-org/k8s-infra-pocharlies:docker/Dockerfile")
        self.assertEqual(e["base_digest"],
                         [{"imagen": "harbor.e-dani.com/homelab/base-python:3.12",
                           "digest": "sha256:" + "7" * 64}])

    def test_workflow_candidate_is_verified_by_content(self):
        # El primer candidato de la busqueda (aaa-docs) menciona homelab/simple-app
        # pero NO declara la linea `IMAGE: homelab/simple-app`: se descarta y gana
        # el workflow de build real (dgx-infra/build-simple.yml).
        e = buscar(self.inventario, "simple-app")
        self.assertEqual(e["dockerfile"], "pocharlies-org/dgx-infra:Dockerfile")

    def test_ghcr_dockerfile_resolved_from_repo_root(self):
        e = buscar(self.inventario, "ghcr-app")
        self.assertEqual(e["dockerfile"], "pocharlies-org/ghcr-app:Dockerfile")
        self.assertEqual(e["base_digest"],
                         [{"imagen": "docker.io/library/python:3.12-slim",
                           "digest": "sha256:" + "8" * 64}])

    def test_sin_dato_markers_are_objects_inside_the_field(self):
        e = buscar(self.inventario, "sin-dato-app")
        self.assertEqual(e["clase"], "propia")
        for clave in ("dockerfile", "build_fecha", "descomprimido"):
            self.assertIsInstance(e[clave], dict, clave)
            self.assertIn("sin_dato", e[clave], clave)
        # Los datos que si hay, siguen siendo datos:
        self.assertEqual(e["comprimido"], 40)

    @unittest.skipUnless(shutil.which("jq"), "jq is not installed")
    def test_c1_jq_exact_returns_zero(self):
        r = subprocess.run(["jq", C1_JQ, str(self.tmp / "inventario.json")],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "0")

    def test_sizes_baseline_maps_digest_to_sizes(self):
        baseline = json.loads((self.tmp / "sizes-baseline.json").read_text(encoding="utf-8"))
        self.assertIn("formato", baseline)
        self.assertIn("imagenes", baseline)
        entrada = baseline["imagenes"]["harbor.e-dani.com/homelab/simple-app"]
        self.assertEqual(entrada["sha256:" + "e" * 64],
                         {"comprimido": 110, "descomprimido": 200})

    def test_no_runtime_timestamps_and_deterministic(self):
        texto = (self.tmp / "inventario.json").read_text(encoding="utf-8")
        self.assertNotIn("generated_at", texto)
        self.assertNotIn("generated", texto)
        with tempfile.TemporaryDirectory() as segundo:
            r = run_inventory(Path(segundo))
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            for name in ("inventario.json", "inventario.md", "sizes-baseline.json"):
                self.assertEqual((self.tmp / name).read_bytes(),
                                 (Path(segundo) / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
