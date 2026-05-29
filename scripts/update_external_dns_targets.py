#!/usr/bin/env python3
"""Rewrite external-dns public targets after KS-5 public IPs are known."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import yaml


CONFIRM = "update-ha-targets"


def load_documents(path: Path) -> list[Any]:
    with path.open("r", encoding="utf-8") as fh:
        return list(yaml.safe_load_all(fh))


def dump_documents(path: Path, docs: list[Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump_all(docs, fh, sort_keys=False, explicit_start=True)


def public_target(value: str) -> bool:
    if not value:
        return False
    if value.startswith("192.168.") or value.startswith("10.") or value.startswith("100."):
        return False
    if value.endswith(".e-dani.com") or value.endswith(".skirmshop.es"):
        return True
    return True


def update_doc(doc: Any, targets: str, include_dns_only: bool) -> bool:
    if not isinstance(doc, dict):
        return False
    metadata = doc.get("metadata")
    if not isinstance(metadata, dict):
        return False
    annotations = metadata.get("annotations")
    if not isinstance(annotations, dict):
        return False
    current = annotations.get("external-dns.alpha.kubernetes.io/target")
    if not public_target(str(current or "")):
        return False
    proxied = str(annotations.get("external-dns.alpha.kubernetes.io/cloudflare-proxied", "")).lower()
    if proxied != "true" and not include_dns_only:
        return False
    annotations["external-dns.alpha.kubernetes.io/target"] = targets
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Update external-dns target annotations for HA public IPs")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--targets", required=True, help="Comma-separated public IPs")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--include-dns-only", action="store_true")
    args = parser.parse_args()

    targets = ",".join(part.strip() for part in args.targets.split(",") if part.strip())
    if len(targets.split(",")) < 4:
        raise SystemExit("Expected four public targets: KS5_1,KS5_2,KS5_3,SAUVAGE")
    if args.write and os.environ.get("CONFIRM_DNS_TARGET_REWRITE") != CONFIRM:
        raise SystemExit(f"Refusing write: set CONFIRM_DNS_TARGET_REWRITE={CONFIRM}")

    changed: list[str] = []
    for path in sorted(Path(args.repo_root).glob("**/*.y*ml")):
        if ".git" in path.parts:
            continue
        docs = load_documents(path)
        if any(update_doc(doc, targets, args.include_dns_only) for doc in docs):
            changed.append(str(path))
            if args.write:
                dump_documents(path, docs)

    print(json.dumps({"write": args.write, "targets": targets, "changed_files": changed}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
