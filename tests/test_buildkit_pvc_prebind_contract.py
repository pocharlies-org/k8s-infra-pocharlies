"""INFRA-826: un PVC local-path de un builder apagado no puede atascar la sync.

`local-path` es WaitForFirstConsumer: con el Deployment a 0 réplicas el PVC se queda
Pending, ArgoCD espera a su salud y la operación de `k8s-infra` no termina (60b1394,
buildkitd-arm64-dgx3: no entró la revisión siguiente). La anotación
`volume.kubernetes.io/selected-node` hace que el provisioner cree el volumen sin
consumidor; tiene que apuntar al nodo del nodeSelector del Deployment.
"""

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SELECTED_NODE = "volume.kubernetes.io/selected-node"
HOSTNAME = "kubernetes.io/hostname"


def builders():
    """(fichero, Deployment, PVC local-path que monta) de cada manifiesto de buildkit/."""
    for path in sorted((ROOT / "buildkit").glob("buildkitd-*.yaml")):
        docs = [d for d in yaml.safe_load_all(path.read_text()) if d]
        pvcs = {
            d["metadata"]["name"]: d
            for d in docs
            if d["kind"] == "PersistentVolumeClaim"
            and d["spec"].get("storageClassName") == "local-path"
        }
        for dep in (d for d in docs if d["kind"] == "Deployment"):
            for vol in dep["spec"]["template"]["spec"].get("volumes", []):
                claim = vol.get("persistentVolumeClaim", {}).get("claimName")
                if claim in pvcs:
                    yield path.name, dep, pvcs[claim]


class BuildkitPvcPrebindContractTest(unittest.TestCase):
    def test_pvc_of_a_deployment_at_zero_replicas_names_its_node(self):
        for name, dep, pvc in builders():
            if dep["spec"]["replicas"] != 0:
                continue
            node = dep["spec"]["template"]["spec"]["nodeSelector"].get(HOSTNAME)
            self.assertIsNotNone(node, f"{name}: a 0 réplicas el nodo va fijado por hostname")
            self.assertEqual(
                (pvc["metadata"].get("annotations") or {}).get(SELECTED_NODE),
                node,
                f"{name}: PVC {pvc['metadata']['name']} sin {SELECTED_NODE}={node}",
            )

    def test_dgx3_builder_pvc_is_prebound_to_dgx3(self):
        found = {n: (d, p) for n, d, p in builders()}["buildkitd-arm64-dgx3.yaml"]
        dep, pvc = found
        self.assertEqual(dep["spec"]["template"]["spec"]["nodeSelector"][HOSTNAME], "dgx3")
        self.assertEqual(pvc["metadata"]["annotations"][SELECTED_NODE], "dgx3")


if __name__ == "__main__":
    unittest.main()
