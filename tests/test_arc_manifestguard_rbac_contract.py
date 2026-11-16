"""Contrato de INFRA-1407 (P1 de INFRA-1405): el runner del guard de manifiestos lee CRDs y nada más.

Dos guardas, ambas leídas del YAML (sin clúster, como tests/test_arc_openclaw_networkpolicy_contract.py):

1. El RBAC es de SOLO LECTURA sobre un único recurso, ligado a la identidad del scale set
   `arc-manifestguard`, y llega al clúster por ArgoCD (está en el kustomization de la raíz). Es la
   frontera de privilegios de la épica: un verbo de escritura añadido aquí, o un segundo recurso,
   debe romper la CI.
2. La NetworkPolicy del pool abre SOLO la API de Kubernetes (pre-DNAT y post-DNAT). Si alguien
   añade un `0.0.0.0/0` o la tailnet entera, el job del guard volvería a poder hablar con el :19900
   del x86: eso es exactamente lo que la NetworkPolicy de arc-runners existe para evitar.
"""

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RBAC_PATH = ROOT / "platform" / "arc" / "rbac-manifestguard.yaml"
POLICY_PATH = ROOT / "networking" / "arc-runners" / "networkpolicy.yaml"

SA_NAME = "arc-manifestguard-cr-reader"
API_ENDPOINTS = {"100.107.21.89/32", "100.71.117.127/32", "100.75.189.75/32"}
WRITE_VERBS = {"create", "update", "patch", "delete", "deletecollection", "*"}


def _documents(path):
    return [doc for doc in yaml.safe_load_all(path.read_text()) if doc]


def _by_kind(kind, name=None):
    for doc in _documents(RBAC_PATH):
        if doc.get("kind") == kind and (name is None or doc["metadata"]["name"] == name):
            return doc
    raise AssertionError(f"{kind} {name} no existe en {RBAC_PATH.relative_to(ROOT)}")


class ArcManifestguardRbacContractTest(unittest.TestCase):
    def test_service_account_lives_in_arc_runners(self):
        sa = _by_kind("ServiceAccount", SA_NAME)
        self.assertEqual(sa["metadata"]["namespace"], "arc-runners")

    def test_cluster_role_is_read_only_on_the_crd_resource_alone(self):
        role = _by_kind("ClusterRole", SA_NAME)
        rules = role["rules"]
        self.assertEqual(len(rules), 1, "el guard no necesita ningún otro recurso")
        rule = rules[0]
        self.assertEqual(rule["apiGroups"], ["apiextensions.k8s.io"])
        self.assertEqual(rule["resources"], ["customresourcedefinitions"])
        self.assertEqual(set(rule["verbs"]), {"get", "list", "watch"})
        self.assertFalse(set(rule["verbs"]) & WRITE_VERBS)

    def test_cluster_role_binding_binds_only_that_service_account(self):
        binding = _by_kind("ClusterRoleBinding", SA_NAME)
        self.assertEqual(
            binding["roleRef"],
            {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": SA_NAME,
            },
        )
        # cluster-scoped: un RoleBinding no otorga acceso a customresourcedefinitions.
        self.assertEqual(
            binding["subjects"],
            [{"kind": "ServiceAccount", "name": SA_NAME, "namespace": "arc-runners"}],
        )

    def test_rbac_is_delivered_by_argocd_not_by_hand(self):
        kustomization = (ROOT / "kustomization.yaml").read_text()
        self.assertIn("platform/arc/rbac-manifestguard.yaml", kustomization)


class ArcManifestguardNetworkPolicyContractTest(unittest.TestCase):
    def _policy(self):
        return next(
            doc
            for doc in _documents(POLICY_PATH)
            if doc.get("kind") == "NetworkPolicy"
            and doc.get("metadata", {}).get("name") == "arc-manifestguard-cluster-egress"
        )

    def test_policy_selects_only_the_manifestguard_pool(self):
        policy = self._policy()
        self.assertEqual(
            policy["spec"]["podSelector"],
            {"matchLabels": {"actions.github.com/scale-set-name": "arc-manifestguard"}},
        )
        self.assertEqual(policy["spec"]["policyTypes"], ["Egress"])

    def test_policy_opens_only_the_kubernetes_api(self):
        by_cidr = {}
        for rule in self._policy()["spec"]["egress"]:
            ports = {(port["protocol"], port["port"]) for port in rule.get("ports", [])}
            for target in rule["to"]:
                cidr = target["ipBlock"]["cidr"]
                by_cidr.setdefault(cidr, set()).update(ports)
        self.assertEqual(
            by_cidr,
            {
                # pre-DNAT: la ClusterIP del service `kubernetes`.
                "10.43.0.0/16": {("TCP", 443)},
                # post-DNAT: los endpoints hostNetwork del API server.
                **{cidr: {("TCP", 6443)} for cidr in API_ENDPOINTS},
            },
        )
        self.assertNotIn("0.0.0.0/0", by_cidr)
        self.assertNotIn("100.64.0.0/10", by_cidr)
        # El x86 (el :19900 sin auth que motivó la baseline) sigue fuera del pool.
        self.assertNotIn("100.83.56.98/32", by_cidr)


if __name__ == "__main__":
    unittest.main()
