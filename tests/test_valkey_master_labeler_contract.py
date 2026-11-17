"""Contratos del etiquetador de master valkey (SC-5880).

1. La decisión pura (qué pod etiquetar/desetiquetar dada la dirección que
   reporta Sentinel y la lista de pods) — stdlib, sin redis ni kubernetes.
2. Los manifiestos de databases/postgres-shared/shared-valkey.yaml: Role
   sin pods/exec, sin bucle `sleep`/`kubectl exec`, NetworkPolicy que deja
   al labeler hablar con Sentinel (26379), y los Services *-master sin
   cambiar de selector (contrato de los consumidores).
"""

import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "databases" / "valkey-master-labeler" / "src"))

from valkey_master_labeler.decision import LABEL_KEY, LABEL_VALUE, plan_label_patches  # noqa: E402

MANIFEST = ROOT / "databases" / "postgres-shared" / "shared-valkey.yaml"


def pod(name, ip, role=None):
    labels = {"app": "shared-valkey"}
    if role is not None:
        labels[LABEL_KEY] = role
    return {"name": name, "ip": ip, "labels": labels}


# Estado estable del nuevo diseño: solo el master lleva la etiqueta (el
# Service *-master selecciona valkey-role=master; los demás no la llevan).
PODS = [
    pod("shared-valkey-0", "10.42.1.10"),
    pod("shared-valkey-1", "10.42.1.11", "master"),
    pod("shared-valkey-2", "10.42.1.12"),
]


class TestPlanLabelPatches(unittest.TestCase):
    def test_master_por_fqdn_sin_cambio(self):
        # Sentinel con announce-hostnames: responde el FQDN del pod master.
        addr = "shared-valkey-1.shared-valkey-headless.databases.svc.cluster.local"
        self.assertEqual(plan_label_patches(addr, PODS), [])

    def test_master_por_ip_sin_cambio(self):
        self.assertEqual(plan_label_patches("10.42.1.11", PODS), [])

    def test_etiquetas_replica_del_bucle_viejo_se_quitan(self):
        # El bucle `sleep 20` estampaba valkey-role=replica; el nuevo diseño
        # solo etiqueta el master — la primera reconciliación converge.
        old = [
            pod("shared-valkey-0", "10.42.1.10", "replica"),
            pod("shared-valkey-1", "10.42.1.11", "master"),
            pod("shared-valkey-2", "10.42.1.12", "replica"),
        ]
        self.assertEqual(
            plan_label_patches("10.42.1.11", old),
            [("shared-valkey-0", None), ("shared-valkey-2", None)],
        )

    def test_failover_etiqueta_nuevo_y_quita_viejo(self):
        addr = "shared-valkey-0.shared-valkey-headless.databases.svc.cluster.local"
        self.assertEqual(
            plan_label_patches(addr, PODS),
            [("shared-valkey-0", LABEL_VALUE), ("shared-valkey-1", None)],
        )

    def test_pod_recreado_nace_sin_etiqueta_y_se_reetiqueta(self):
        # shared-valkey-1 recreado (sin valkey-role) siendo aún el master:
        # el watch dispara la reconciliación y recupera la etiqueta sin reloj.
        recreated = [pod("shared-valkey-1", "10.42.1.11")]
        self.assertEqual(
            plan_label_patches("10.42.1.11", recreated),
            [("shared-valkey-1", LABEL_VALUE)],
        )

    def test_sin_coincidencia_no_toca_nada(self):
        # Sentinel reporta un pod que aún no existe (failover en curso):
        # quitar la etiqueta a todos dejaría el Service *-master sin endpoints.
        self.assertEqual(plan_label_patches("shared-valkey-9.headless", PODS), [])
        self.assertEqual(plan_label_patches(None, PODS), [])
        self.assertEqual(plan_label_patches("", PODS), [])

    def test_sin_pods_no_falla(self):
        self.assertEqual(plan_label_patches("10.42.1.11", []), [])


class TestManifests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.docs = [d for d in yaml.safe_load_all(MANIFEST.read_text()) if d]

    def by_kind(self, kind, name=None):
        out = [d for d in self.docs if d["kind"] == kind]
        if name is not None:
            out = [d for d in out if d["metadata"]["name"] == name]
        return out

    def test_role_sin_pods_exec_y_con_watch(self):
        roles = self.by_kind("Role", "shared-valkey-master-labeler")
        self.assertEqual(len(roles), 1)
        rules = roles[0]["rules"]
        self.assertFalse(
            any("pods/exec" in r.get("resources", []) for r in rules),
            "el Role no puede conservar pods/exec (reducción de privilegio SC-5880)",
        )
        pod_rules = [r for r in rules if "pods" in r.get("resources", [])]
        self.assertEqual(len(pod_rules), 1)
        self.assertEqual(sorted(pod_rules[0]["verbs"]), ["get", "list", "patch", "watch"])

    def test_deployment_sin_bucle_de_reloj_ni_exec(self):
        deploys = self.by_kind("Deployment", "shared-valkey-master-labeler")
        self.assertEqual(len(deploys), 1)
        container = deploys[0]["spec"]["template"]["spec"]["containers"][0]
        blob = str(container)
        self.assertNotIn("sleep", blob)
        self.assertNotIn("kubectl", blob)
        self.assertNotIn("exec", blob)
        self.assertTrue(
            container["image"].startswith("harbor.e-dani.com/homelab/valkey-master-labeler"),
            container["image"],
        )
        # Nunca :latest ni sin tag (Kyverno disallow-latest-tag; el digest
        # se fija tras el primer build — INFRA-1300).
        tag = container["image"].rsplit("/", 1)[-1]
        self.assertIn(":", tag)
        self.assertFalse(tag.endswith(":latest"))
        env = {e["name"]: e for e in container["env"]}
        for key in ("NAMESPACE", "MASTER_NAME", "SENTINEL_HOST", "SENTINEL_PORT",
                    "SENTINEL_PASSWORD", "POD_SELECTOR"):
            self.assertIn(key, env)
        self.assertEqual(env["MASTER_NAME"]["value"], "shared-cache-master")
        self.assertEqual(env["SENTINEL_HOST"]["value"], "shared-valkey-sentinel")
        self.assertEqual(env["POD_SELECTOR"]["value"], "app=shared-valkey")

    def test_networkpolicy_deja_al_labeler_hablar_con_sentinel(self):
        policies = self.by_kind("NetworkPolicy", "shared-valkey-ingress")
        self.assertEqual(len(policies), 1)
        allowed = []
        for rule in policies[0]["spec"]["ingress"]:
            for frm in rule.get("from", []):
                sel = (frm.get("podSelector") or {}).get("matchLabels", {})
                if sel.get("app") == "shared-valkey-master-labeler":
                    allowed += [p["port"] for p in rule.get("ports", [])]
        self.assertIn(26379, allowed)
        # El labeler no toca 6379: no se le abre.
        self.assertNotIn(6379, allowed)

    def test_services_master_son_contrato(self):
        # shared-valkey-master / labels-valkey-master: ni renombrados ni con
        # selector cambiado (contrato de los consumidores, nota architect E6).
        services = self.by_kind("Service", "shared-valkey-master")
        self.assertEqual(len(services), 1)
        self.assertEqual(
            services[0]["spec"]["selector"],
            {"app": "shared-valkey", "valkey-role": "master"},
        )
        self.assertEqual([p["port"] for p in services[0]["spec"]["ports"]], [6379])


if __name__ == "__main__":
    unittest.main()
