#!/usr/bin/env python3
"""Enforce the registry contract of ROLES.yaml between the trunk and a branch (INFRA-219 C2).

An entry is never deleted and a role never comes back from the dead: every
role name in the trunk catalog must still be in the branch catalog, and a
role `deprecated` in the trunk must not be `active` in the branch. New roles
and active -> deprecated are allowed.

  OK: <N> roles del tronco presentes, 0 borrados, 0 deprecated reactivados   exit 0
  SKIP: el tronco no tiene <path> ...                                        exit 0
  CONTRATO: <one line per violation>                                         exit 1
  ERROR: <unreadable catalog>                                                exit 2

The trunk catalog is read with a minimal reader (names and status only), so a
later, stricter shape of the branch loader never rejects an older trunk file.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kc_rbac  # noqa: E402

DEFAULT_CATALOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ROLES.yaml")


def load_base_statuses(path):
    """{name: status} of the trunk catalog."""
    try:
        with open(path, encoding="utf-8") as handle:
            document = json.load(handle)
    except OSError as exc:
        raise kc_rbac.CatalogError(f"no se puede leer {path}: {exc.strerror}") from None
    except ValueError as exc:
        raise kc_rbac.CatalogError(f"{path} no es JSON válido: {exc}") from None
    roles = document.get("roles") if isinstance(document, dict) else None
    if not isinstance(roles, list):
        raise kc_rbac.CatalogError(f"{path}: falta la lista roles")
    statuses = {}
    for index, entry in enumerate(roles):
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise kc_rbac.CatalogError(f"{path}: roles[{index}] sin name")
        statuses[entry["name"]] = entry.get("status")
    return statuses


def find_violations(base, head):
    """base: {name: status} of the trunk; head: {name: entry} of the branch."""
    violations = []
    for name in sorted(set(base) - set(head)):
        violations.append(f"CONTRATO: rol {name} está en el catálogo del tronco y la rama lo borra (se depreca, no se borra)")
    for name in sorted(set(base) & set(head)):
        if base[name] == "deprecated" and head[name]["status"] == "active":
            violations.append(f"CONTRATO: rol {name} es deprecated en el tronco y la rama lo vuelve a active")
    return violations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="ROLES.yaml del tronco (si no existe, se salta)")
    parser.add_argument("--head", default=DEFAULT_CATALOG, help="ROLES.yaml de la rama (por defecto el del repo)")
    args = parser.parse_args(argv)
    if not os.path.exists(args.base):
        print(f"SKIP: el tronco no tiene {args.base}; no hay catálogo previo contra el que comprobar borrados")
        return 0
    try:
        base = load_base_statuses(args.base)
        head = kc_rbac.load_role_catalog(args.head)
    except kc_rbac.CatalogError as exc:
        print(f"ERROR: {exc}")
        return 2
    violations = find_violations(base, head)
    if violations:
        print("\n".join(violations))
        return 1
    print(f"OK: {len(base)} roles del tronco presentes, 0 borrados, 0 deprecated reactivados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
