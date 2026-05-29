#!/usr/bin/env python3
"""OVH dedicated-server helper for the KS-5 HA rollout.

The destructive operation in this file is reinstalling a server. It is gated by
CONFIRM_OVH_REINSTALL=install-ubuntu-24.04 and never prints credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


CONFIRM_REINSTALL = "install-ubuntu-24.04"
DEFAULT_HOSTNAMES = ["ks5-cp-1", "ks5-cp-2", "ks5-cp-3"]
DEFAULT_KS5A_REQUIRES = [
    "KS-5-A",
    "Intel Xeon E-2274G",
    "SSD NVMe",
    "Soft RAID",
]
DEFAULT_KS5A_REJECTS = ["HDD", "SATA"]


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def client() -> Any:
    try:
        import ovh
    except ImportError as exc:  # pragma: no cover - actionable CLI error
        raise SystemExit("Missing dependency: pip install -r requirements.txt") from exc

    endpoint = os.environ.get("OVH_ENDPOINT", "ovh-eu")
    return ovh.Client(
        endpoint=endpoint,
        application_key=require_env("OVH_APPLICATION_KEY"),
        application_secret=require_env("OVH_APPLICATION_SECRET"),
        consumer_key=require_env("OVH_CONSUMER_KEY"),
    )


def api_get(path: str) -> Any:
    return client().get(path)


def api_post(path: str, **payload: Any) -> Any:
    return client().post(path, **payload)


def list_servers() -> list[str]:
    return sorted(api_get("/dedicated/server"))


def stringify(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def server_info(service_name: str) -> dict[str, Any]:
    return api_get(f"/dedicated/server/{service_name}")


def compatible_templates(service_name: str) -> dict[str, Any]:
    return api_get(f"/dedicated/server/{service_name}/install/compatibleTemplates")


def flatten_templates(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        values: list[str] = []
        for item in payload.values():
            values.extend(flatten_templates(item))
        return values
    if isinstance(payload, list):
        values = []
        for item in payload:
            values.extend(flatten_templates(item))
        return values
    if isinstance(payload, str):
        return [payload]
    return []


def choose_ubuntu_2404_template(service_name: str, explicit: str | None) -> str:
    if explicit:
        return explicit

    candidates = sorted(set(flatten_templates(compatible_templates(service_name))))
    matches = [
        item
        for item in candidates
        if "ubuntu" in item.lower()
        and ("24.04" in item.lower() or "2404" in item.lower())
        and "desktop" not in item.lower()
    ]
    server_matches = [item for item in matches if "server" in item.lower()]
    if server_matches:
        return server_matches[0]
    if matches:
        return matches[0]
    raise SystemExit(
        f"No Ubuntu 24.04 template found for {service_name}. "
        "Run `ovh_install.py templates --service-name ...` and pass --template explicitly."
    )


def raid1_storage_payload() -> list[dict[str, Any]]:
    return [
        {
            "partitioning": {
                "disks": 2,
                "layout": [
                    {
                        "fileSystem": "ext4",
                        "mountPoint": "/boot",
                        "size": 1024,
                        "raidLevel": 1,
                    },
                    {
                        "fileSystem": "ext4",
                        "mountPoint": "/",
                        "size": 0,
                        "raidLevel": 1,
                    },
                ],
            }
        }
    ]


def reinstall_payload(
    *,
    service_name: str,
    hostname: str,
    template: str | None,
    ssh_public_key: str,
    raid1: bool,
) -> dict[str, Any]:
    selected_template = choose_ubuntu_2404_template(service_name, template)
    payload: dict[str, Any] = {
        "operatingSystem": selected_template,
        "customizations": {
            "hostname": hostname,
            "sshKey": ssh_public_key,
        },
    }
    if raid1:
        payload["storage"] = raid1_storage_payload()
    return payload


def install(args: argparse.Namespace) -> None:
    if os.environ.get("CONFIRM_OVH_REINSTALL") != CONFIRM_REINSTALL:
        raise SystemExit(
            "Refusing to reinstall: set CONFIRM_OVH_REINSTALL=install-ubuntu-24.04. "
            "This operation erases the target server disks."
        )

    ssh_public_key = args.ssh_public_key or require_env("SSH_PUBLIC_KEY")
    hostnames = args.hostnames or DEFAULT_HOSTNAMES
    if len(args.service_names) != len(hostnames):
        raise SystemExit("Number of --service-name values must match --hostname values.")

    tasks = []
    for service_name, hostname in zip(args.service_names, hostnames, strict=True):
        payload = reinstall_payload(
            service_name=service_name,
            hostname=hostname,
            template=args.template,
            ssh_public_key=ssh_public_key,
            raid1=not args.no_raid1,
        )
        safe_payload = json.loads(json.dumps(payload))
        safe_payload["customizations"]["sshKey"] = "<redacted>"
        eprint(f"Reinstalling {service_name} as {hostname}: {json.dumps(safe_payload, sort_keys=True)}")
        try:
            task = api_post(f"/dedicated/server/{service_name}/reinstall", **payload)
        except Exception:
            if args.no_raid1 or not args.fallback_no_raid:
                raise
            eprint(f"RAID1 install rejected for {service_name}; retrying without storage customization.")
            payload.pop("storage", None)
            task = api_post(f"/dedicated/server/{service_name}/reinstall", **payload)
        tasks.append({"service_name": service_name, "hostname": hostname, "task": task})
    print(json.dumps(tasks, indent=2, sort_keys=True))


def wait(args: argparse.Namespace) -> None:
    try:
        from ovh.exceptions import ResourceNotFoundError
    except ImportError:  # pragma: no cover - ovh always present at runtime
        ResourceNotFoundError = ()  # type: ignore[assignment]

    deadline = time.monotonic() + args.timeout_seconds
    pending = set(args.service_names)
    while pending:
        for service_name in sorted(pending):
            try:
                status = api_get(f"/dedicated/server/{service_name}/install/status")
            except ResourceNotFoundError:
                # OVH stops exposing /install/status once the reinstall task
                # finishes ("Server is not being installed..."). Treat the 404
                # as completion; downstream SSH checks confirm the host is up.
                print(json.dumps({"service_name": service_name, "status": "done (install/status no longer present)"}, sort_keys=True))
                pending.discard(service_name)
                continue
            print(json.dumps({"service_name": service_name, "status": status}, sort_keys=True))
            state = str(status.get("status") or status.get("state") or "").lower()
            if state in {"done", "finished", "installed", "ok"}:
                pending.discard(service_name)
            if state in {"error", "failed"}:
                raise SystemExit(f"Install failed for {service_name}: {status}")
        if pending:
            if time.monotonic() > deadline:
                raise SystemExit(f"Timed out waiting for: {', '.join(sorted(pending))}")
            time.sleep(args.interval_seconds)


def inventory(args: argparse.Namespace) -> None:
    rows = []
    for service_name, hostname in zip(args.service_names, args.hostnames or DEFAULT_HOSTNAMES, strict=True):
        info = server_info(service_name)
        rows.append(
            {
                "hostname": hostname,
                "service_name": service_name,
                "ansible_host": info.get("ip"),
                "public_ip": info.get("ip"),
                "datacenter": info.get("datacenter"),
                "region": info.get("region"),
            }
        )
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["[ks5_control_plane]"]
    for row in rows:
        lines.append(
            "{hostname} ansible_host={ansible_host} ovh_service_name={service_name} public_ip={public_ip} ovh_datacenter={datacenter}".format(
                **row
            )
        )
    lines.extend(["", "[ks5_control_plane:vars]", "ansible_user=ubuntu"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"written": str(path), "hosts": rows}, indent=2, sort_keys=True))


def discover(args: argparse.Namespace) -> None:
    servers = []
    for service_name in list_servers():
        info = server_info(service_name)
        servers.append(
            {
                "service_name": service_name,
                "name": info.get("name"),
                "ip": info.get("ip"),
                "datacenter": info.get("datacenter"),
                "commercial_range": info.get("commercialRange") or info.get("commercial_range"),
                "state": info.get("state"),
            }
        )
    print(json.dumps(servers, indent=2, sort_keys=True))


def templates(args: argparse.Namespace) -> None:
    payload = compatible_templates(args.service_name)
    print(json.dumps(payload, indent=2, sort_keys=True))


def find_matches(value: Any, requires: list[str], rejects: list[str]) -> list[Any]:
    matches: list[Any] = []
    text = stringify(value).lower()
    if all(item.lower() in text for item in requires) and not any(item.lower() in text for item in rejects):
        matches.append(value)
    if isinstance(value, dict):
        for item in value.values():
            matches.extend(find_matches(item, requires, rejects))
    elif isinstance(value, list):
        for item in value:
            matches.extend(find_matches(item, requires, rejects))
    return matches


def iter_objects(value: Any) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    if isinstance(value, dict):
        objects.append(value)
        for item in value.values():
            objects.extend(iter_objects(item))
    elif isinstance(value, list):
        for item in value:
            objects.extend(iter_objects(item))
    return objects


def is_nvme_soft_raid_option(option: dict[str, Any], rejects: list[str]) -> bool:
    text = stringify(option).lower()
    compact = text.replace("-", "").replace("_", "").replace(" ", "")
    if any(item.lower() in text for item in rejects):
        return False
    return option.get("family") == "storage" and "nvme" in compact and "softraid" in compact


def monthly_price(option: dict[str, Any]) -> str | None:
    for price in option.get("prices") or []:
        if (
            "renew" in (price.get("capacities") or [])
            and price.get("duration") == "P1M"
            and price.get("pricingMode") == "default"
        ):
            return (price.get("price") or {}).get("text")
    return None


def catalog(args: argparse.Namespace) -> None:
    """Create a temporary cart and search its eco catalog for KS-5-A NVMe."""

    requires = [args.offer_name] + (args.require or [item for item in DEFAULT_KS5A_REQUIRES if item != args.offer_name])
    rejects = args.reject or DEFAULT_KS5A_REJECTS
    storage_requires = [
        item
        for item in requires
        if any(token in item.lower() for token in ("nvme", "soft raid", "ssd"))
    ]
    offer_requires = [item for item in requires if item not in storage_requires]
    subsidiary = args.ovh_subsidiary or os.environ.get("OVH_SUBSIDIARY", "ES")
    cart = api_post("/order/cart", ovhSubsidiary=subsidiary)
    cart_id = cart["cartId"] if isinstance(cart, dict) else cart
    payloads = []
    for path in (
        f"/order/cart/{cart_id}/eco",
        f"/order/cart/{cart_id}/dedicated/server",
        f"/order/cart/{cart_id}/dedicated",
    ):
        try:
            payloads.append({"path": path, "payload": api_get(path)})
        except Exception as exc:  # endpoint availability varies by subsidiary/catalog
            payloads.append({"path": path, "error": str(exc)})

    offer_matches = []
    for payload in payloads:
        for obj in iter_objects(payload.get("payload")):
            text = stringify(obj).lower()
            if all(item.lower() in text for item in offer_requires):
                offer_matches.append(obj)

    plan_codes = sorted({item.get("planCode") for item in offer_matches if item.get("planCode")})
    option_payloads = []
    storage_matches = []
    for plan_code in plan_codes:
        try:
            options = api_get(f"/order/cart/{cart_id}/eco/options?planCode={plan_code}")
            option_payloads.append({"plan_code": plan_code, "options_count": len(options)})
            storage_matches.extend([option for option in options if is_nvme_soft_raid_option(option, rejects)])
        except Exception as exc:
            option_payloads.append({"plan_code": plan_code, "error": str(exc)})

    missing = []
    for item in offer_requires:
        if not any(item.lower() in stringify(match).lower() for match in offer_matches):
            missing.append(item)
    if storage_requires and not storage_matches:
        missing.extend(storage_requires)

    result = {
        "ovh_subsidiary": subsidiary,
        "requires": requires,
        "rejects": rejects,
        "missing_global_terms": missing,
        "offer_matches": [
            {
                "planCode": item.get("planCode"),
                "productName": item.get("productName"),
                "productType": item.get("productType"),
                "monthly": monthly_price(item),
            }
            for item in offer_matches
        ],
        "acceptable_storage_matches": [
            {
                "family": item.get("family"),
                "planCode": item.get("planCode"),
                "mandatory": item.get("mandatory"),
                "exclusive": item.get("exclusive"),
                "monthly": monthly_price(item),
            }
            for item in storage_matches
        ],
        "option_payloads": option_payloads,
        "searched_paths": [
            {"path": item["path"], "has_error": "error" in item, "error": item.get("error")}
            for item in payloads
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if missing:
        raise SystemExit(f"Catalog is missing required KS-5-A terms/options: {', '.join(missing)}")
    if not storage_matches:
        raise SystemExit(
            "No acceptable selected storage option found. Refusing to continue unless the catalog contains "
            "an SSD NVMe Soft RAID storage object that is not HDD/SATA."
        )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="OVH KS-5 Ubuntu 24.04 installer helper")
    sub = root.add_subparsers(required=True)

    p = sub.add_parser("discover", help="List dedicated servers visible to the OVH API key")
    p.set_defaults(func=discover)

    p = sub.add_parser("templates", help="List install templates compatible with one server")
    p.add_argument("--service-name", required=True)
    p.set_defaults(func=templates)

    p = sub.add_parser("catalog", help="Find KS-5-A SSD NVMe Soft RAID offers in the OVH cart catalog")
    p.add_argument("--ovh-subsidiary")
    p.add_argument("--offer-name", default="KS-5-A")
    p.add_argument("--require", action="append")
    p.add_argument("--reject", action="append")
    p.set_defaults(func=catalog)

    p = sub.add_parser("install-ubuntu", help="Install Ubuntu Server 24.04 LTS on delivered servers")
    p.add_argument("--service-name", dest="service_names", action="append", required=True)
    p.add_argument("--hostname", dest="hostnames", action="append")
    p.add_argument("--template", help="Explicit OVH Ubuntu 24.04 template name")
    p.add_argument("--ssh-public-key")
    p.add_argument("--no-raid1", action="store_true", help="Do not request software RAID1 partitioning")
    p.add_argument("--fallback-no-raid", action="store_true", help="Retry without storage customization if RAID1 is rejected")
    p.set_defaults(func=install)

    p = sub.add_parser("wait", help="Wait until OVH reports installation complete")
    p.add_argument("--service-name", dest="service_names", action="append", required=True)
    p.add_argument("--timeout-seconds", type=int, default=7200)
    p.add_argument("--interval-seconds", type=int, default=60)
    p.set_defaults(func=wait)

    p = sub.add_parser("inventory", help="Generate an Ansible inventory from delivered servers")
    p.add_argument("--service-name", dest="service_names", action="append", required=True)
    p.add_argument("--hostname", dest="hostnames", action="append")
    p.add_argument("--output", default="ansible/inventory/generated/ks5.ini")
    p.set_defaults(func=inventory)
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
