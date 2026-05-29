#!/usr/bin/env python3
"""Back up and safely restore Cloudflare DNS records for the KS-5 rollout."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests


API = "https://api.cloudflare.com/client/v4"
CONFIRM_RESTORE = "restore-dns-from-backup"


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def session() -> requests.Session:
    token = require_env("CLOUDFLARE_API_TOKEN")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s


def zone_id() -> str:
    return require_env("CLOUDFLARE_ZONE_ID")


def cf_request(method: str, path: str, **kwargs: Any) -> Any:
    response = session().request(method, f"{API}{path}", timeout=30, **kwargs)
    try:
        payload = response.json()
    except ValueError:
        payload = {"success": response.ok, "raw": response.text}
    if not response.ok or payload.get("success") is False:
        raise SystemExit(json.dumps({"status_code": response.status_code, "payload": payload}, indent=2))
    return payload


def list_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = cf_request("GET", f"/zones/{zone_id()}/dns_records", params={"page": page, "per_page": 100})
        records.extend(payload["result"])
        info = payload.get("result_info", {})
        if page >= int(info.get("total_pages", page)):
            return records
        page += 1


def write(path: str, content: str) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(json.dumps({"written": str(output)}, sort_keys=True))


def backup_json(args: argparse.Namespace) -> None:
    write(args.output, json.dumps({"records": list_records()}, indent=2, sort_keys=True) + "\n")


def backup_bind(args: argparse.Namespace) -> None:
    response = session().get(f"{API}/zones/{zone_id()}/dns_records/export", timeout=30)
    if not response.ok:
        raise SystemExit(f"Cloudflare export failed: HTTP {response.status_code}")
    write(args.output, response.text)


def restore_json(args: argparse.Namespace) -> None:
    if os.environ.get("CONFIRM_CLOUDFLARE_RESTORE") != CONFIRM_RESTORE:
        raise SystemExit(f"Refusing restore: set CONFIRM_CLOUDFLARE_RESTORE={CONFIRM_RESTORE}")
    backup = json.loads(Path(args.input).read_text(encoding="utf-8"))
    source_records = backup.get("records", [])
    suffix = args.name_suffix
    restored = []
    existing = {(r["type"], r["name"], r.get("content")): r for r in list_records()}
    for record in source_records:
        if suffix and not str(record.get("name", "")).endswith(suffix):
            continue
        if record["type"] not in set(args.types):
            continue
        key = (record["type"], record["name"], record.get("content"))
        body = {
            key: value
            for key, value in record.items()
            if key
            in {
                "type",
                "name",
                "content",
                "ttl",
                "proxied",
                "priority",
                "comment",
                "tags",
                "settings",
            }
        }
        if key in existing:
            cf_request("PUT", f"/zones/{zone_id()}/dns_records/{existing[key]['id']}", json=body)
            action = "updated"
        else:
            cf_request("POST", f"/zones/{zone_id()}/dns_records", json=body)
            action = "created"
        restored.append({"action": action, "type": record["type"], "name": record["name"], "content": record.get("content")})
    print(json.dumps({"restored": restored}, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Cloudflare DNS backup/restore helper")
    sub = root.add_subparsers(required=True)

    p = sub.add_parser("backup-json")
    p.add_argument("--output", required=True)
    p.set_defaults(func=backup_json)

    p = sub.add_parser("backup-bind")
    p.add_argument("--output", required=True)
    p.set_defaults(func=backup_bind)

    p = sub.add_parser("restore-json")
    p.add_argument("--input", required=True)
    p.add_argument("--name-suffix", default="")
    p.add_argument("--types", nargs="+", default=["A", "AAAA", "CNAME", "TXT", "MX"])
    p.set_defaults(func=restore_json)
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except requests.RequestException as exc:
        print(f"Cloudflare API error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
