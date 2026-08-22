from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]


def documents(path):
    with (ROOT / path).open(encoding="utf-8") as stream:
        return [item for item in yaml.safe_load_all(stream) if item]


def ingress(path, name):
    return next(
        item
        for item in documents(path)
        if item.get("kind") == "IngressRoute" and item["metadata"]["name"] == name
    )


def hosts(route):
    return {
        host
        for rule in route["spec"]["routes"]
        for host in re.findall(r"Host\(`([^`]+)`\)", rule["match"])
    }


CANONICAL_LAN_HOSTS = {
    "adguard-setup.e-dani.com",
    "adguard.e-dani.com",
    "agentgateway-mcp-stg.e-dani.com",
    "agentgateway-mcp.e-dani.com",
    "alertmanager.e-dani.com",
    "argocd.e-dani.com",
    "aurora-api.e-dani.com",
    "aurora.e-dani.com",
    "brain-ingest-k8s.e-dani.com",
    "brain-k8s.e-dani.com",
    "dgx-synapse-mcp.e-dani.com",
    "firecrawl.e-dani.com",
    "grafana.e-dani.com",
    "ha-dashboard.e-dani.com",
    "harbor.e-dani.com",
    "home-assistant.e-dani.com",
    "keep-api.e-dani.com",
    "keep.e-dani.com",
    "langfuse.e-dani.com",
    "libreplay.e-dani.com",
    "litellm.e-dani.com",
    "longhorn.e-dani.com",
    "mcp-socialmedia.e-dani.com",
    "minio-s3.e-dani.com",
    "minio.e-dani.com",
    "multichamber.e-dani.com",
    "openclaw-k8s-readonly.e-dani.com",
    "openclaw-k8s-webhooks.e-dani.com",
    "openclaw-k8s.e-dani.com",
    "openclaw-sauvage.e-dani.com",
    "openclaw-synapse.e-dani.com",
    "openclaw-webhooks.e-dani.com",
    "openclaw.e-dani.com",
    "picqer-mcp.e-dani.com",
    "sauvage-bot.e-dani.com",
    "skirmshop-s3-console.e-dani.com",
    "skirmshop-s3.e-dani.com",
    "stt-mcp.e-dani.com",
    "synapse.e-dani.com",
    "teslamate.e-dani.com",
    "uriel.e-dani.com",
    "vault.e-dani.com",
    "vm.e-dani.com",
    "whatsapp-pro.e-dani.com",
    "whatsapp.e-dani.com",
}


API_EDGE_HOSTS = {
    "agentgateway-mcp.e-dani.com",
    "dgx-synapse-mcp.e-dani.com",
    "litellm.e-dani.com",
    "mcp-socialmedia.e-dani.com",
    "minio-s3.e-dani.com",
    "picqer-mcp.e-dani.com",
    "stt-mcp.e-dani.com",
}


def test_all_new_lan_routes_use_canonical_names_and_public_wildcard():
    route = ingress(
        "networking/traefik-lan/canonical-hosts-lan.yaml",
        "canonical-hosts-lan",
    )
    assert CANONICAL_LAN_HOSTS == hosts(route)
    assert all(".lan." not in rule["match"] for rule in route["spec"]["routes"])
    assert route["spec"]["tls"] == {"secretName": "wildcard-edani-tls"}
    assert "ingressClassName" not in route["spec"]


def test_multichamber_keeps_keycloak_on_the_lan_path():
    route = ingress(
        "networking/traefik-lan/canonical-hosts-lan.yaml",
        "canonical-hosts-lan",
    )
    rules = [
        rule
        for rule in route["spec"]["routes"]
        if "Host(`multichamber.e-dani.com`)" in rule["match"]
    ]
    assert [rule["priority"] for rule in rules] == [150, 100]
    assert rules[0]["middlewares"] == [
        {"name": "sso-forward-auth", "namespace": "keycloak"}
    ]
    assert rules[1]["middlewares"] == [
        {"name": "sso-chain", "namespace": "keycloak"}
    ]
    assert all("ClientIP(" not in rule["match"] for rule in rules)


