import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
TRUSTED = ("192.168.50.0/24", "100.64.0.0/10", "10.42.0.0/16", "10.43.0.0/16")


def documents(path):
    with (ROOT / path).open(encoding="utf-8") as stream:
        return [item for item in yaml.safe_load_all(stream) if item]


def ingress(path, name):
    return next(
        item
        for item in documents(path)
        if item.get("kind") == "IngressRoute" and item["metadata"]["name"] == name
    )


def test_simple_public_panels_are_direct_only_from_trusted_networks():
    path = "networking/traefik-lan/public-panels-lan.yaml"
    expected = {
        "lan-bambulab-public-host": ("bambulab.e-dani.com", "bambulab", "bambulab", 80),
    }
    for name, (host, namespace, service, port) in expected.items():
        route = ingress(path, name)
        [rule] = route["spec"]["routes"]
        assert f"Host(`{host}`)" in rule["match"]
        assert "ingressClassName" not in route["spec"]
        assert all(cidr in rule["match"] for cidr in TRUSTED)
        assert "middlewares" not in rule
        assert rule["services"] == [{"name": service, "namespace": namespace, "port": port}]
        assert route["spec"]["tls"] == {"secretName": "wildcard-edani-tls"}


def test_skirmbooks_lan_route_is_sso_gated_with_oauth2_callback_path():
    # SKIRM-16 (D2): el bypass LAN/tailnet de skirmbooks se cierra. El break-glass
    # es kubectl port-forward al Service, no el ingress.
    route = ingress("networking/traefik-lan/public-panels-lan.yaml", "lan-skirmbooks-public-host")
    oauth2, host = route["spec"]["routes"]
    assert "ingressClassName" not in route["spec"]
    assert oauth2["priority"] == 310 and host["priority"] == 300
    assert "PathPrefix(`/oauth2`)" in oauth2["match"]
    assert "middlewares" not in oauth2
    assert oauth2["services"] == [{"name": "oauth2-proxy-skirmbooks", "namespace": "keycloak", "port": 4180}]
    assert host["middlewares"] == [{"name": "sso-skirmbooks-chain", "namespace": "keycloak"}]
    assert host["services"] == [{"name": "skirmbooks-ui", "namespace": "skirmshop", "port": 80}]
    for rule in (oauth2, host):
        assert "Host(`skirmbooks.e-dani.com`)" in rule["match"]
        assert all(cidr in rule["match"] for cidr in TRUSTED)
    assert route["spec"]["tls"] == {"secretName": "wildcard-edani-tls"}


def test_jarvis_preserves_hud_rewrite_and_trusted_catchall_without_client_identity():
    route = ingress("networking/traefik-lan/public-panels-lan.yaml", "lan-jarvis-public-host")
    hud, sso, catchall = route["spec"]["routes"]
    assert (hud["priority"], sso["priority"], catchall["priority"]) == (400, 350, 300)
    assert "ingressClassName" not in route["spec"]
    strip = {"name": "dgx-strip-identity-headers", "namespace": "traefik-lan"}
    # sin SSO en jarvis: la identidad nunca llega del cliente (es_dani del dashboard; security 03-10-2026)
    assert hud["middlewares"] == [strip, {"name": "jarvis-public-hud-shell", "namespace": "jarvis"}]
    assert catchall["middlewares"] == [strip]
    # salvo lo que DGX-809 pone tras sso-chain (detalle en test_dgx_lan_sso_secretaria_escrituras_contract.py)
    assert sso["middlewares"] == [strip, {"name": "sso-chain", "namespace": "keycloak"}]
    assert all(all(cidr in rule["match"] for cidr in TRUSTED) for rule in (hud, sso, catchall))


def test_no_route_serves_or_points_at_openchamber():
    # INFRA-824: OpenChamber se retiro el 10-10-2026 (lo sustituye Paseo). Ninguna ruta sirve sus
    # hosts (chamber, chamber-beta, chamber.lan) ni el redirect /openchamber, y ninguna apunta a un
    # Service, middleware o ServersTransport `openchamber*` que ya no existe.
    assert "openchamber" not in (ROOT / "kustomization.yaml").read_text(encoding="utf-8")
    for path in sorted((ROOT / "networking").rglob("*.yaml")):
        for item in documents(path.relative_to(ROOT)):
            if not isinstance(item, dict) or item.get("kind") != "IngressRoute":
                continue
            for rule in item["spec"]["routes"]:
                assert not re.search(r"Host\(`chamber[.-]|/openchamber", rule["match"]), (path, rule["match"])
                refs = [*rule.get("services", []), *rule.get("middlewares", [])]
                assert not any(
                    "openchamber" in ref[key] for ref in refs for key in ("name", "serversTransport") if key in ref
                ), (path, item["metadata"]["name"])


