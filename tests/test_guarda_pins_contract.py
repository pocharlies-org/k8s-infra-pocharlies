"""INFRA-1365: contrato del módulo de enumeración de pins (scripts/guarda-pins/pins.py).

El módulo es la pieza común de la guarda (INFRA-1366) y de `migrar.py` (INFRA-1365):
extrae los pins `@sha256:` de los repos GitOps y comprueba en Harbor si el digest
existe y lleva algún tag `keep-*`. Estos tests fijan la extracción (PyYAML, con su
fallback de texto crudo) y la construcción de URLs / clasificación, sin tocar Harbor.
"""
import builtins
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "guarda-pins"))

import pins  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "guarda-pins" / "values-pins.yaml"

D1 = "1" * 64
D2 = "2" * 64


class TestExtract(unittest.TestCase):
    def test_extracts_full_ref_pins(self):
        got = pins.extract_pins_from_text(FIXTURE.read_text())
        self.assertEqual(
            got,
            {
                ("homelab/correo-core", "sha256:" + D1),
                ("homelab/correo-telegram", "sha256:" + D2),
            },
        )

    def test_ignores_dockerhub_and_short_digest(self):
        got = pins.extract_pins_from_text(FIXTURE.read_text())
        self.assertFalse(any("redis" in r for r, _ in got))
        self.assertFalse(any("/x" in r for r, _ in got))

    def test_canonical_host_without_lan_is_a_pin(self):
        got = pins.extract_pins_from_text(
            "image: harbor.e-dani.com/homelab/foo@sha256:" + D1
        )
        self.assertEqual(got, {("homelab/foo", "sha256:" + D1)})

    def test_fallback_regex_matches_pyyaml_path(self):
        """Sin PyYAML (imagen mínima del Job) el regex sobre texto crudo da lo mismo."""
        text = FIXTURE.read_text()
        canonical = pins.extract_pins_from_text(text)
        real_import = builtins.__import__

        def fake_import(name, *a, **k):
            if name == "yaml":
                raise ImportError("no pyyaml")
            return real_import(name, *a, **k)

        with mock.patch.object(builtins, "__import__", fake_import):
            fallback = pins.extract_pins_from_text(text)
        self.assertEqual(canonical, fallback)

    def test_enumerate_pins_walks_directories(self):
        with tempfile.TemporaryDirectory() as d:
            sub = pathlib.Path(d) / "k8s" / "overlays" / "prod"
            sub.mkdir(parents=True)
            (sub / "values.yaml").write_text(FIXTURE.read_text())
            (sub / "notes.txt").write_text("harbor.lan.e-dani.com/homelab/no@sha256:" + D1)
            out = pins.enumerate_pins([d])
            refs = {(r, dg) for r, dg, _ in out}
            self.assertEqual(
                refs,
                {("homelab/correo-core", "sha256:" + D1), ("homelab/correo-telegram", "sha256:" + D2)},
            )
            # el .txt no se recorre (solo .yaml/.yml)
            self.assertNotIn("homelab/no", {r for r, _ in refs})


class TestKeepTag(unittest.TestCase):
    def test_keep_tag_first_12_hex(self):
        self.assertEqual(pins.keep_tag("sha256:" + "a" * 8 + "b" * 56), "keep-" + "a" * 8 + "b" * 4)
        self.assertEqual(pins.keep_tag("sha256:" + "3" * 64), "keep-" + "3" * 12)


class TestHarborUrl(unittest.TestCase):
    def test_tags_url_encodes_project_repo_and_digest(self):
        url = pins._tags_url("https://h", "homelab/foo", "sha256:" + D1)
        self.assertTrue(url.startswith("https://h/api/v2.0/projects/homelab/repositories/foo/artifacts/"))
        self.assertIn("sha256%3A" + D1, url)
        self.assertTrue(url.endswith("/tags"))

    def test_nested_repo_path_encodes_slash(self):
        # el primer segmento es el proyecto; el resto es el nombre del repo y su
        # barra va codificada (%2F), como pide la API de Harbor.
        url = pins._tags_url("https://h", "homelab/sub/foo", "sha256:" + D1)
        self.assertIn("projects/homelab/repositories/sub%2Ffoo", url)


class TestClassify(unittest.TestCase):
    def test_protected_when_a_keep_tag_present(self):
        with mock.patch.object(pins, "harbor_tag_names", return_value=["ci-abc", "keep-" + D1[:12]]):
            self.assertEqual(pins.classify_pin("b", "homelab/foo", "sha256:" + D1, "u", "p"), pins.PROTEGIDO)

    def test_unprotected_when_no_keep_tag(self):
        with mock.patch.object(pins, "harbor_tag_names", return_value=["ci-abc", "v1"]):
            self.assertEqual(pins.classify_pin("b", "homelab/foo", "sha256:" + D1, "u", "p"), pins.DESPROTEGIDO)

    def test_nonexistent_when_404(self):
        with mock.patch.object(pins, "harbor_tag_names", return_value=None):
            self.assertEqual(pins.classify_pin("b", "homelab/foo", "sha256:" + D1, "u", "p"), pins.INEXISTENTE)


class TestCreateTag(unittest.TestCase):
    def test_create_tag_returns_status(self):
        with mock.patch.object(pins, "_harbor_request", return_value=(201, None)) as m:
            self.assertEqual(pins.create_tag("b", "homelab/foo", "sha256:" + D1, "keep-x", "u", "p"), 201)
        self.assertEqual(m.call_args[0][0], "POST")

    def test_verify_true_only_if_tag_on_digest(self):
        with mock.patch.object(pins, "harbor_tag_names", return_value=["keep-x"]):
            self.assertTrue(pins.verify_tag_on_digest("b", "homelab/foo", "sha256:" + D1, "keep-x", "u", "p"))
        with mock.patch.object(pins, "harbor_tag_names", return_value=["keep-y"]):
            self.assertFalse(pins.verify_tag_on_digest("b", "homelab/foo", "sha256:" + D1, "keep-x", "u", "p"))
        with mock.patch.object(pins, "harbor_tag_names", return_value=None):
            self.assertFalse(pins.verify_tag_on_digest("b", "homelab/foo", "sha256:" + D1, "keep-x", "u", "p"))


if __name__ == "__main__":
    unittest.main()
