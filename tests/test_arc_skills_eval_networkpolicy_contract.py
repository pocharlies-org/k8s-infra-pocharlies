"""SC-3635 (security, 2026-10-29): perimetro de egreso de arc-skills-eval.

Los runners de este pool ejecutan skills externas (codigo de terceros) en DinD.
El contrato: solo DNS, LiteLLM:4000 e internet publico (GitHub). Una fuga del
contenedor anidado no puede alcanzar ks5-cp-* (API :6443 en la tailnet), la LAN
ni ningun otro servicio del cluster. Si alguien abre algo mas, este test corta.
"""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "networking" / "arc-skills-eval" / "networkpolicy.yaml"
ES_PATH = ROOT / "networking" / "arc-skills-eval" / "externalsecret-arc-github-app.yaml"


def _policy():
    documents = [doc for doc in yaml.safe_load_all(POLICY_PATH.read_text()) if doc]
    return next(
        doc
        for doc in documents
        if doc.get("kind") == "NetworkPolicy"
        and doc.get("metadata", {}).get("name") == "arc-skills-eval-egress"
    )


def _cidrs(policy):
    return {
        target["ipBlock"]["cidr"]
        for rule in policy["spec"]["egress"]
        for target in rule.get("to", [])
        if "ipBlock" in target
    }


def _ns_names(policy):
    return {
        target["namespaceSelector"]["matchLabels"]["kubernetes.io/metadata.name"]
        for rule in policy["spec"]["egress"]
        for target in rule.get("to", [])
        if "namespaceSelector" in target
    }


def test_policy_covers_the_whole_namespace():
    # El namespace es exclusivo del scale set: podSelector {} = runner + dind.
    assert _policy()["spec"]["podSelector"] == {}


def test_only_dns_litellm_and_public_internet_are_allowed():
    policy = _policy()
    assert _ns_names(policy) == {"kube-system", "litellm"}
    ports = {
        port["port"]
        for rule in policy["spec"]["egress"]
        for port in rule.get("ports", [])
    }
    # 53 DNS, 4000 LiteLLM. Nada mas tiene puertos nombrados: la regla de
    # internet publico va sin puertos (todo destino) y es la unica sin `to` de
    # namespace.
    assert ports == {53, 4000}


def test_litellm_is_allowed_both_views_of_the_service():
    # kube-router comprueba la ClusterIP y el destino tras el DNAT (leccion de
    # arc-openclaw): hacen falta ambas vistas para que la evaluacion funcione.
    policy = _policy()
    service_cidr = "10.43.0.0/16" in _cidrs(policy)
    litellm_ns = "litellm" in _ns_names(policy)
    assert service_cidr and litellm_ns


def test_public_internet_excludes_private_tailnet_and_link_local():
    policy = _policy()
    public_rule = next(
        rule
        for rule in policy["spec"]["egress"]
        if any(
            target.get("ipBlock", {}).get("cidr") == "0.0.0.0/0"
            for target in rule.get("to", [])
        )
    )
    excepts = {
        cidr
        for target in public_rule["to"]
        for cidr in target["ipBlock"].get("except", [])
    }
    assert excepts == {
        "10.0.0.0/8",       # cluster: pods, services (incl. API 10.43.0.1)
        "172.16.0.0/12",
        "192.168.0.0/16",   # LAN de casa
        "100.64.0.0/10",    # tailnet: ks5-cp-* (API :6443) y x86
        "169.254.0.0/16",   # link-local / metadata
    }


def test_the_control_plane_api_endpoints_are_never_allowed():
    # Los tres endpoints del API (kubernetes.default tras el DNAT) viven en la
    # tailnet. Si alguien los fijara como /32 (patron arc-openclaw), este test
    # lo recuerda: aqui el runner de evaluacion NO habla con el API.
    cidrs = _cidrs(_policy())
    for endpoint in ("100.107.21.89/32", "100.71.117.127/32", "100.75.189.75/32"):
        assert endpoint not in cidrs
    ports = {
        port["port"]
        for rule in _policy()["spec"]["egress"]
        for port in rule.get("ports", [])
    }
    assert 6443 not in ports


def test_externalsecret_reads_the_org_app_via_connect_with_onchange():
    doc = next(
        d
        for d in yaml.safe_load_all(ES_PATH.read_text())
        if d and d.get("kind") == "ExternalSecret"
    )
    assert doc["spec"]["secretStoreRef"] == {
        "kind": "ClusterSecretStore",
        "name": "onepassword-connect",
    }
    assert doc["spec"]["refreshPolicy"] == "OnChange"
    assert [d["remoteRef"]["key"] for d in doc["spec"]["data"]] == ["arc-github-app"] * 3
    assert {d["remoteRef"]["property"] for d in doc["spec"]["data"]} == {
        "app_id",
        "installation_id",
        "private_key",
    }
