#!/usr/bin/env python3
"""Compare ROUTE-ROLES.md with the live AgentGateway config and the edani realm (INFRA-219 C3).

Read-only. The matrix is the single json block of ROUTE-ROLES.md. Checks:

* every route of the config is in the matrix with the same path, the same
  route-level roles (`require` / authorization rules without a tool) and, per
  role, the same set of gated tools (mcpAuthorization rules naming a tool);
  no matrix route is missing from the config;
* every role the config references exists in the realm;
* every live gateway role (realm role `agentgateway-*`, or any role the config
  references) is gated by a route or documented in `unrouted`, and no
  `unrouted` role is gated by the config or gone from the realm.

  OK: <N> gates coherentes, 0 roles referenciados inexistentes, 0 roles sin ruta documentada   exit 0
  DRIFT: <one line per finding>                                                              exit 1
  ERROR: <kubectl, auth, network, parse or matrix failure>                                   exit 2

A gate is one (route, role) pair. The config comes from
`kubectl -n agentgateway get cm agentgateway-config -o json` (key config.yaml)
unless --config-file names a copy of config.yaml. Realm authentication: see
kc_rbac.Client.from_env.
"""

import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import kc_rbac  # noqa: E402

DEFAULT_MATRIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ROUTE-ROLES.md")
CONFIG_NAMESPACE = "agentgateway"
CONFIG_MAP = "agentgateway-config"
CONFIG_KEY = "config.yaml"
GATEWAY_ROLE_PREFIX = "agentgateway-"
UNROUTED_DISPOSITIONS = ("reservado", "aplicacion", "retirada-propuesta")

_ROUTE = re.compile(r"^(\s*)- name: (\S+)\s*$")
_PATH = re.compile(r"pathPrefix:\s*([^\s}]+)")
# Every CEL rule of the config is a single-quoted scalar on one line, either a
# list item or the value of `require:`.
_RULE = re.compile(r"^\s*- (?:require: )?'(.*)'\s*$")
_ROLE_REF = re.compile(r'"([^"]+)" in jwt\.realm_access\.roles')
_TOOL_EQ = re.compile(r'mcp\.tool\.name == "([^"]+)"')
_TOOL_IN = re.compile(r"mcp\.tool\.name in \[([^\]]*)\]")


def _is_comment(line):
    return line.lstrip().startswith("#")


def _next_code_line(lines, index):
    for line in lines[index + 1:]:
        if line.strip() and not _is_comment(line):
            return line
    return ""


def parse_config(text):
    """{route name: {"path", "require": set, "tools": {role: set}}} of an AgentGateway config.

    Raises kc_rbac.CatalogError when a role reference escapes the rule shapes
    this parser reads, so a new CEL form fails loud instead of hiding a gate.
    """
    lines = text.splitlines()
    routes, current = {}, None
    for index, line in enumerate(lines):
        match = _ROUTE.match(line)
        if match and _next_code_line(lines, index).strip().startswith("matches:"):
            name = match.group(2)
            if name in routes:
                raise kc_rbac.CatalogError(f"config: ruta {name} duplicada")
            current = {"indent": len(match.group(1)), "lines": []}
            routes[name] = current
            continue
        if current is None or not line.strip() or _is_comment(line):
            continue
        indent = len(line) - len(line.lstrip())
        if indent < current["indent"] or (indent == current["indent"] and line.lstrip().startswith("- ")):
            current = None
            continue
        current["lines"].append(line)

    parsed, references = {}, 0
    for name, route in routes.items():
        paths = [p for p in _PATH.findall("\n".join(route["lines"])) if not p.startswith("/.well-known/")]
        require, tools, seen = set(), {}, 0
        for line in route["lines"]:
            seen += len(_ROLE_REF.findall(line))
            rule = _RULE.match(line)
            if not rule:
                continue
            cel = rule.group(1)
            roles = _ROLE_REF.findall(cel)
            if not roles:
                continue
            names = _TOOL_EQ.findall(cel)
            listed = _TOOL_IN.search(cel)
            if listed:
                names += re.findall(r'"([^"]+)"', listed.group(1))
            if "mcp.tool.name" in cel and not names:
                raise kc_rbac.CatalogError(f"config: ruta {name}: regla de tool que el parser no sabe leer: {cel[:80]}")
            for role in roles:
                if names:
                    tools.setdefault(role, set()).update(names)
                else:
                    require.add(role)
        captured = sum(len(_ROLE_REF.findall(_RULE.match(l).group(1))) for l in route["lines"] if _RULE.match(l))
        if captured != seen:
            raise kc_rbac.CatalogError(f"config: ruta {name}: {seen - captured} referencias de rol fuera de una regla legible")
        references += seen
        parsed[name] = {"path": paths[0] if paths else "", "require": require, "tools": tools}

    total = sum(len(_ROLE_REF.findall(l)) for l in lines if not _is_comment(l))
    if not parsed:
        raise kc_rbac.CatalogError("config: no se encontró ninguna ruta")
    if total != references:
        raise kc_rbac.CatalogError(f"config: {total - references} referencias de rol fuera de cualquier ruta")
    return parsed


