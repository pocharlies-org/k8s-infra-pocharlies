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
        "lan-skirmbooks-public-host": ("skirmbooks.e-dani.com", "skirmshop", "skirmbooks-ui", 80),
    }
    for name, (host, namespace, service, port) in expected.items():
        route = ingress(path, name)
        [rule] = route["spec"]["routes"]
        assert f"Host(`{host}`)" in rule["match"]
        assert all(cidr in rule["match"] for cidr in TRUSTED)
        assert "middlewares" not in rule
        assert rule["services"] == [{"name": service, "namespace": namespace, "port": port}]
        assert route["spec"]["tls"] == {"secretName": "wildcard-edani-tls"}


def test_jarvis_preserves_hud_rewrite_and_trusted_catchall():
    route = ingress("networking/traefik-lan/public-panels-lan.yaml", "lan-jarvis-public-host")
    hud, catchall = route["spec"]["routes"]
    assert hud["priority"] == 400 and catchall["priority"] == 300
    assert hud["middlewares"] == [{"name": "jarvis-public-hud-shell", "namespace": "jarvis"}]
    assert "middlewares" not in catchall
    assert all(all(cidr in rule["match"] for cidr in TRUSTED) for rule in (hud, catchall))


def test_openchamber_accepts_public_split_host_without_removing_fallback():
    route = ingress("networking/traefik-lan/public-panels-lan.yaml", "lan-openchamber-public-host")
    trusted, fallback = route["spec"]["routes"]
    assert "Host(`chamber.e-dani.com`)" in trusted["match"]
    assert all(cidr in trusted["match"] for cidr in TRUSTED)
    assert "middlewares" not in trusted
    assert fallback["middlewares"] == [{"name": "sso-chain", "namespace": "keycloak"}]
    assert route["spec"]["tls"] == {"secretName": "wildcard-edani-tls"}
