"""CROSSLINK (acuerdo inter-casa pocharlies<->staticduo, 14-10-2026): el borde de
ingreso /crosslink debe estar en Git y coherente con el contrato del repo
pocharlies-org/crosslink (PR #1).

Este test fija:
  * el manifiesto existe y esta referenciado en kustomization.yaml (sin eso ArgoCD
    no lo aplica y la ruta no existe);
  * el handler del ConfigMap es stdlib puro (nada de pip en un pod readOnlyRootFilesystem)
    y respeta las invariants del contrato: bytes crudos, ventana +-300 s, limite 64 KiB,
    dedupe por tupla event_id+casa+sha256, 2xx solo tras commit durable, fail-closed sin
    keystore, y todos los 4xx terminales (el emisor nunca reintenta un 4xx);
  * el secreto NO vive en el YAML: llega por ExternalSecret Connect (crosslink-grants)
    montado readOnly en /secrets;
  * la ruta publica solo expone /crosslink/ingest y /crosslink/healthz, con TLS store
    default y entrypoint websecure (nada de http);
  * NetworkPolicy: traefik-edge es default-deny, asi que sin politica propia el borde
    no recibe trafico; la politica debe limitar al rango del proxy, no abrir el mundo;
  * colocacion node-pool ks5-nvme (PVC longhorn; leccion de synapse-brain-feedback-handler)
    y PSA sin privilegios.
"""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "networking/traefik-edge/crosslink-ingress.yaml"


def _docs():
    return [d for d in yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")) if d]


def _by_kind(kind):
    return {d["metadata"]["name"]: d for d in _docs() if d["kind"] == kind}


class CrosslinkIngressContractTest(unittest.TestCase):
    def test_manifest_is_in_kustomization(self) -> None:
        kustomization = yaml.safe_load((ROOT / "kustomization.yaml").read_text(encoding="utf-8"))
        self.assertIn(
            "networking/traefik-edge/crosslink-ingress.yaml",
            kustomization["resources"],
        )

    def test_all_objects_present(self) -> None:
        kinds = {d["kind"] for d in _docs()}
        for kind in ("ConfigMap", "ExternalSecret", "Deployment",
                     "PersistentVolumeClaim", "Service", "IngressRoute", "NetworkPolicy"):
            self.assertIn(kind, kinds)

    def test_handler_is_stdlib_and_contract_faithful(self) -> None:
        cm = _by_kind("ConfigMap")["crosslink-ingress"]
        src = cm["data"]["handler.py"]
        for forbidden in ("import requests", "import flask", "pip install", "subprocess"):
            self.assertNotIn(forbidden, src)
        # invariants del contrato
        self.assertIn("LIMIT = 65536", src)
        self.assertIn("WINDOW = 300", src)
        self.assertIn("synchronous=FULL", src)
        self.assertIn("PRAGMA journal_mode=WAL", src)
        self.assertIn("hmac.compare_digest", src)
        self.assertIn("ensure_ascii=False", src)
        self.assertIn("allow_nan=False", src)
        self.assertIn("keystore_unavailable", src)
        self.assertIn("event_id_conflict", src)
        self.assertIn('"status": "duplicate"', src)
        # la firma entra sobre bytes crudos: verify() recibe body, nunca un re-serializado
        self.assertIn("verify(secret, key_id, ts, sig, body)", src)

    def test_secret_never_in_yaml(self) -> None:
        text = MANIFEST.read_text(encoding="utf-8")
        for leak in ("crosslink-test-secret", "crosslink-secret", "SECRETO="):
            self.assertNotIn(leak, text)
        es = _by_kind("ExternalSecret")["crosslink-grants"]
        self.assertEqual(es["spec"]["secretStoreRef"]["name"], "onepassword-connect")
        self.assertEqual(es["metadata"]["annotations"]["argocd.argoproj.io/sync-wave"], "-2")

    def test_public_route_is_minimal_and_tls(self) -> None:
        ir = _by_kind("IngressRoute")["edge-crosslink-public"]
        self.assertEqual(ir["spec"]["entryPoints"], ["websecure"])
        route = ir["spec"]["routes"][0]
        self.assertIn("Path(`/crosslink/ingest`)", route["match"])
        self.assertIn("Path(`/crosslink/healthz`)", route["match"])
        self.assertNotIn("PathPrefix", route["match"])
        self.assertEqual(ir["spec"]["tls"]["store"]["name"], "default")
        ann = ir["metadata"]["annotations"]
        self.assertEqual(ann["external-dns.alpha.kubernetes.io/hostname"], "crosslink.e-dani.com")

    def test_networkpolicy_scoped_not_open(self) -> None:
        pol = _by_kind("NetworkPolicy")["crosslink-ingress-allow-edge"]
        self.assertEqual(
            pol["spec"]["podSelector"]["matchLabels"]["app.kubernetes.io/name"],
            "crosslink-ingress",
        )
        rules = pol["spec"]["ingress"]
        self.assertEqual(len(rules), 1)
        cidrs = {f["ipBlock"]["cidr"] for f in rules[0]["from"]}
        self.assertNotIn("0.0.0.0/0", cidrs)
        self.assertTrue({r["port"] for r in rules[0]["ports"]} <= {8080})

    def test_pod_is_hardened_and_placed(self) -> None:
        dep = _by_kind("Deployment")["crosslink-ingress"]
        pod = dep["spec"]["template"]["spec"]
        self.assertEqual(pod["nodeSelector"], {"node-pool": "ks5-nvme"})
        self.assertFalse(pod["automountServiceAccountToken"])
        c = pod["containers"][0]
        self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
        self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
        self.assertEqual(dep["spec"]["strategy"]["type"], "Recreate")
        mounts = {m["name"]: m for m in c["volumeMounts"]}
        vols = {v["name"]: v for v in pod["volumes"]}
        self.assertTrue(vols["grants"]["secret"]["optional"])
        self.assertTrue(mounts["grants"]["readOnly"])
        self.assertEqual(mounts["grants"]["mountPath"], "/secrets")
        env = {e["name"]: e["value"] for e in c["env"]}
        self.assertEqual(env["MY_HOUSE"], "pocharlies")
        self.assertEqual(env["CROSSLINK_KEYSTORE"], "/secrets/grants.json")


if __name__ == "__main__":
    unittest.main()
