#!/usr/bin/env python3
"""Compare platform/keycloak-next/ROLES.yaml with the live edani realm (INFRA-219 C1).

Read-only. Checks, per catalogued role: the realm role exists (a deprecated
role may be present or gone), nobody holds it directly outside `grantees`,
every declared grantee still holds it, no group carries it (R2), and the
realm roles it contains are exactly its `composites` (absent = none), so a
role slipped into default-roles-edani is caught even though it reaches users
only through the composite; the client roles it contains are exactly its
`client_composites` ({clientId: roles}, absent = none), so a client role such
as realm-management view-users slipped into the composite is caught too. Any
live realm role missing from the catalog is drift too.

  OK: <N> roles en catálogo, 0 sin catalogar, 0 catalogados inexistentes   exit 0
  DRIFT: <one line per finding>                                            exit 1
  ERROR: <auth, network or catalog failure>                                exit 2

Authentication: see kc_rbac.Client.from_env (local netrc flow, or in-cluster
KC_CLIENT_ID_FILE/KC_CLIENT_SECRET_FILE + KEYCLOAK_URL).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kc_rbac  # noqa: E402

DEFAULT_CATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ROLES.yaml")


def find_drift(catalog, client):
    """Return (drift lines, uncatalogued count, missing count)."""
    drift = []
    live = {role["name"] for role in client.realm_roles()}
    uncatalogued = sorted(live - set(catalog))
    for name in uncatalogued:
        drift.append(f"DRIFT: rol {name} existe en el realm y no está en el catálogo")
    missing = sorted(name for name, entry in catalog.items() if name not in live and entry["status"] == "active")
    for name in missing:
        drift.append(f"DRIFT: rol {name} catalogado (active) no existe en el realm")
    for name in sorted(set(catalog) & live):
        declared = set(catalog[name]["grantees"])
        holders = {user["username"] for user in client.users_with_role(name)}
        for username in sorted(holders - declared):
            drift.append(f"DRIFT: {username} tiene {name} no declarada")
        for username in sorted(declared - holders):
            drift.append(f"DRIFT: {username} declarado en {name} no la tiene concedida")
        for group in client.groups_with_role(name):
            drift.append(f"DRIFT: grupo {group.get('path') or group.get('name')} tiene {name} (R2: sin role-mapping por grupo)")
        declared_composites = set(catalog[name].get("composites", []))
        live_composites = set(client.realm_composites(name))
        for composite in sorted(live_composites - declared_composites):
            drift.append(f"DRIFT: {name} contiene {composite} y el catálogo no lo declara en composites")
        for composite in sorted(declared_composites - live_composites):
            drift.append(f"DRIFT: {name} declara {composite} en composites y el realm no lo contiene")
        declared_client = {
            (client_id, role) for client_id, roles in catalog[name].get("client_composites", {}).items() for role in roles
        }
        live_client = {(client_id, role) for client_id, roles in client.client_composites(name).items() for role in roles}
        for client_id, role in sorted(live_client - declared_client):
            drift.append(f"DRIFT: {name} contiene el rol de cliente {client_id}/{role} y el catálogo no lo declara en client_composites")
        for client_id, role in sorted(declared_client - live_client):
            drift.append(f"DRIFT: {name} declara {client_id}/{role} en client_composites y el realm no lo contiene")
    return drift, len(uncatalogued), len(missing)


def main(argv=None, env=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", default=DEFAULT_CATALOG, help="ruta del catálogo (por defecto ROLES.yaml del repo)")
    args = parser.parse_args(argv)
    try:
        catalog = kc_rbac.load_role_catalog(args.catalog)
        client = kc_rbac.Client.from_env(env)
        drift, _, _ = find_drift(catalog, client)
    except (kc_rbac.KcError, kc_rbac.CatalogError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if drift:
        print("\n".join(drift))
        return 1
    print(f"OK: {len(catalog)} roles en catálogo, 0 sin catalogar, 0 catalogados inexistentes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
