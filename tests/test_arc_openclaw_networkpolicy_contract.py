from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "networking" / "arc-runners" / "networkpolicy.yaml"


def _policy():
    documents = [doc for doc in yaml.safe_load_all(POLICY_PATH.read_text()) if doc]
    return next(
        doc
        for doc in documents
        if doc.get("kind") == "NetworkPolicy"
        and doc.get("metadata", {}).get("name") == "arc-openclaw-service-egress"
    )


def test_arc_openclaw_api_access_is_limited_to_control_plane_endpoints():
    policy = _policy()
    assert policy["spec"]["podSelector"]["matchLabels"] == {
        "actions.github.com/scale-set-name": "arc-openclaw"
    }

    api_rule = next(
        rule
        for rule in policy["spec"]["egress"]
        if {port["port"] for port in rule.get("ports", [])} == {6443}
    )
    assert {target["ipBlock"]["cidr"] for target in api_rule["to"]} == {
        "100.107.21.89/32",
        "100.71.117.127/32",
        "100.75.189.75/32",
    }


def test_arc_openclaw_policy_never_allows_the_whole_tailnet():
    cidrs = {
        target["ipBlock"]["cidr"]
        for rule in _policy()["spec"]["egress"]
        for target in rule.get("to", [])
        if "ipBlock" in target
    }
    assert "100.64.0.0/10" not in cidrs