def load_matrix(path):
    """The json block of ROUTE-ROLES.md, validated. Returns (routes, unrouted)."""
    document = kc_rbac.load_json_block(path)
    if not isinstance(document, dict) or not isinstance(document.get("routes"), list) or not isinstance(document.get("unrouted"), list):
        raise kc_rbac.CatalogError(f"{path}: el bloque json necesita las listas routes y unrouted")
    routes = {}
    for index, entry in enumerate(document["routes"]):
        where = f"{path}: routes[{index}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("route"), str) or not entry["route"]:
            raise kc_rbac.CatalogError(f"{where} sin route")
        name = entry["route"]
        if name in routes:
            raise kc_rbac.CatalogError(f"{where}: ruta {name} duplicada")
        require, tools = entry.get("require"), entry.get("tools")
        if not isinstance(entry.get("path"), str) or not isinstance(require, list) or not isinstance(tools, dict):
            raise kc_rbac.CatalogError(f"{where}: {name} necesita path, require (lista) y tools (objeto)")
        if not all(isinstance(t, list) for t in tools.values()):
            raise kc_rbac.CatalogError(f"{where}: {name}: cada rol de tools lleva una lista de tools")
        routes[name] = {"path": entry["path"], "require": set(require), "tools": {r: set(t) for r, t in tools.items()}}
    unrouted = {}
    for index, entry in enumerate(document["unrouted"]):
        where = f"{path}: unrouted[{index}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("role"), str) or not entry["role"]:
            raise kc_rbac.CatalogError(f"{where} sin role")
        if entry.get("disposition") not in UNROUTED_DISPOSITIONS:
            raise kc_rbac.CatalogError(f"{where}: disposition de {entry['role']} debe ser {', '.join(UNROUTED_DISPOSITIONS)}")
        if not isinstance(entry.get("purpose"), str) or not entry["purpose"].strip():
            raise kc_rbac.CatalogError(f"{where}: purpose de {entry['role']} vacío")
        unrouted[entry["role"]] = entry
    return routes, unrouted


def _gates(route):
    return set(route["require"]) | set(route["tools"])


