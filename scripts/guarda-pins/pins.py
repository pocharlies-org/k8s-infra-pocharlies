"""Enumeración de pins de Harbor fijados por digest en los repos GitOps (INFRA-1365).

La retención del proyecto `homelab` de Harbor (cron sábado 03:00 UTC: conserva los
2 últimos push + los tags `keep-*` + los pullados en 7 días) borra los tags de
imágenes fijadas por digest desde GitOps. La convención que lo evita: toda imagen
que CI publica lleva el tag `keep-<digest12>` (keep- + 12 primeros hex del digest
del INDEX) sobre el mismo manifest. Este módulo es la pieza común que consumen la
guarda (INFRA-1366, alerta) y `migrar.py` (INFRA-1365, retag): recorre los repos
GitOps listados, extrae los pins `@sha256:` de values/kustomizations/deployments y
comprueba en Harbor si el digest existe y lleva algún tag `keep-*`.

Extracción con PyYAML (stack de tests del repo): se parsean los documentos YAML y
se recorren todas las cadenas (claves y valores) buscando el patrón de pin. Si
PyYAML no está importable (imagen mínima del Job, como `python:3.13-alpine`) se
usa el mismo patrón por regex sobre el texto crudo: un pin `@sha256:<64hex>` es una
subcadena inequívoca, y los tests fijan que ambas rutas dan el mismo conjunto.

El digest es siempre el del INDEX (el que fijan los pins), nunca de arquitectura.

Comprobación en Harbor por la API de tags anidados
(`GET /api/v2.0/projects/{p}/repositories/{r}/artifacts/{digest}/tags`), que sí
responde a cuentas robot (200); el listado de artefactos responde 403 a robots
(hallazgo 4 del architect), por eso se comprueba por digest conocido, nunca
listando. El retag usa la primitiva CreateTag (POST, 201/409 + verify).
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request

# harbor[.lan].e-dani.com/<project>/<name>[/<sub>]@sha256:<64 hex>
PIN_RE = re.compile(
    r"\bharbor(?:\.lan)?\.e-dani\.com/([a-z0-9][a-z0-9._/-]*?)/([a-z0-9][a-z0-9._-]*)@sha256:([a-f0-9]{64})\b"
)

HARBOR_BASE_DEFAULT = "https://harbor.lan.e-dani.com"

# Transient classes retried against Harbor (the Job keeps backoffLimit 0, so the
# retry is in-process): 429 and 5xx. A 4xx other than 404/409 is a real error.
HTTP_ATTEMPTS = 3
HTTP_BACKOFF = (2, 4)


def keep_tag(digest: str) -> str:
    """`keep-` + los 12 primeros hex del digest del index (convención INFRA-1274)."""
    hex_part = digest.split(":", 1)[1] if ":" in digest else digest
    return "keep-" + hex_part[:12]


def _iter_strings(obj):
    """Todas las cadenas de un documento parseado (claves y valores, anidados)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)


def _pins_from_strings(strings):
    out = set()
    for s in strings:
        for m in PIN_RE.finditer(s):
            project, name, hex_ = m.group(1), m.group(2), m.group(3)
            repo = f"{project}/{name}"
            out.add((repo, "sha256:" + hex_))
    return out


def extract_pins_from_text(text: str) -> set[tuple[str, str]]:
    """Pins (repo, digest) de un texto YAML.

    Ruta canónica: parsear con PyYAML y recorrer las cadenas (evita falsos
    positivos fuera del YAML y cubre values/kustomizations/deployments igual).
    Fallback sin PyYAML (imagen mínima del Job): regex sobre el texto crudo.
    """
    try:
        import yaml  # noqa: PLC0415 - optional at runtime, present in tests
    except ImportError:
        return _pins_from_strings([text])
    out = set()
    for doc in yaml.safe_load_all(text):
        out |= _pins_from_strings(_iter_strings(doc))
    return out


def extract_pins_from_file(path) -> set[tuple[str, str]]:
    with open(path, "r", encoding="utf-8") as f:
        return extract_pins_from_text(f.read())


