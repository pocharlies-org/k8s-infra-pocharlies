"""Evaluador compartido de reglas de Traefik v3 para los contratos de ingress (DGX-809, DGX-829).

Cada IngressRoute que sirve el backend del panel se compraba igual: evaluar la regla con los matchers
que usan los ficheros del repo, elegir la de más prioridad que casa (como Traefik) y mirar su cadena de
middlewares. Vive aquí porque dos tests la necesitan y el detector de duplicados de la org no deja
copiar el bloque (y con razón: la semántica es una sola).
"""
import ipaddress
import re

import yaml


def casa(rule, host, ip, method, path):
    """Evalúa una regla de Traefik v3 con los matchers que usan estos ficheros (otro matcher = NameError)."""
    env = {
        "Host": lambda h: h == host,
        "ClientIP": lambda cidr: ipaddress.ip_address(ip) in ipaddress.ip_network(cidr),
        "Path": lambda p: path == p,
        "PathPrefix": lambda p: path.startswith(p),
        "PathRegexp": lambda rx: re.search(rx, path) is not None,
        "Method": lambda m: method == m,
    }
    trozos = re.split(r"(`[^`]*`)", rule)
    expr = "".join(repr(t[1:-1]) if t.startswith("`") else
                   t.replace("&&", " and ").replace("||", " or ").replace("!", " not ") for t in trozos)
    return eval(expr, {"__builtins__": {}}, env)  # noqa: S307 — solo reglas de este repo


def rutas(root, fichero, nombre):
    for doc in yaml.safe_load_all((root / fichero).read_text()):
        if doc and doc.get("kind") == "IngressRoute" and doc["metadata"]["name"] == nombre:
            return doc["spec"]["routes"]
    raise AssertionError(f"{nombre} no está en {fichero}")


def gana(listas, host, ip, method, path):
    casan = [r for r in listas if casa(r["match"], host, ip, method, path)]
    return max(casan, key=lambda r: r.get("priority", 0)) if casan else None


def cadena(ruta):
    return [(m["name"], m.get("namespace", "")) for m in (ruta or {}).get("middlewares", [])]
