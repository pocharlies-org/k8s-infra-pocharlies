from pathlib import Path
import shutil
import subprocess
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "databases" / "postgres-shared"
MANIFEST = BASE / "shared-valkey.yaml"
RUNBOOK = ROOT / "docs" / "runbook-litellm-shared-valkey-ha-prerequisite.md"


def load_documents(text: str):
    return [document for document in yaml.safe_load_all(text) if document]


def find_resource(documents, kind: str, name: str):
    return next(
        document
        for document in documents
        if document["kind"] == kind and document["metadata"]["name"] == name
    )


class SharedValkeyLitellmHaContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = MANIFEST.read_text(encoding="utf-8")
        cls.documents = load_documents(cls.text)

    def test_three_pods_are_required_on_three_core_hostnames(self) -> None:
        statefulset = find_resource(self.documents, "StatefulSet", "shared-valkey")
        self.assertEqual(statefulset["spec"]["replicas"], 3)
        pod_spec = statefulset["spec"]["template"]["spec"]
        self.assertEqual(pod_spec["nodeSelector"], {"workload": "core"})

        anti_affinity = pod_spec["affinity"]["podAntiAffinity"]
        self.assertNotIn("preferredDuringSchedulingIgnoredDuringExecution", anti_affinity)
        self.assertEqual(
            anti_affinity["requiredDuringSchedulingIgnoredDuringExecution"],
            [
                {
                    "labelSelector": {"matchLabels": {"app": "shared-valkey"}},
                    "topologyKey": "kubernetes.io/hostname",
                }
            ],
        )
        self.assertEqual(
            pod_spec["topologySpreadConstraints"],
            [
                {
                    "maxSkew": 1,
                    "minDomains": 3,
                    "topologyKey": "kubernetes.io/hostname",
                    "whenUnsatisfiable": "DoNotSchedule",
                    "nodeAffinityPolicy": "Honor",
                    "nodeTaintsPolicy": "Honor",
                    "labelSelector": {"matchLabels": {"app": "shared-valkey"}},
                }
            ],
        )

    def test_pdb_preserves_sentinel_quorum(self) -> None:
        pdb = find_resource(self.documents, "PodDisruptionBudget", "shared-valkey")
        self.assertEqual(pdb["apiVersion"], "policy/v1")
        self.assertEqual(pdb["metadata"]["namespace"], "databases")
        self.assertEqual(pdb["spec"]["minAvailable"], 2)
        self.assertEqual(
            pdb["spec"]["selector"], {"matchLabels": {"app": "shared-valkey"}}
        )

    def test_litellm_gets_only_the_valkey_data_port(self) -> None:
        policy = find_resource(
            self.documents, "NetworkPolicy", "shared-valkey-ingress"
        )
        litellm_rules = []
        for rule in policy["spec"]["ingress"]:
            for source in rule.get("from", []):
                namespace = source.get("namespaceSelector", {}).get(
                    "matchLabels", {}
                )
                pod = source.get("podSelector", {}).get("matchLabels", {})
                if namespace.get("kubernetes.io/metadata.name") == "litellm":
                    self.assertEqual(pod, {"app": "litellm"})
                    litellm_rules.append(rule)
        self.assertEqual(len(litellm_rules), 1)
        self.assertEqual(
            litellm_rules[0]["ports"], [{"protocol": "TCP", "port": 6379}]
        )

    def test_services_sentinel_aof_and_longhorn_are_unchanged(self) -> None:
        expected_service_ports = {
            "shared-valkey-headless": [6379, 26379, 9121],
            "shared-valkey-sentinel": [26379],
            "shared-valkey-master": [6379],
        }
        for name, expected_ports in expected_service_ports.items():
            service = find_resource(self.documents, "Service", name)
            self.assertEqual(
                [port["port"] for port in service["spec"]["ports"]], expected_ports
            )

        config = find_resource(self.documents, "ConfigMap", "shared-valkey-scripts")
        valkey_script = config["data"]["start-valkey.sh"]
        sentinel_script = config["data"]["start-sentinel.sh"]
        self.assertIn("--appendonly yes --appendfsync everysec", valkey_script)
        self.assertIn(
            "sentinel monitor shared-cache-master shared-valkey-0.${HEADLESS} 6379 2",
            sentinel_script,
        )
        self.assertIn("sentinel parallel-syncs shared-cache-master 1", sentinel_script)

        statefulset = find_resource(self.documents, "StatefulSet", "shared-valkey")
        claim = statefulset["spec"]["volumeClaimTemplates"][0]["spec"]
        self.assertEqual(claim["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(claim["storageClassName"], "longhorn")
        self.assertEqual(claim["resources"]["requests"]["storage"], "2Gi")
        self.assertFalse(any(doc["kind"] == "Secret" for doc in self.documents))

    def test_runbook_keeps_litellm_cutover_fail_closed(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("Do not scale LiteLLM above one replica", runbook)
        self.assertIn("Do not edit `shared-valkey-acl`", runbook)
        self.assertIn("TCP `26379`", runbook)
        self.assertIn("remains closed", runbook)
        self.assertIn("Make-before-break blocker for LiteLLM", runbook)
        self.assertIn("controlled Valkey failover", runbook)

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_postgres_shared_kustomization_renders_the_contract(self) -> None:
        result = subprocess.run(
            ["kubectl", "kustomize", str(BASE)],
            check=True,
            text=True,
            capture_output=True,
        )
        rendered = load_documents(result.stdout)
        statefulset = find_resource(rendered, "StatefulSet", "shared-valkey")
        pdb = find_resource(rendered, "PodDisruptionBudget", "shared-valkey")
        policy = find_resource(rendered, "NetworkPolicy", "shared-valkey-ingress")
        self.assertEqual(statefulset["spec"]["replicas"], 3)
        self.assertEqual(pdb["spec"]["minAvailable"], 2)
        self.assertEqual(policy["metadata"]["namespace"], "databases")


if __name__ == "__main__":
    unittest.main()
