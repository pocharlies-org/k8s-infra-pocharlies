#!/usr/bin/env python3
"""Grafo determinista de imagenes (INFRA-1296, INFRA-536 P1, criterio C2).

Consume docs/images/inventario.json y escribe docs/images/grafo.md y grafo.dot.
Dos ejecuciones sobre el mismo inventario dan bytes identicos (`git diff
--exit-code` limpio): nodos y aristas ordenados y ninguna marca de tiempo de
ejecucion. Raices = bases (propias y de terceros); intermedias = propias que son
base de otra propia; hojas = despliegues. Cada imagen del inventario aparece como
nodo, tambien los espejos.
"""
import argparse
import json
import sys
from pathlib import Path

FORMA = {"imagen": "ellipse", "espejo": "ellipse", "base": "doublecircle",
         "despliegue": "box"}


def construir(entradas):
    nodos = {}
    for e in entradas:
        nodos[e["repo"]] = "espejo" if e.get("clase") == "espejo" else "imagen"
    aristas = set()
    for e in entradas:
        for d in e.get("deployments", []):
            nodos.setdefault(d, "despliegue")
            aristas.add((e["repo"], d))
        base_digest = e.get("base_digest")
        if isinstance(base_digest, list):
            for b in base_digest:
                img = b.get("imagen") if isinstance(b, dict) else None
                if img:
                    nodos.setdefault(img, "base")
                    aristas.add((img, e["repo"]))
    return nodos, aristas


def dot(nodos, aristas):
    lineas = ["digraph imagenes {", "  rankdir=LR;"]
    for nid in sorted(nodos):
        lineas.append('  "{}" [shape={}];'.format(nid, FORMA[nodos[nid]]))
    for origen, destino in sorted(aristas):
        lineas.append('  "{}" -> "{}";'.format(origen, destino))
    lineas.append("}")
    return "\n".join(lineas) + "\n"


def markdown(nodos, aristas, entradas):
    hijos = {}
    padres = {}
    for origen, destino in aristas:
        hijos.setdefault(origen, []).append(destino)
        padres.setdefault(destino, []).append(origen)
    lineas = ["# Grafo de imagenes (INFRA-536)", "",
              "Regenerado por `scripts/image-graph.py` a partir de `docs/images/inventario.json`.",
              "No tocar a mano: se regenera.", "", "## Raices (bases)", ""]
    raices = sorted(n for n, t in nodos.items() if t == "base")
    for base in raices:
        lineas.append("- `{}` -> {}".format(base, ", ".join("`{}`".format(h)
                                                            for h in sorted(hijos.get(base, [])))))
    if not raices:
        lineas.append("- (ninguna)")
    lineas += ["", "## Imagenes", ""]
    for e in entradas:
        bases_de = sorted(padres.get(e["repo"], []))
        lineas.append("- `{}` ({}) — bases: {}; despliegues: {}".format(
            e["repo"], e["clase"],
            ", ".join("`{}`".format(b) for b in bases_de) if bases_de else "sin_dato",
            len(e.get("deployments", []))))
    lineas += ["", "## Despliegues", ""]
    for n in sorted(n for n, t in nodos.items() if t == "despliegue"):
        lineas.append("- `{}` <- {}".format(n, ", ".join("`{}`".format(p)
                                                        for p in sorted(padres.get(n, [])))))
    return "\n".join(lineas) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inventario", default="docs/images/inventario.json")
    ap.add_argument("--out-dir", default="docs/images")
    args = ap.parse_args(argv)

    try:
        entradas = json.loads(Path(args.inventario).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print("no se pudo leer {}: {}".format(args.inventario, error), file=sys.stderr)
        return 1
    nodos, aristas = construir(entradas)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "grafo.dot").write_text(dot(nodos, aristas), encoding="utf-8")
    (out_dir / "grafo.md").write_text(markdown(nodos, aristas, entradas), encoding="utf-8")
    print("{} nodos, {} aristas en {}".format(len(nodos), len(aristas), out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
