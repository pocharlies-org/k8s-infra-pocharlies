#!/usr/bin/env python3
"""Compare platform/keycloak-next/PRINCIPALS.md with the live edani realm (INFRA-219 C4).

Read-only. Every live principal (users plus the service-account-* users that
the default listing hides) must have exactly one entry with a named owner;
every entry must match a live principal; the realm roles an entry declares
must be exactly the roles ROLES.yaml grants it; a proposed retirement needs
its reason. It reads users only (no clients, no role mappings), so the
auditor client of the drift CronJob can run it without view-clients.

  OK: <N> principals, 0 sin dueño      exit 0
  DRIFT: <one line per finding>        exit 1
  ERROR: <auth, network or file>       exit 2

Authentication: see kc_rbac.Client.from_env (local netrc flow, or in-cluster
KC_CLIENT_ID_FILE/KC_CLIENT_SECRET_FILE + KEYCLOAK_URL).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kc_rbac  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PRINCIPALS = os.path.join(BASE, "PRINCIPALS.md")
DEFAULT_CATALOG = os.path.join(BASE, "ROLES.yaml")

TYPES = ("sa", "humano")
STATUSES = ("activo", "retirada-propuesta")
SA_PREFIX = "service-account-"


def load_principals(path):
    """The json block of PRINCIPALS.md as {username: entry}; shape errors raise CatalogError.

    Ownership, retirement reasons and roles are findings, not shape errors:
    they are reported by find_drift so that one run names all of them.
    """
    document = kc_rbac.load_json_block(path)
    principals = document.get("principals") if isinstance(document, dict) else None
    if not isinstance(principals, list) or not principals:
        raise kc_rbac.CatalogError(f"{path}: falta la lista principals")
    entries = {}
    for index, entry in enumerate(principals):
        where = f"{path}: principals[{index}]"
        if not isinstance(entry, dict):
            raise kc_rbac.CatalogError(f"{where} no es un objeto")
        username = entry.get("username")
        if not isinstance(username, str) or not username:
            raise kc_rbac.CatalogError(f"{where}: username vacío")
        if username in entries:
            raise kc_rbac.CatalogError(f"{where}: {username} duplicado")
        if entry.get("type") not in TYPES:
            raise kc_rbac.CatalogError(f"{where}: type de {username} debe ser sa o humano")
        if entry.get("status") not in STATUSES:
            raise kc_rbac.CatalogError(f"{where}: status de {username} debe ser activo o retirada-propuesta")
        client = entry.get("client")
        if entry["type"] == "sa":
            if not isinstance(client, str) or username != f"{SA_PREFIX}{client}":
                raise kc_rbac.CatalogError(f"{where}: {username} es sa y client debe ser su client ({SA_PREFIX}<client>)")
        elif client is not None:
            raise kc_rbac.CatalogError(f"{where}: {username} es humano y client debe ser null")
        roles = entry.get("realm_roles")
        if not isinstance(roles, list) or not all(isinstance(r, str) and r for r in roles):
            raise kc_rbac.CatalogError(f"{where}: realm_roles de {username} debe ser una lista de roles")
        entries[username] = entry
    return entries


def _blank(value):
    return not isinstance(value, str) or not value.strip()


def live_principals(client):
    """Usernames of every realm user; service accounts need their own query."""
    return {user["username"] for user in client.users() + client.service_account_users()}


def find_drift(entries, catalog, live):
    """Return the drift lines, sorted per kind so the output is stable."""
    drift = []
    for username in sorted(live - set(entries)):
        drift.append(f"DRIFT: principal {username} existe en el realm y no tiene entrada en PRINCIPALS.md")
    for username in sorted(set(entries) - live):
        drift.append(f"DRIFT: entrada {username} de PRINCIPALS.md no existe en el realm")
    for username in sorted(entries):
        entry = entries[username]
        if _blank(entry.get("owner")):
            drift.append(f"DRIFT: entrada {username} sin dueño")
        if entry["status"] == "retirada-propuesta" and _blank(entry.get("retirement_reason")):
            drift.append(f"DRIFT: entrada {username} en retirada-propuesta sin motivo")
        declared = set(entry["realm_roles"])
        granted = {name for name, role in catalog.items() if username in role["grantees"]}
        for name in sorted(declared - set(catalog)):
            drift.append(f"DRIFT: entrada {username} declara {name}, que no está en ROLES.yaml")
        for name in sorted((declared & set(catalog)) - granted):
            drift.append(f"DRIFT: entrada {username} declara {name} y ROLES.yaml no se lo concede")
        for name in sorted(granted - declared):
            drift.append(f"DRIFT: entrada {username} no declara {name}, que ROLES.yaml le concede")
    return drift


def main(argv=None, env=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--principals", default=DEFAULT_PRINCIPALS, help="ruta del inventario (por defecto PRINCIPALS.md del repo)")
    parser.add_argument("--catalog", default=DEFAULT_CATALOG, help="ruta del catálogo de roles (por defecto ROLES.yaml del repo)")
    args = parser.parse_args(argv)
    try:
        entries = load_principals(args.principals)
        catalog = kc_rbac.load_role_catalog(args.catalog)
        live = live_principals(kc_rbac.Client.from_env(env))
    except (kc_rbac.KcError, kc_rbac.CatalogError) as exc:
        print(f"ERROR: {exc}")
        return 2
    drift = find_drift(entries, catalog, live)
    if drift:
        print("\n".join(drift))
        return 1
    print(f"OK: {len(live)} principals, 0 sin dueño")
    return 0


if __name__ == "__main__":
    sys.exit(main())
