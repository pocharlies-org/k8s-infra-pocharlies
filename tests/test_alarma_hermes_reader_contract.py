"""DGX-702 (épica DGX-674, P3b): el ClusterSecretStore kubernetes que da a Hermes el HMAC de la
clase `hermes` de la alarma (`dgx-dashboard-alarma-hermes`, clave `ALARMA_HMAC_HERMES`, creado por
dgx-infra#1062), y su RBAC mínimo. Espejo de `test_pagos_hermes_reader_contract.py`.

Un store por Secret: el de pagos NO se amplía. El alcance es lo que hace segura la apertura: `get`
exacto sobre ese único nombre, una sola identidad (la SA del store) y nada más. Un `list`/`watch`,
un resourceNames suelto, otro Secret, una regla extra o un segundo sujeto en el RoleBinding son
escándalo.

`violaciones(docs)` es la única definición del contrato: el manifiesto real debe devolver `[]` y
cada mutación del RBAC (clase `MutacionesDelRbac`) debe devolver al menos una.
"""
import copy
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
ES = ROOT / "platform" / "external-secrets"
STORE = ES / "cluster-secret-store-control-nexus-alarma.yaml"
PAGOS = ES / "cluster-secret-store-control-nexus-pagos.yaml"
KUSTOMIZATION = ROOT / "kustomization.yaml"

STORE_NAME = "kubernetes-control-nexus-alarma"
SA = "eso-control-nexus-alarma-reader"
SECRET = "dgx-dashboard-alarma-hermes"
OLA = "argocd.argoproj.io/sync-wave"


def _docs(path=STORE):
    return [d for d in yaml.safe_load_all(path.read_text()) if d]


def _de(docs, kind):
    return [d for d in docs if d["kind"] == kind]


def _ola(d):
    return int((d["metadata"].get("annotations") or {}).get(OLA, "0"))


