from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _documents(relative_path):
    with (ROOT / relative_path).open(encoding="utf-8") as stream:
        return [document for document in yaml.safe_load_all(stream) if document]


def _resource(documents, kind, name):
    return next(
        document
        for document in documents
        if document.get("kind") == kind
        and document.get("metadata", {}).get("name") == name
    )


def test_public_opencode_always_uses_keycloak():
    documents = _documents("networking/traefik-edge/opencode-public.yaml")
    route = _resource(documents, "IngressRoute", "edge-opencode-public")
    [public] = route["spec"]["routes"]

    assert public["priority"] == 100
    assert public["middlewares"] == [{"name": "sso-chain", "namespace": "keycloak"}]
    assert public["services"] == [
        {"name": "opencode-edge-host", "namespace": "traefik-edge", "port": 19900}
    ]


def test_lan_opencode_bypasses_sso_only_for_trusted_networks():
    documents = _documents("networking/traefik-lan/opencode-lan.yaml")
    service = _resource(documents, "Service", "opencode-lan-host")
    route = _resource(documents, "IngressRoute", "lan-opencode-public-host")
    [trusted] = route["spec"]["routes"]

    assert trusted["priority"] == 300
    assert "middlewares" not in trusted
    assert "Host(`code.e-dani.com`)" in trusted["match"]
    assert trusted["services"] == [{"name": "opencode-lan-host", "port": 19900}]
    assert route["spec"]["tls"] == {"secretName": "wildcard-edani-tls"}
    assert "type" not in service["spec"]
    endpoint = _resource(documents, "EndpointSlice", "opencode-lan-host")
    assert endpoint["endpoints"] == [{"addresses": ["100.83.56.98"], "conditions": {}}]