def enumerate_pins(dirs) -> list[tuple[str, str, str]]:
    """Recorre los directorios dados y devuelve [(repo, digest, fichero_origen)].

    `dirs` es una lista de rutas raíz (checkouts GitOps). Se inspeccionan los
    `.yaml`/`.yml`. Un mismo pin puede salir de varios ficheros: se devuelve una
    entrada por (repo, digest) con el primer fichero que lo fija.
    """
    import os  # noqa: PLC0415
    seen: dict[tuple[str, str], str] = {}
    for root in dirs:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            # no meternos en clones anidados ni en el propio worktree
            if "/.git" in dirpath or "/.claude/worktrees" in dirpath:
                continue
            for fn in sorted(files):
                if not (fn.endswith(".yaml") or fn.endswith(".yml")):
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    pins = extract_pins_from_file(fp)
                except (OSError, UnicodeDecodeError):
                    continue
                for repo, digest in pins:
                    seen.setdefault((repo, digest), fp)
    return [(repo, digest, src) for (repo, digest), src in seen.items()]


# --- Harbor client (solo stdlib: urllib + basic auth) -----------------------

def _harbor_request(method: str, url: str, user: str, password: str, body=None):
    """Devuelve (status, parsed_json_or_None). Reintenta 429/5xx en memoria."""
    import time  # noqa: PLC0415
    data = None if body is None else json.dumps(body).encode()
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    last = (0, None)
    for attempt in range(HTTP_ATTEMPTS):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", "Basic " + token)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read() or b"{}"
                return (r.status, json.loads(raw))
        except urllib.error.HTTPError as e:
            last = (e.code, None)
            # 404 (digest inexistente) y 409 (tag ya existe) son respuestas de
            # control, no errores: se devuelven sin reintentar.
            if e.code in (404, 409) or not (e.code == 429 or 500 <= e.code < 600):
                return (e.code, None)
            if attempt == HTTP_ATTEMPTS - 1:
                return (e.code, None)
            time.sleep(HTTP_BACKOFF[min(attempt, len(HTTP_BACKOFF) - 1)])
        except (urllib.error.URLError, TimeoutError):
            last = (0, None)
            if attempt == HTTP_ATTEMPTS - 1:
                raise
            time.sleep(HTTP_BACKOFF[min(attempt, len(HTTP_BACKOFF) - 1)])
    return last


def _tags_url(base: str, repo: str, digest: str) -> str:
    project, _, name = repo.partition("/")
    return (
        f"{base}/api/v2.0/projects/{urllib.parse.quote(project)}"
        f"/repositories/{urllib.parse.quote(name, safe='')}"
        f"/artifacts/{urllib.parse.quote(digest)}/tags"
    )


def harbor_tag_names(base: str, repo: str, digest: str, user: str, password: str):
    """Nombres de tag sobre el digest. None si el digest no existe (404)."""
    status, parsed = _harbor_request("GET", _tags_url(base, repo, digest), user, password)
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"Harbor tag lookup failed: HTTP {status} for {repo}@{digest}")
    return [t["name"] for t in (parsed or [])]


def create_tag(base: str, repo: str, digest: str, tag: str, user: str, password: str) -> int:
    """Primitiva CreateTag: POST .../artifacts/{digest}/tags. Devuelve el código.

    201 = creado; 409 = ya existe (quien llama verifica que resuelve al mismo
    digest); cualquier otro código es fallo. No se introduce un GET+PUT nuevo.
    """
    status, _ = _harbor_request(
        "POST", _tags_url(base, repo, digest), user, password, body={"name": tag}
    )
    return status


def verify_tag_on_digest(base: str, repo: str, digest: str, tag: str, user: str, password: str) -> bool:
    """El tag `tag` está efectivamente sobre `digest` (verificación post-escritura)."""
    names = harbor_tag_names(base, repo, digest, user, password)
    return names is not None and tag in names


# --- clasificación de un pin ------------------------------------------------

PROTEGIDO = "PROTEGIDO"
DESPROTEGIDO = "DESPROTEGIDO"
INEXISTENTE = "INEXISTENTE"


def classify_pin(base: str, repo: str, digest: str, user: str, password: str) -> str:
    """PROTEGIDO (lleva algún keep-*), DESPROTEGIDO (existe, sin keep-*) o
    INEXISTENTE (el digest ya fue borrado por la retención: no es retagueable)."""
    names = harbor_tag_names(base, repo, digest, user, password)
    if names is None:
        return INEXISTENTE
    if any(n.startswith("keep-") for n in names):
        return PROTEGIDO
    return DESPROTEGIDO