def violaciones(docs):
    """Todo lo que el manifiesto hace distinto del contrato; vacío = cumple."""
    v = []
    kinds = sorted(d["kind"] for d in docs)
    if kinds != ["ClusterSecretStore", "Role", "RoleBinding", "ServiceAccount"]:
        return [f"recursos distintos de store+SA+Role+RoleBinding: {kinds}"]
    (store,) = _de(docs, "ClusterSecretStore")
    (sa,) = _de(docs, "ServiceAccount")
    (role,) = _de(docs, "Role")
    (binding,) = _de(docs, "RoleBinding")

    if store["metadata"]["name"] != STORE_NAME:
        v.append("nombre del store")
    k = store["spec"]["provider"].get("kubernetes", {})
    if k.get("auth", {}).get("serviceAccount") != {"name": SA, "namespace": "hermes"}:
        v.append("el store no autentica con la SA de hermes")
    if k.get("remoteNamespace") != "control-nexus":
        v.append("remoteNamespace")
    if k.get("server", {}).get("url") != "kubernetes.default":
        v.append("server.url")
    if k.get("server", {}).get("caProvider") != {"type": "ConfigMap", "name": "kube-root-ca.crt",
                                                 "namespace": "control-nexus", "key": "ca.crt"}:
        v.append("caProvider")

    if (sa["metadata"]["name"], sa["metadata"]["namespace"]) != (SA, "hermes"):
        v.append("identidad de la SA")
    if role["metadata"]["namespace"] != "control-nexus":
        v.append("el Role no vive en control-nexus")
    secretos = [r for r in role["rules"] if "secrets" in (r.get("resources") or [])]
    if len(secretos) != 1:
        v.append(f"reglas sobre secrets: {len(secretos)} (debe haber una)")
    else:
        r = secretos[0]
        if r.get("apiGroups") != [""] or r.get("resources") != ["secrets"]:
            v.append("la regla de secrets no es solo core/secrets")
        if r.get("verbs") != ["get"]:
            v.append(f"verbos {r.get('verbs')} (solo get)")
        if r.get("resourceNames") != [SECRET]:
            v.append(f"resourceNames {r.get('resourceNames')} (solo {SECRET})")
    demas = [(r.get("apiGroups"), r.get("resources"), r.get("verbs"))
             for r in role["rules"] if "secrets" not in (r.get("resources") or [])]
    if demas != [(["authorization.k8s.io"], ["selfsubjectrulesreviews"], ["create"])]:
        v.append(f"reglas extra: {demas}")  # solo la validación del store

    if binding["metadata"]["namespace"] != "control-nexus":
        v.append("el RoleBinding no vive en control-nexus")
    if binding["roleRef"] != {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": role["metadata"]["name"]}:
        v.append("roleRef")
    if binding["subjects"] != [{"kind": "ServiceAccount", "name": SA, "namespace": "hermes"}]:
        v.append("sujetos del RoleBinding (la SA del store y ninguna otra)")

    if _ola(store) != -4:
        v.append("el store no va en la oleada -4")
    for d in (sa, role, binding):
        if _ola(d) >= _ola(store):
            v.append(f"{d['kind']} no va antes que el store en las oleadas")
    return v


class AlarmaHermesReaderContract(unittest.TestCase):
    def test_el_manifiesto_existe_y_cumple_el_contrato(self):
        self.assertTrue(STORE.exists(), f"falta {STORE.relative_to(ROOT)}")
        self.assertEqual(violaciones(_docs()), [])

    def test_el_fichero_entra_por_el_kustomization(self):
        resources = yaml.safe_load(KUSTOMIZATION.read_text())["resources"]
        self.assertIn(STORE.relative_to(ROOT).as_posix(), resources)

    def test_el_store_de_pagos_no_se_amplia(self):
        pagos = _docs(PAGOS)
        (role,) = _de(pagos, "Role")
        (regla,) = [r for r in role["rules"] if r.get("resources") == ["secrets"]]
        self.assertEqual(sorted(regla["resourceNames"]), ["dgx-dashboard-pagos", "dgx-dashboard-pagos-decision"])
        self.assertNotIn(SECRET, PAGOS.read_text())

    def test_el_store_de_alarma_no_toca_los_secretos_de_pagos(self):
        self.assertNotIn("dgx-dashboard-pagos", STORE.read_text())


class MutacionesDelRbac(unittest.TestCase):
    """El contrato tiene que fallar cuando alguien amplía el RBAC (criterio 2 de DGX-702)."""

    def _muta(self, f):
        docs = copy.deepcopy(_docs())
        f(_de(docs, "Role")[0], docs)
        self.assertTrue(violaciones(docs), "la mutación pasó el contrato")

    def _regla_secretos(self, role):
        return next(r for r in role["rules"] if r.get("resources") == ["secrets"])

    def test_verbo_list(self):
        self._muta(lambda role, _: self._regla_secretos(role)["verbs"].append("list"))

    def test_verbo_watch(self):
        self._muta(lambda role, _: self._regla_secretos(role)["verbs"].append("watch"))

    def test_otro_secret(self):
        self._muta(lambda role, _: self._regla_secretos(role)["resourceNames"].append("dgx-dashboard-pagos"))

    def test_sin_resource_names(self):
        self._muta(lambda role, _: self._regla_secretos(role).pop("resourceNames"))

    def test_regla_extra_sobre_secrets(self):
        self._muta(lambda role, _: role["rules"].append(
            {"apiGroups": [""], "resources": ["secrets"], "verbs": ["list"]}))

    def test_regla_extra_cualquiera(self):
        self._muta(lambda role, _: role["rules"].append(
            {"apiGroups": [""], "resources": ["configmaps"], "verbs": ["get"]}))

    def test_segundo_sujeto_en_el_binding(self):
        def f(_, docs):
            _de(docs, "RoleBinding")[0]["subjects"].append(
                {"kind": "ServiceAccount", "name": "otra", "namespace": "hermes"})
        self._muta(f)

    def test_binding_en_otra_oleada(self):
        def f(_, docs):
            _de(docs, "RoleBinding")[0]["metadata"]["annotations"][OLA] = "0"
        self._muta(f)


if __name__ == "__main__":
    unittest.main()
