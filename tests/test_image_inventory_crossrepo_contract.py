"""Gramatica cross-repo de los envs IMAGE:/DOCKERFILE: (INFRA-1475).

Un workflow de build puede declarar su Dockerfile en OTRO repo
("pocharlies-org/k8s-nova-pocharlies:avatar/Dockerfile": build-nova-avatar.yml y
build-weight-resolver.yml de dgx-infra construyen desde el repo de la fuente).
El inventario debe resolver ese Dockerfile en el repo declarado, no buscarlo en
el repo del workflow (hasta hoy: sin_dato). Corre sin red con un runner stub.
"""
import base64
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "image-inventory.py"

_spec = importlib.util.spec_from_file_location("image_inventory", SCRIPT)
ii = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ii)


def _contenido(texto):
    return json.dumps({"content": base64.b64encode(texto.encode()).decode()})


WF_NOVA = """name: build nova-avatar
env:
  IMAGE: homelab/nova-avatar
  DOCKERFILE: pocharlies-org/k8s-nova-pocharlies:avatar/Dockerfile
"""

WF_LOCAL = """name: build local
env:
  IMAGE: homelab/app-local
  DOCKERFILE: docker/App.Dockerfile
"""

DOCKERFILE_NOVA = "FROM harbor.e-dani.com/base/python@sha256:aaaa\nRUN pip install x\n"

GITHUB = {
    "gh api orgs/pocharlies-org/repos?per_page=100 --paginate --jq .[].name":
        {"stdout": "dgx-infra\nk8s-nova-pocharlies\n"},
    "gh api repos/pocharlies-org/dgx-infra/contents/.github/workflows":
        {"stdout": json.dumps([
            {"name": "build-nova-avatar.yml", "type": "file"},
            {"name": "build-local.yml", "type": "file"},
        ])},
    "gh api repos/pocharlies-org/dgx-infra/contents/.github/workflows/build-nova-avatar.yml":
        {"stdout": _contenido(WF_NOVA)},
    "gh api repos/pocharlies-org/dgx-infra/contents/.github/workflows/build-local.yml":
        {"stdout": _contenido(WF_LOCAL)},
    "gh api repos/pocharlies-org/k8s-nova-pocharlies/contents/.github/workflows":
        {"returncode": 1},
    "gh api repos/pocharlies-org/k8s-nova-pocharlies/contents/avatar/Dockerfile":
        {"stdout": _contenido(DOCKERFILE_NOVA)},
    "gh api repos/pocharlies-org/dgx-infra/contents/docker/App.Dockerfile":
        {"stdout": _contenido("FROM alpine\n")},
}


class CrossRepoDockerfileTest(unittest.TestCase):
    def setUp(self):
        self.runner = ii.RunnerFixture({}, GITHUB)
        self.mapa = ii.mapa_de_workflows(self.runner)

    def test_cross_repo_dockerfile_keeps_its_own_repo(self):
        ref, contenido, workflow = ii.resolver_dockerfile(
            self.runner, "harbor.e-dani.com/homelab/nova-avatar", self.mapa)
        self.assertEqual(ref, "pocharlies-org/k8s-nova-pocharlies:avatar/Dockerfile")
        self.assertEqual(contenido, DOCKERFILE_NOVA)
        self.assertEqual(
            workflow,
            "pocharlies-org/dgx-infra:.github/workflows/build-nova-avatar.yml")

    def test_same_repo_dockerfile_still_resolves_in_the_workflow_repo(self):
        ref, contenido, _ = ii.resolver_dockerfile(
            self.runner, "harbor.e-dani.com/homelab/app-local", self.mapa)
        self.assertEqual(ref, "pocharlies-org/dgx-infra:docker/App.Dockerfile")
        self.assertEqual(contenido, "FROM alpine\n")


if __name__ == "__main__":
    unittest.main()
