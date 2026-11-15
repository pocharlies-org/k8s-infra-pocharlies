"""migrar.py — retag de los pins de Harbor sin `keep-*` (INFRA-1365, P2).

Aplica la convención `keep-<digest12>` a los pins fijados por digest en los repos
GitOps que aún no la tienen. Usa la primitiva CreateTag (POST .../artifacts/
{digest}/tags: 201 creado, 409 ya existe → verificar mismo digest) con la
credencial de push (`harbor-push`, ns buildkit; con pull da 401, INFRA-1273).

Pins a digest ya borrado por la retención (la bomba ya cayó): NO se retaguean; se
listan como `DESPROTEGIDO ... (inexistente)` — el arreglo es re-pinear, no retaguear.

El reporte va por stdout (evidencia del Job; sin PVC). Formato:
  RETAGUEADO <repo>@<digest>            (se creó/verificó el keep-)
  DESPROTEGIDO <repo>@<digest> (inexistente)   (digest borrado: no retagueable)
  DESPROTEGIDO <repo>@<digest> (pendiente)     (no se pudo retaguear: fallo real)
  PROTEGIDO <repo>@<digest>             (ya llevaba keep-)
  retagueados: N, pendientes: M, inexistentes: K

Sale 1 si queda algún pendiente (falla el Job); 0 si todos los protegibles quedaron
protegidos (los inexistentes no son fallo: se nombran para re-pinear).

Variables de entorno:
  GITOPS_DIRS      rutas raíz a recorrer, separadas por ':' (default /work/repos)
  HARBOR_BASE      default https://harbor.lan.e-dani.com
  HARBOR_USER      usuario robot con push (harbor-push)
  HARBOR_PASSWORD  contraseña del robot
  DRY_RUN=1        no escribe: solo informa lo que retaguearía
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pins  # noqa: E402  (mismo ConfigMap montado en el Job)


def main() -> int:
    dirs = [d for d in os.environ.get("GITOPS_DIRS", "/work/repos").split(":") if d]
    base = os.environ.get("HARBOR_BASE", pins.HARBOR_BASE_DEFAULT)
    user = os.environ.get("HARBOR_USER", "")
    password = os.environ.get("HARBOR_PASSWORD", "")
    dry_run = os.environ.get("DRY_RUN") == "1"
    if not user or not password:
        print("ERROR: HARBOR_USER/HARBOR_PASSWORD no fijados", file=sys.stderr)
        return 1

    found = pins.enumerate_pins(dirs)
    if not found:
        print(f"ERROR: 0 pins encontrados en {dirs}", file=sys.stderr)
        return 1

    retagueados = 0
    pendientes = 0
    inexistentes = 0
    for repo, digest, _src in sorted(found):
        status = pins.classify_pin(base, repo, digest, user, password)
        if status == pins.PROTEGIDO:
            print(f"PROTEGIDO {repo}@{digest}")
            continue
        if status == pins.INEXISTENTE:
            inexistentes += 1
            print(f"DESPROTEGIDO {repo}@{digest} (inexistente)")
            continue
        # DESPROTEGIDO: existe y no lleva keep-*, es retagueable
        tag = pins.keep_tag(digest)
        if dry_run:
            print(f"RETAGUEARIA {repo}@{digest} -> {tag}")
            retagueados += 1
            continue
        code = pins.create_tag(base, repo, digest, tag, user, password)
        if code == 201:
            ok = pins.verify_tag_on_digest(base, repo, digest, tag, user, password)
        elif code == 409:
            # ya existe: éxito solo si resuelve al mismo digest
            ok = pins.verify_tag_on_digest(base, repo, digest, tag, user, password)
        else:
            ok = False
        if ok:
            retagueados += 1
            print(f"RETAGUEADO {repo}@{digest}")
        else:
            pendientes += 1
            print(f"DESPROTEGIDO {repo}@{digest} (pendiente, HTTP {code})")

    print(f"retagueados: {retagueados}, pendientes: {pendientes}, inexistentes: {inexistentes}")
    return 1 if pendientes else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - cualquier fallo debe fallar el Job
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
