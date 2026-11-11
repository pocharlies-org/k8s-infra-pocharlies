"""Contrato de las bases comunes fijadas por digest (INFRA-1297, INFRA-536 P2).

Corre sin red: `docs/images/bases.md` y `docs/images/inventario.json` son ficheros
commiteados. Fija el criterio C3 en lo verificable sin registries:

- cada base declara `tag`, `digest` con formato `sha256:` + 64 hex, `dockerfile`,
  `arquitecturas` y `consumidoras`;
- el numero de digests `sha256:` en bases.md es >= 2 (grep del criterio);
- cada base tiene >= 3 consumidoras y todas existen como `repo` del inventario;
- el Dockerfile declarado existe y su FROM esta fijado por digest (@sha256:);
- la fixture negativa (tests/fixtures/image-bases/mala-bases.md) es rechazada.

El `crane digest` real contra Harbor es evidencia en vivo de la PR (fuera del test).
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASES_MD = ROOT / "docs" / "images" / "bases.md"
INVENTARIO = ROOT / "docs" / "images" / "inventario.json"
FIXTURES = ROOT / "tests" / "fixtures" / "image-bases"

DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
CAMPOS_REQUERIDOS = ("tag", "digest", "dockerfile", "arquitecturas", "consumidoras")


def parsear_bases(texto):
    """Parser de bases.md -> {nombre: {campo: valor, 'consumidoras': [..]}}.

    Formato: secciones `## <nombre>`; campos `- clave: valor` (con valor, o vacío
    para las listas); consumidoras como sublistas indentadas `  - <repo>`. La
    prosa esta permitida, pero toda linea que empieza por `- ` a nivel de campo
    debe casar con el formato: un campo mal escrito es un error de contrato.
    """
    bases = {}
    actual = None
    for n, linea in enumerate(texto.splitlines(), 1):
        m = re.match(r"^## (\S+)\s*$", linea)
        if m:
            actual = m.group(1)
            bases[actual] = {"consumidoras": []}
            continue
        m = re.match(r"^\s{2,}- (\S+)\s*$", linea)
        if m:
            if actual is None:
                raise ValueError(f"linea {n}: consumidora fuera de seccion: {linea!r}")
            bases[actual]["consumidoras"].append(m.group(1))
            continue
        if linea.startswith("- "):
            if actual is None:
                raise ValueError(f"linea {n}: campo fuera de seccion: {linea!r}")
            m = re.match(r"^- ([a-z]+):\s*(\S.*?)?\s*$", linea)
            if not m:
                raise ValueError(f"linea {n}: campo no parseable en {actual}: {linea!r}")
            clave, valor = m.group(1), m.group(2) or ""
            if isinstance(bases[actual].get(clave), list):
                if valor:
                    raise ValueError(f"linea {n}: {clave} es lista, no admite valor: {linea!r}")
            else:
                bases[actual][clave] = valor
    return bases


def validar_bases(bases, repos_inventario, raiz=ROOT):
    """Errores de contrato sobre lo parseado (vacío == cumple)."""
    errores = []
    for nombre, b in sorted(bases.items()):
        for campo in CAMPOS_REQUERIDOS:
            if campo not in b:
                errores.append(f"{nombre}: falta el campo {campo}")
        digest = b.get("digest", "")
        if digest and not DIGEST_RE.match(digest):
            errores.append(f"{nombre}: digest con formato invalido: {digest!r}")
        if "sha256:" not in digest:
            if digest:
                errores.append(f"{nombre}: digest sin prefijo sha256:")
        consumidoras = b.get("consumidoras", [])
        if len(consumidoras) < 3:
            errores.append(f"{nombre}: {len(consumidoras)} consumidoras (< 3)")
        for c in consumidoras:
            if c not in repos_inventario:
                errores.append(f"{nombre}: consumidora inexistente en el inventario: {c}")
        dockerfile = b.get("dockerfile", "")
        if dockerfile:
            ruta = raiz / dockerfile
            if not ruta.is_file():
                errores.append(f"{nombre}: Dockerfile no existe: {dockerfile}")
            else:
                froms = re.findall(r"(?im)^\s*FROM\s+(\S+)", ruta.read_text(encoding="utf-8"))
                if not froms:
                    errores.append(f"{nombre}: Dockerfile sin FROM: {dockerfile}")
                elif not any("@sha256:" in f for f in froms):
                    errores.append(f"{nombre}: FROM sin fijar por digest: {dockerfile}")
    return errores


class BasesContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inventario = json.loads(INVENTARIO.read_text(encoding="utf-8"))
        cls.repos = {e["repo"] for e in cls.inventario}

    def test_bases_md_existe_y_declaran_dos_digests(self):
        self.assertTrue(BASES_MD.is_file(), "falta docs/images/bases.md")
        texto = BASES_MD.read_text(encoding="utf-8")
        digests = re.findall(r"sha256:[0-9a-f]{64}", texto)
        self.assertGreaterEqual(len(digests), 2, "bases.md debe declarar >= 2 digests")

    def test_bases_md_cumple_el_contrato_contra_el_inventario(self):
        bases = parsear_bases(BASES_MD.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(bases), 2, "bases.md debe documentar >= 2 bases")
        errores = validar_bases(bases, self.repos)
        self.assertEqual(errores, [], f"bases.md incumple el contrato: {errores}")

    def test_dockerfiles_de_bases_parsean(self):
        bases = parsear_bases(BASES_MD.read_text(encoding="utf-8"))
        for nombre, b in bases.items():
            ruta = ROOT / b["dockerfile"]
            froms = re.findall(r"(?im)^\s*FROM\s+(\S+)", ruta.read_text(encoding="utf-8"))
            self.assertTrue(froms, f"{nombre}: Dockerfile sin FROM")

    def test_fixture_mala_es_rechazada(self):
        texto = (FIXTURES / "mala-bases.md").read_text(encoding="utf-8")
        bases = parsear_bases(texto)
        errores = validar_bases(bases, self.repos)
        joined = "\n".join(errores)
        self.assertTrue(any("digest" in e for e in errores), f"no detecta digest malo: {joined}")
        self.assertTrue(any("inventario" in e for e in errores), f"no detecta consumidora falsa: {joined}")
        self.assertTrue(any("< 3" in e for e in errores), f"no detecta <3 consumidoras: {joined}")


if __name__ == "__main__":
    unittest.main()