def find_drift(matrix_routes, unrouted, config_routes, realm_roles):
    """Return (drift lines, gate count)."""
    drift = []
    for name in sorted(set(config_routes) - set(matrix_routes)):
        roles = ", ".join(sorted(_gates(config_routes[name]))) or "sin rol"
        drift.append(f"DRIFT: ruta {name} ({config_routes[name]['path']}) está en el config y no en la matriz ({roles})")
    for name in sorted(set(matrix_routes) - set(config_routes)):
        drift.append(f"DRIFT: ruta {name} está en la matriz y no en el config")
    for name in sorted(set(matrix_routes) & set(config_routes)):
        live, declared = config_routes[name], matrix_routes[name]
        if live["path"] != declared["path"]:
            drift.append(f"DRIFT: ruta {name}: path {live['path']} en el config, {declared['path']} en la matriz")
        for role in sorted(live["require"] - declared["require"]):
            drift.append(f"DRIFT: ruta {name}: el config exige {role} a nivel de ruta y la matriz no lo recoge")
        for role in sorted(declared["require"] - live["require"]):
            drift.append(f"DRIFT: ruta {name}: la matriz declara {role} a nivel de ruta y el config no lo exige")
        for role in sorted(set(live["tools"]) | set(declared["tools"])):
            have, want = live["tools"].get(role, set()), declared["tools"].get(role, set())
            if not want:
                drift.append(f"DRIFT: ruta {name}: {role} gatea {len(have)} tools en el config y la matriz no lo recoge")
            elif not have:
                drift.append(f"DRIFT: ruta {name}: la matriz declara {role} por tool y el config no lo usa")
            else:
                for tool in sorted(have - want):
                    drift.append(f"DRIFT: ruta {name}: tool {tool} gateada por {role} falta en la matriz")
                for tool in sorted(want - have):
                    drift.append(f"DRIFT: ruta {name}: tool {tool} de {role} en la matriz y no en el config")

    referenced = set().union(*(_gates(route) for route in config_routes.values()))
    for role in sorted(referenced - realm_roles):
        drift.append(f"DRIFT: {role} referenciado en config y ausente del realm")
    gateway = {role for role in realm_roles if role.startswith(GATEWAY_ROLE_PREFIX)} | referenced | set(unrouted)
    for role in sorted(gateway - referenced - set(unrouted)):
        drift.append(f"DRIFT: rol gateway {role} vivo sin ruta que lo exija ni entrada en unrouted")
    for role in sorted(set(unrouted) & referenced):
        where = ", ".join(sorted(n for n, r in config_routes.items() if role in _gates(r)))
        drift.append(f"DRIFT: {role} está en unrouted pero lo exige la ruta {where}")
    for role in sorted(set(unrouted) - realm_roles):
        drift.append(f"DRIFT: {role} está en unrouted y ausente del realm")
    return drift, sum(len(_gates(route)) for route in config_routes.values())


def read_live_config():
    try:
        completed = subprocess.run(
            ["kubectl", "-n", CONFIG_NAMESPACE, "get", "configmap", CONFIG_MAP, "-o", "json"],
            check=False,
            capture_output=True,
            timeout=kc_rbac.TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise kc_rbac.KcError(f"kubectl no disponible: {exc}") from None
    if completed.returncode != 0:
        raise kc_rbac.KcError(f"kubectl get configmap {CONFIG_NAMESPACE}/{CONFIG_MAP} falló (exit {completed.returncode})")
    try:
        return json.loads(completed.stdout)["data"][CONFIG_KEY]
    except (ValueError, KeyError, TypeError):
        raise kc_rbac.KcError(f"el ConfigMap {CONFIG_MAP} no trae {CONFIG_KEY}") from None


def main(argv=None, env=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--matrix", default=DEFAULT_MATRIX, help="ruta de la matriz (por defecto ROUTE-ROLES.md del repo)")
    parser.add_argument("--config-file", help="copia local de config.yaml en vez del ConfigMap vivo")
    args = parser.parse_args(argv)
    try:
        matrix_routes, unrouted = load_matrix(args.matrix)
        if args.config_file:
            try:
                with open(args.config_file, encoding="utf-8") as handle:
                    text = handle.read()
            except OSError as exc:
                raise kc_rbac.KcError(f"no se puede leer {args.config_file}: {exc.strerror}") from None
        else:
            text = read_live_config()
        config_routes = parse_config(text)
        realm_roles = {role["name"] for role in kc_rbac.Client.from_env(env).realm_roles()}
        drift, gates = find_drift(matrix_routes, unrouted, config_routes, realm_roles)
    except (kc_rbac.KcError, kc_rbac.CatalogError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if drift:
        print("\n".join(drift))
        return 1
    print(f"OK: {gates} gates coherentes, 0 roles referenciados inexistentes, 0 roles sin ruta documentada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
