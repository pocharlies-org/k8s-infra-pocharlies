#!/usr/bin/env python3
"""SRE post-render patches for the live MetalLB Helm release."""

import sys

import yaml


def main() -> int:
    docs = list(yaml.safe_load_all(sys.stdin))
    patched = []

    for doc in docs:
        if not isinstance(doc, dict):
            patched.append(doc)
            continue

        if doc.get("kind") == "DaemonSet" and doc.get("metadata", {}).get("name") == "metallb-speaker":
            pod_spec = doc.setdefault("spec", {}).setdefault("template", {}).setdefault("spec", {})
            pod_spec["dnsPolicy"] = "ClusterFirstWithHostNet"

        patched.append(doc)

    yaml.safe_dump_all(patched, sys.stdout, sort_keys=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
