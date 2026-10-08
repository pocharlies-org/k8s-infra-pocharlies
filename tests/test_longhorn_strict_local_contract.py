"""INFRA-709: StorageClass `longhorn-strict-local` (volumen local de un nodo).

Contrato de la clase que usan los volúmenes de Frigate (INFRA-701): 1 réplica,
strict-local, Delete y WaitForFirstConsumer (D1 del architect). Tiene que estar
en el kustomize raíz, que es lo que lee ArgoCD (`k8s-infra`, path `.`): un
fichero en `kubernetes/storage/` que no esté listado ahí no llega al clúster.
"""

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CLASS = ROOT / "kubernetes/storage/longhorn-strict-local.yaml"


def resources(kustomization):
    return yaml.safe_load((ROOT / kustomization).read_text())["resources"]


class LonghornStrictLocalContractTest(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CLASS.is_file(), f"falta {CLASS.relative_to(ROOT)}")
        self.sc = yaml.safe_load(CLASS.read_text())
        self.params = self.sc["parameters"]

    def test_identity(self):
        self.assertEqual(self.sc["kind"], "StorageClass")
        self.assertEqual(self.sc["metadata"]["name"], "longhorn-strict-local")
        self.assertEqual(self.sc["provisioner"], "driver.longhorn.io")
        self.assertEqual(
            self.sc["metadata"]["annotations"][
                "storageclass.kubernetes.io/is-default-class"
            ],
            "false",
        )

    def test_one_replica_strict_local_and_delete(self):
        self.assertEqual(self.params["numberOfReplicas"], "1")
        self.assertEqual(self.params["dataLocality"], "strict-local")
        self.assertEqual(self.sc["reclaimPolicy"], "Delete")

    def test_waits_for_first_consumer(self):
        # D1: las demás clases del repo son Immediate; esta se separa a propósito.
        self.assertEqual(self.sc["volumeBindingMode"], "WaitForFirstConsumer")

    def test_d1_parameters(self):
        self.assertEqual(self.params["fsType"], "ext4")
        self.assertEqual(self.params["staleReplicaTimeout"], "30")
        self.assertEqual(self.params["replicaAutoBalance"], "ignored")
        self.assertTrue(self.sc["allowVolumeExpansion"])

    def test_no_node_or_disk_selector(self):
        # El nodo lo decide el nodeSelector del workload, no una etiqueta de Longhorn.
        self.assertNotIn("nodeSelector", self.params)
        self.assertNotIn("diskSelector", self.params)

    def test_reaches_the_cluster_through_the_argocd_kustomization(self):
        self.assertIn("kubernetes/storage/longhorn-strict-local.yaml", resources("kustomization.yaml"))
        self.assertIn("longhorn-strict-local.yaml", resources("kubernetes/storage/kustomization.yaml"))


if __name__ == "__main__":
    unittest.main()