def test_openclaw_synapse_has_a_lan_sso_fallback():
    route = ingress(
        "networking/traefik-lan/canonical-hosts-lan.yaml",
        "canonical-hosts-lan",
    )
    rules = [
        rule
        for rule in route["spec"]["routes"]
        if "Host(`openclaw-synapse.e-dani.com`)" in rule["match"]
    ]
    assert [rule["priority"] for rule in rules] == [1000, 100]
    assert rules[1]["middlewares"] == [
        {"name": "sso-chain", "namespace": "keycloak"}
    ]


def test_public_ui_routes_are_sso_gated_and_dns_is_wildcard_owned():
    path = "networking/traefik-edge/canonical-hosts-public.yaml"
    ui = ingress(path, "canonical-ui-hosts-public")
    api = ingress(path, "canonical-api-hosts-public")

    assert ui["spec"]["ingressClassName"] == "traefik-edge"
    assert api["spec"]["ingressClassName"] == "traefik-edge"
    for route in (ui, api):
        assert route["metadata"]["annotations"] == {
            "external-dns.alpha.kubernetes.io/exclude": "true"
        }
    assert hosts(api) == API_EDGE_HOSTS

    for rule in ui["spec"]["routes"]:
        middleware_names = {item["name"] for item in rule.get("middlewares", [])}
        assert "sso-chain" in middleware_names
    for rule in api["spec"]["routes"]:
        assert "middlewares" not in rule


def test_colliding_legacy_hosts_have_unambiguous_canonical_names():
    route = ingress(
        "networking/traefik-lan/canonical-hosts-lan.yaml",
        "canonical-hosts-lan",
    )
    current = hosts(route)
    assert {
        "minio-s3.e-dani.com",
        "openclaw-k8s-webhooks.e-dani.com",
        "openclaw-sauvage.e-dani.com",
    } <= current


def test_admin_skirmshop_has_a_dedicated_lan_certificate_and_route():
    path = "networking/traefik-lan/admin-skirmshop-canonical-lan.yaml"
    cert = next(item for item in documents(path) if item["kind"] == "Certificate")
    route = ingress(path, "admin-skirmshop-canonical-lan")
    assert cert["spec"]["dnsNames"] == ["admin.skirmshop.es"]
    assert cert["spec"]["secretName"] == "admin-skirmshop-canonical-tls"
    assert hosts(route) == {"admin.skirmshop.es"}
    assert route["spec"]["tls"] == {
        "secretName": "admin-skirmshop-canonical-tls"
    }


def test_edge_watches_every_namespace_used_by_canonical_routes():
    route_documents = documents(
        "networking/traefik-edge/canonical-hosts-public.yaml"
    )
    service_namespaces = {
        service["namespace"]
        for document in route_documents
        for rule in document["spec"]["routes"]
        for service in rule["services"]
    }
    values = documents("networking/traefik-edge/values.yaml")[0]
    providers = values["providers"]
    assert service_namespaces <= set(
        providers["kubernetesCRD"]["namespaces"]
    )


def test_external_dns_honors_canonical_route_exclusions():
    values = documents("networking/external-dns/values.yaml")[0]
    assert values["annotationFilter"] == (
        "external-dns.alpha.kubernetes.io/exclude notin (true)"
    )


def test_openclaw_synapse_allows_only_edge_nodes_on_its_http_port():
    policy = documents(
        "networking/traefik-edge/canonical-hosts-networkpolicy.yaml"
    )[0]
    assert policy["kind"] == "NetworkPolicy"
    assert policy["spec"]["policyTypes"] == ["Ingress"]
    ingress = policy["spec"]["ingress"]
    assert ingress[0]["ports"] == [{"protocol": "TCP", "port": 8791}]
    assert {item["ipBlock"]["cidr"] for item in ingress[0]["from"]} == {
        "100.71.117.127/32",
        "100.75.189.75/32",
        "100.107.21.89/32",
        "100.109.183.9/32",
    }
