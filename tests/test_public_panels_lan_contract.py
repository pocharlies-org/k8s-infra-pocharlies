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
    hud, catchall = route["spec"]["routes"]
    assert hud["priority"] == 400 and catchall["priority"] == 300
    assert "ingressClassName" not in route["spec"]
    strip = {"name": "dgx-strip-identity-headers", "namespace": "traefik-lan"}
    # sin SSO en jarvis: la identidad nunca llega del cliente (es_dani del dashboard; security 03-10-2026)
    assert hud["middlewares"] == [strip, {"name": "jarvis-public-hud-shell", "namespace": "jarvis"}]
    assert catchall["middlewares"] == [strip]
    assert all(all(cidr in rule["match"] for cidr in TRUSTED) for rule in (hud, catchall))


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