SSO_CHAIN = {"name": "sso-chain", "namespace": "keycloak"}
PASEO_HOST = "Host(`paseo.e-dani.com`)"


def assert_paseo_rules_are_sso_gated_outside_trusted_networks(route, service):
    # INFRA-825: Paseo ejecuta agentes con shell en el x86. Solo LAN/tailnet entra directo; todo lo
    # demas (y la regla comodin del host, que cubre tambien el WebSocket /ws) pasa por sso-chain.
    rules = route["spec"]["routes"]
    for rule in rules:
        assert PASEO_HOST in rule["match"]
        assert rule["services"] == [service]
        if SSO_CHAIN not in rule.get("middlewares", []):
            assert all(f"ClientIP(`{cidr}`)" in rule["match"] for cidr in TRUSTED), rule["match"]
            assert "middlewares" not in rule
    [catchall] = [rule for rule in rules if rule["match"] == PASEO_HOST]
    assert catchall["middlewares"] == [SSO_CHAIN]


def assert_x86_externalname(path, name):
    [service] = [item for item in documents(path) if item.get("kind") == "Service"]
    assert service["metadata"]["name"] == name
    assert service["spec"]["type"] == "ExternalName"
    assert service["spec"]["externalName"] == "x86.taile0ad27.ts.net"
    assert [(port["port"], port["targetPort"]) for port in service["spec"]["ports"]] == [(6767, 6767)]


def test_paseo_public_route_requires_sso_chain_outside_trusted_networks():
    path = "networking/traefik-edge/paseo-public.yaml"
    assert f"  - {path}\n" in (ROOT / "kustomization.yaml").read_text(encoding="utf-8")
    route = ingress(path, "edge-paseo-public")
    assert route["metadata"]["annotations"] == {
        "external-dns.alpha.kubernetes.io/hostname": "paseo.e-dani.com",
        "external-dns.alpha.kubernetes.io/target": "141.94.73.52,141.94.73.50,145.239.194.168,57.129.17.172",
        "external-dns.alpha.kubernetes.io/cloudflare-proxied": "true",
    }
    assert route["spec"]["ingressClassName"] == "traefik-edge"
    assert_paseo_rules_are_sso_gated_outside_trusted_networks(
        route, {"name": "paseo-edge-x86", "namespace": "traefik-edge", "port": 6767}
    )
    assert_x86_externalname(path, "paseo-edge-x86")


def test_paseo_lan_route_points_at_the_x86_externalname_on_6767():
    path = "networking/traefik-lan/paseo-lan.yaml"
    assert f"  - {path}\n" in (ROOT / "kustomization.yaml").read_text(encoding="utf-8")
    route = ingress(path, "lan-paseo")
    assert "ingressClassName" not in route["spec"]
    assert_paseo_rules_are_sso_gated_outside_trusted_networks(route, {"name": "paseo-lan-x86", "port": 6767})
    assert route["spec"]["tls"] == {"secretName": "wildcard-edani-tls"}
    assert_x86_externalname(path, "paseo-lan-x86")


def test_coredns_pins_the_x86_tailnet_name():
    config = next(
        item for item in documents("networking/dns/coredns-custom.yaml")
        if item.get("kind") == "ConfigMap" and item["metadata"]["name"] == "coredns-custom"
    )
    assert "100.83.56.98 x86.taile0ad27.ts.net" not in config["data"]["edani-public-lan.server"]
    tailnet_zone = config["data"]["x86-taile0ad27.server"]
    assert "taile0ad27.ts.net:53 {" in tailnet_zone
    assert "100.83.56.98 x86.taile0ad27.ts.net" in tailnet_zone
    assert "hosts {" in tailnet_zone
    assert "fallthrough" in tailnet_zone
    assert "forward . /etc/resolv.conf" in tailnet_zone
    assert "cache 30" in tailnet_zone
