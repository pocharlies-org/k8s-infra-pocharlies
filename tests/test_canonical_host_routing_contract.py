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
    "openclaw-k8s-readonly.e-dani.com",
    "openclaw-k8s-webhooks.e-dani.com",
    "openclaw-k8s.e-dani.com",
    "openclaw.e-dani.com",
    "picqer-mcp.e-dani.com",
    "sauvage-bot.e-dani.com",
    "skirmshop-s3-console.e-dani.com",
    "skirmshop-s3.e-dani.com",
    "stt-mcp.e-dani.com",
    "synapse.e-dani.com",
    "teslamate.e-dani.com",
    "uriel.e-dani.com",
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
    assert route["metadata"]["annotations"] == {
        "external-dns.alpha.kubernetes.io/exclude": "true"
    }


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
    } <= current


def test_retired_sauvage_alias_redirects_to_active_k8s_openclaw():
    documents_ = documents("networking/traefik-lan/openclaw-lan.yaml")
    middleware = next(item for item in documents_ if item["kind"] == "Middleware")
    route = next(item for item in documents_ if item["kind"] == "IngressRoute")
    assert middleware["spec"]["redirectRegex"] == {
        "regex": r"^https://openclaw\.lan\.e-dani\.com/(.*)",
        "replacement": "https://openclaw.e-dani.com/${1}",
        "permanent": True,
    }
    assert hosts(route) == {"openclaw.lan.e-dani.com"}
    assert route["spec"]["routes"][0]["services"] == [{
        "name": "openclaw-qwen36-openclaw",
        "namespace": "openclaw-qwen36",
        "port": 8080,
    }]


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
    assert route["metadata"]["annotations"] == {
        "external-dns.alpha.kubernetes.io/exclude": "true"
    }


def test_admin_skirmshop_panel_on_lan_asks_the_same_login_as_the_edge():
    # SKIRM-301: without it the LAN got the fixed lan-operator identity, so an
    # admin never saw «Mover» nor the Hermes profile that moves.
    route = ingress(
        "networking/traefik-lan/admin-skirmshop-canonical-lan.yaml",
        "admin-skirmshop-canonical-lan",
    )
    rules = {rule["match"]: rule for rule in route["spec"]["routes"]}
    sso = {"name": "sso-skirmshop-chain", "namespace": "keycloak"}
    for match in (
        "Host(`admin.skirmshop.es`) && PathPrefix(`/api/panel`)",
        "Host(`admin.skirmshop.es`) && Path(`/`)",
        "Host(`admin.skirmshop.es`) && PathPrefix(`/`)",
    ):
        assert rules[match]["middlewares"] == [sso]
    oauth2 = rules["Host(`admin.skirmshop.es`) && PathPrefix(`/oauth2`)"]
    assert oauth2["services"] == [
        {"name": "oauth2-proxy-skirmshop", "namespace": "keycloak", "port": 4180}
    ]
    assert "middlewares" not in oauth2
    assert all(
        middleware["name"] != "admin-lan-panel-operator-identity"
        for rule in route["spec"]["routes"]
        for middleware in rule.get("middlewares", [])
    )


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


def test_whatsapp_lan_hosts_ask_sso_except_pods_and_keep_qr_and_public_deny_on_top():
    # whatsapp-pro (SKIRM-116, acotada a /api/v1 por SC-2843): pods
    # (10.42.0.0/16) reach the connector's signed API without SSO; everything
    # else — including pods — goes through Keycloak. Explicit priorities,
    # because the rule-length default would rank the ClientIP rule above /qr.
    route = ingress(
        "networking/traefik-lan/canonical-hosts-lan.yaml",
        "canonical-hosts-lan",
    )
    host = "whatsapp-pro.e-dani.com"
    rules = {
        rule["match"]: rule
        for rule in route["spec"]["routes"]
        if f"Host(`{host}`)" in rule["match"]
    }
    pods = rules[
        f"Host(`{host}`) && ClientIP(`10.42.0.0/16`) && PathPrefix(`/api/v1`)"
    ]
    rest = rules[f"Host(`{host}`)"]
    qr = rules[f"Host(`{host}`) && PathPrefix(`/qr`)"]
    public = rules[f"Host(`{host}`) && PathPrefix(`/api/public`)"]

    assert "middlewares" not in pods
    assert [m["name"] for m in rest["middlewares"]] == ["sso-chain"]
    assert [m["name"] for m in qr["middlewares"]] == ["sso-chain"]
    assert [m["name"] for m in public["middlewares"]] == [
        "connector-public-api-deny"
    ]
    assert qr["priority"] > pods["priority"] > rest["priority"]
    assert public["priority"] > pods["priority"]
    assert pods["services"] == rest["services"] == qr["services"]


def test_whatsapp_host_lan_is_the_app_no_direct_connector_rule():
    # SC-2760: whatsapp.e-dani.com is Jordi's WhatsApp app on the LAN (its own
    # OIDC login, no sso-chain — that would double-login). SC-2843 removed the
    # ClientIP(10.42.0.0/16) && /api/v1 -> connector exception: nothing calls
    # the personal connector through this host (the app and the synapse bridge
    # proxy it via in-cluster DNS, the adapter uses the -pro host), and
    # ClientIP is not a reliable discriminator at this VIP — traffic from the
    # traefik node itself arrives SNAT-ed to 10.42.0.1, so the rule exposed the
    # connector's internal API without the app session to everything local.
    route = ingress(
        "networking/traefik-lan/canonical-hosts-lan.yaml",
        "canonical-hosts-lan",
    )
    rules = {
        rule["match"]: rule
        for rule in route["spec"]["routes"]
        if "Host(`whatsapp.e-dani.com`)" in rule["match"]
    }
    app = rules["Host(`whatsapp.e-dani.com`)"]
    public = rules["Host(`whatsapp.e-dani.com`) && PathPrefix(`/api/public`)"]

    assert "middlewares" not in app
    assert app["services"] == [
        {"name": "whatsapp-app", "namespace": "whatsapp-mcp", "port": 3080}
    ]
    assert [m["name"] for m in public["middlewares"]] == [
        "connector-public-api-deny"
    ]
    assert public["priority"] > app["priority"]
    assert not [m for m in rules if "ClientIP" in m]
    assert "Host(`whatsapp.e-dani.com`) && PathPrefix(`/qr`)" not in rules
