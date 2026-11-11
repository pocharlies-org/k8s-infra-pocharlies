#!/usr/bin/env python3
"""Inventario regenerable de imagenes propias (INFRA-1296, INFRA-536 P1).

Punto de partida: las refs reales del cluster (`kubectl get deploy,sts,ds,cronjob
-A -o json`). Nunca se asume `latest`: se resuelve el tag o digest que el cluster
cita. Alcance: harbor.e-dani.com/homelab/*, harbor.lan.e-dani.com/homelab/*
(normalizados al mismo repo logico, con harbor.e-dani.com preferido y reintento)
y ghcr.io/pocharlies-org/*.

Contrato JSON de C1 (fijado por el architect, no cambiar): las 7 claves de toda
propia (dockerfile, base_digest, comprimido, descomprimido, capas_top,
build_fecha, deployments) estan siempre presentes y no son nulas. Un dato no
obtenible tras los reintentos queda como marcador dentro del propio campo, p. ej.
{"sin_dato": "crane config fallo tras 2 intentos"}. Los espejos (origen upstream)
llevan "clase": "espejo" y no los 7 campos.

Sin credenciales: crane y kubectl usan ~/.docker/config.json y el KUBECONFIG del
entorno tal cual; este script no escribe ni imprime secretos. Los ficheros
generados no llevan marcas de tiempo de ejecucion (romperian la regeneracion
limpia de C2); la fecha va solo dentro de los datos por imagen (build_fecha).

Modo fixture (tests, sin red ni cluster): --fixture-dir lee el JSON de kubectl y
las respuestas de crane/gh de tests/fixtures/image-inventory/.
"""
import argparse
import base64
import json
import platform
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HARBOR = "harbor.e-dani.com"
HARBOR_LAN = "harbor.lan.e-dani.com"
GHCR_ORG = "ghcr.io/pocharlies-org"
ALCANCE = (HARBOR + "/homelab/", HARBOR_LAN + "/homelab/", GHCR_ORG + "/")

# Upstreams espejados dentro del alcance (los que nombra el 00-spec.md de INFRA-536).
ESPEJOS_CONOCIDOS = ("redis", "minio", "onepassword-connect", "vllm", "searxng",
                     "clamav", "agentgateway")

INTENTOS = 2
# crane export baja el rootfs entero (medido en vivo: ~6 MB/s por capa de red):
# solo se intenta por debajo de este umbral comprimido. Las imagenes por encima
# quedan con marcador sin_dato dentro del campo (es la respuesta que fija el
# plan de INFRA-536: "crane export caro en imagenes grandes -> reintentos y
# marcador"; el guard C4 solo necesita el comprimido).
MAX_EXPORT_BYTES = 100 * 1024 * 1024
TIMEOUT_EXPORT_S = 300
CAPAS_TOP_N = 3
# GitHub code search (autenticado): 30 peticiones/minuto. Las busquedas se
# serializan por este limitador global para no provocar 403 (medido 11-11).
INTERVALO_BUSQUEDA_S = 2.1
_LIMITADOR_BUSQUEDA = threading.Lock()
_ULTIMA_BUSQUEDA = [0.0]
TRABAJADORES = 8


class RunnerReal:
    es_fixture = False

    def run(self, cmd):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return p.returncode, p.stdout
        except (subprocess.TimeoutExpired, OSError):
            return 1, ""

    def export_bytes(self, cmd):
        # `timeout` mata el crane export colgado: un worker lento no bloquea el pozo.
        try:
            p = subprocess.Popen(["timeout", str(TIMEOUT_EXPORT_S)] + cmd,
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            total = 0
            while True:
                chunk = p.stdout.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
            p.wait()
            return total if p.returncode == 0 else None
        except OSError:
            return None


class RunnerFixture:
    """Responde por clave = linea de comando exacta. Ausente = fallo (rc 1)."""

    es_fixture = True

    def __init__(self, registry, github):
        self.resp = {"crane": registry, "gh": github}

    def _get(self, cmd):
        return self.resp.get(cmd[0], {}).get(" ".join(cmd))

    def run(self, cmd):
        r = self._get(cmd)
        if r is None:
            return 1, ""
        return r.get("returncode", 0), r.get("stdout", "")

    def export_bytes(self, cmd):
        r = self._get(cmd)
        if r is None or r.get("returncode", 0) != 0:
            return None
        return r.get("stdout_bytes", 0)


def pacear_busqueda(runner):
    """Serializa las `gh search code` al ritmo que permite GitHub (30/min)."""
    if runner.es_fixture:
        return
    with _LIMITADOR_BUSQUEDA:
        esperar = INTERVALO_BUSQUEDA_S - (time.monotonic() - _ULTIMA_BUSQUEDA[0])
        if esperar > 0:
            time.sleep(esperar)
        _ULTIMA_BUSQUEDA[0] = time.monotonic()


def reintentar(runner, cmd):
    rc, out = 1, ""
    for intento in range(INTENTOS):
        rc, out = runner.run(cmd)
        if rc == 0:
            return rc, out
        if not runner.es_fixture and intento + 1 < INTENTOS:
            time.sleep(1)
    return rc, out


def reintentar_export(runner, cmd):
    for intento in range(INTENTOS):
        total = runner.export_bytes(cmd)
        if total is not None:
            return total
        if not runner.es_fixture and intento + 1 < INTENTOS:
            time.sleep(1)
    return None


def partir_ref(ref):
    """(repo, sufijo) con sufijo '@sha256:...' o ':tag' o ''."""
    if "@" in ref:
        repo, digest = ref.rsplit("@", 1)
        return repo, "@" + digest
    sep = ref.rfind(":")
    if sep > ref.rfind("/"):
        return ref[:sep], ":" + ref[sep + 1:]
    return ref, ""


def repo_logico(ref):
    """Normaliza los dos hosts de Harbor al mismo repo logico (harbor.e-dani.com)."""
    repo, sufijo = partir_ref(ref)
    if repo.startswith(HARBOR_LAN + "/"):
        repo = HARBOR + repo[len(HARBOR_LAN):]
    return repo, sufijo


def dentro_de_alcance(ref):
    return ref.startswith(ALCANCE)


def consumidores_de(doc):
    """(imagen, consumidor 'ns/Kind/nombre') de deploy, sts, ds y cronjob."""
    for item in doc.get("items", []):
        kind = item.get("kind")
        meta = item.get("metadata", {})
        consumidor = "{}/{}/{}".format(meta.get("namespace"), kind, meta.get("name"))
        if kind == "CronJob":
            plantilla = (item.get("spec", {}).get("jobTemplate", {})
                         .get("spec", {}).get("template", {}))
        else:
            plantilla = item.get("spec", {}).get("template", {})
        for seccion in ("containers", "initContainers"):
            for c in plantilla.get("spec", {}).get(seccion, []):
                img = c.get("image")
                if img:
                    yield img, consumidor


def espejo_conocido(repo):
    nombre = repo.split("/homelab/", 1)[1] if "/homelab/" in repo else repo.rsplit("/", 1)[-1]
    segmentos = re.split(r"[/-]", nombre)
    for patron in ESPEJOS_CONOCIDOS:
        # El patron completo casa con el nombre entero (p. ej. onepassword-connect)
        # y cada patron casa con un segmento (p. ej. vllm en vllm-openai).
        if nombre == patron or nombre.startswith(patron + "-"):
            return patron
        if any(s == patron or s.startswith(patron + "-") for s in segmentos):
            return patron
    return None


def es_indice(manifiesto):
    media = manifiesto.get("mediaType", "")
    return "index" in media or "manifest.list" in media


def elegir_plataforma(manifiesto, host_arq):
    """Prefiere la arquitectura del host; si el indice es de una sola plataforma
    (p. ej. ComfyUI solo arm64) toma la primera ordenada — siempre determinista.
    Descarta los hijos de atestiguacion (architecture "unknown", medido en vivo
    en los indices de Harbor: buildx adjunta una attestation-manifest)."""
    hijos = [m for m in manifiesto.get("manifests", [])
             if m.get("platform") and m["platform"].get("architecture") not in (None, "unknown")]
    for m in sorted(hijos, key=lambda m: (m["platform"].get("os", ""),
                                          m["platform"].get("architecture", ""))):
        if (m["platform"].get("architecture") == host_arq
                and m["platform"].get("os") == "linux"):
            return "linux/" + host_arq, m["digest"]
    if hijos:
        m = sorted(hijos, key=lambda m: (m["platform"].get("os", ""),
                                         m["platform"].get("architecture", "")))[0]
        p = m["platform"]
        return "{}/{}".format(p.get("os"), p.get("architecture")), m["digest"]
    return None, None


def leer_contenido(runner, repo, ruta):
    rc, out = reintentar(runner, ["gh", "api", "repos/{}/contents/{}".format(repo, ruta)])
    if rc != 0:
        return None
    try:
        return base64.b64decode(json.loads(out)["content"]).decode("utf-8", "replace")
    except (ValueError, KeyError, TypeError):
        return None


def buscar_workflow(runner, nombre):
    """Los workflows de build declaran envs IMAGE:/DOCKERFILE: (verificado en dgx-infra).

    Con la CLI real (gh 2.103, medido 11-11): el filtro de organizacion es
    `--owner` (no existe `--org`) y el motor legacy de code search no casa la
    frase exacta "IMAGE: homelab/x"; se busca el path `homelab/<nombre>` en
    ficheros .yml y se VERIFICA en el contenido la linea `IMAGE: homelab/<nombre>`.
    Devuelve el primer candidato verificado (orden determinista) o None.
    """
    pacear_busqueda(runner)
    rc, out = reintentar(runner, ["gh", "search", "code", "homelab/{}".format(nombre),
                                  "--owner", "pocharlies-org", "--extension", "yml",
                                  "--json", "repository", "path", "--limit", "5"])
    if rc != 0:
        return None
    try:
        resultados = json.loads(out)
    except ValueError:
        return None

    def clave(r):
        return (r.get("repository", {}).get("nameWithOwner", ""), r.get("path", ""))

    vistos, candidatos = set(), []
    for r in sorted(resultados, key=clave):
        if clave(r)[0] and clave(r) not in vistos:
            vistos.add(clave(r))
            candidatos.append(clave(r))
    for repo_wf, ruta_wf in candidatos:
        contenido_wf = leer_contenido(runner, repo_wf, ruta_wf) or ""
        if re.search(r"^\s*IMAGE:\s*homelab/{}\s*$".format(re.escape(nombre)),
                     contenido_wf, re.M):
            return {"repository": {"full_name": repo_wf}, "path": ruta_wf,
                    "contenido": contenido_wf}
    return None


def resolver_dockerfile(runner, repo):
    """(dockerfile, contenido, workflow). dockerfile None = ghcr sin repo GitHub (espejo)."""
    if repo.startswith(GHCR_ORG + "/"):
        nombre = repo[len(GHCR_ORG) + 1:]
        rc, _ = reintentar(runner, ["gh", "api", "repos/pocharlies-org/{}".format(nombre)])
        if rc != 0:
            return None, None, None
        ruta = "Dockerfile"
        contenido = leer_contenido(runner, "pocharlies-org/" + nombre, ruta)
        if contenido is None:
            pacear_busqueda(runner)
            rc, out = reintentar(runner, ["gh", "search", "code", "--repo",
                                          "pocharlies-org/" + nombre,
                                          "filename:Dockerfile", "--json", "path",
                                          "--limit", "5"])
            try:
                res = json.loads(out) if rc == 0 else []
            except ValueError:
                res = []
            if not res:
                return ({"sin_dato": "sin Dockerfile en el repositorio pocharlies-org/{}"
                         .format(nombre)}, None, None)
            ruta = sorted(r.get("path", "") for r in res)[0]
            contenido = leer_contenido(runner, "pocharlies-org/" + nombre, ruta)
        return "pocharlies-org/{}:{}".format(nombre, ruta), contenido, None
    nombre = repo.split("/homelab/", 1)[1]
    hit = buscar_workflow(runner, nombre)
    if hit is None:
        return ({"sin_dato": 'sin workflow de build que declare "IMAGE: homelab/{}" '
                            'en pocharlies-org'.format(nombre)}, None, None)
    repo_wf = hit["repository"]["full_name"]
    ruta_wf = hit["path"]
    m = re.search(r"^\s*DOCKERFILE:\s*(\S+)\s*$", hit["contenido"], re.M)
    ruta_df = m.group(1) if m else "Dockerfile"
    return ("{}:{}".format(repo_wf, ruta_df),
            leer_contenido(runner, repo_wf, ruta_df),
            "{}:{}".format(repo_wf, ruta_wf))


def bases_desde_dockerfile(runner, contenido):
    """FROM (distintas, excluyendo etapas y scratch) resueltas a digest con crane."""
    if contenido is None:
        return {"sin_dato": "sin Dockerfile que leer"}
    imagenes = []
    etapas = set()
    for linea in contenido.splitlines():
        m = re.match(r"^\s*FROM\s+(?P<resto>.+)$", linea, re.I)
        if not m:
            continue
        args = [a for a in m.group("resto").split("#")[0].split() if not a.startswith("--")]
        if not args:
            continue
        img = args[0]
        if len(args) >= 3 and args[1].upper() == "AS":
            etapas.add(args[2])
        if img.lower() == "scratch" or img in etapas:
            continue
        if img not in imagenes:
            imagenes.append(img)
    resueltas = []
    for img in sorted(imagenes):
        rc, out = reintentar(runner, ["crane", "digest", img])
        if rc == 0:
            resueltas.append({"imagen": img, "digest": out.strip()})
        else:
            resueltas.append({"imagen": img,
                              "digest": {"sin_dato": "crane digest fallo tras {} intentos"
                                         .format(INTENTOS)}})
    return resueltas


def resolver_tamanos(runner, ref, host_arq):
    """Ref real del cluster -> (resuelta, plataforma, comprimido, descomprimido,
    capas_top, build_fecha). Cada no-dato es marcador dentro de su campo."""
    rc, out = reintentar(runner, ["crane", "manifest", ref])
    if rc != 0:
        motivo = "crane manifest fallo tras {} intentos".format(INTENTOS)
        return (None, {"sin_dato": motivo}, {"sin_dato": motivo}, {"sin_dato": motivo},
                {"sin_dato": motivo}, {"sin_dato": motivo})
    try:
        manifiesto = json.loads(out)
    except ValueError:
        motivo = "crane manifest devolvio JSON invalido"
        return (None, {"sin_dato": motivo}, {"sin_dato": motivo}, {"sin_dato": motivo},
                {"sin_dato": motivo}, {"sin_dato": motivo})
    repo, _ = partir_ref(ref)
    if es_indice(manifiesto):
        plataforma, digest_hijo = elegir_plataforma(manifiesto, host_arq)
        if not digest_hijo:
            motivo = "indice OCI sin hijos con plataforma"
            return (None, {"sin_dato": motivo}, {"sin_dato": motivo}, {"sin_dato": motivo},
                    {"sin_dato": motivo}, {"sin_dato": motivo})
        resuelta = "{}@{}".format(repo, digest_hijo)
        rc, out = reintentar(runner, ["crane", "manifest", resuelta])
        if rc != 0:
            motivo = "crane manifest del hijo {} fallo".format(digest_hijo)
            return (resuelta, plataforma, {"sin_dato": motivo}, {"sin_dato": motivo},
                    {"sin_dato": motivo}, {"sin_dato": motivo})
        try:
            manifiesto = json.loads(out)
        except ValueError:
            manifiesto = {}
    else:
        plataforma = {"sin_dato": "manifiesto simple sin indice OCI"}
        if "@" in ref:
            resuelta = ref
        else:
            rc, out = reintentar(runner, ["crane", "digest", ref])
            resuelta = "{}@{}".format(repo, out.strip()) if rc == 0 else ref
    capas = sorted(manifiesto.get("layers", []),
                   key=lambda l: (-l.get("size", 0), l.get("digest", "")))
    capas_top = [{"digest": c.get("digest"), "tamano": c.get("size")} for c in capas[:CAPAS_TOP_N]]
    if capas:
        comprimido = sum(c.get("size", 0) for c in manifiesto.get("layers", []))
    else:
        comprimido = {"sin_dato": "manifiesto sin capas"}
    rc, out = reintentar(runner, ["crane", "config", resuelta])
    if rc == 0:
        try:
            build_fecha = json.loads(out).get("created") or {"sin_dato": "config sin .created"}
        except ValueError:
            build_fecha = {"sin_dato": "crane config devolvio JSON invalido"}
    else:
        build_fecha = {"sin_dato": "crane config fallo tras {} intentos".format(INTENTOS)}
    if isinstance(comprimido, int) and comprimido > MAX_EXPORT_BYTES:
        descomprimido = {"sin_dato": "omitido por tamano ({} bytes comprimidos)".format(comprimido)}
    elif not isinstance(comprimido, int):
        descomprimido = {"sin_dato": "sin comprimido del que derivar"}
    else:
        total = reintentar_export(runner, ["crane", "export", resuelta, "-"])
        descomprimido = (total if total is not None
                         else {"sin_dato": "crane export fallo tras {} intentos".format(INTENTOS)})
    return resuelta, plataforma, comprimido, descomprimido, capas_top, build_fecha


def entrada_de(runner, repo, sufijos, consumidores, host_arq):
    patron = espejo_conocido(repo)
    if patron:
        return {"clase": "espejo",
                "origen": "upstream {} espejado en el registro propio".format(patron),
                "repo": repo, "refs": sorted(sufijos),
                "deployments": sorted(consumidores)}
    dockerfile, contenido_df, workflow = resolver_dockerfile(runner, repo)
    if dockerfile is None:  # ghcr.io/pocharlies-org/<x> sin repositorio GitHub homonimo
        return {"clase": "espejo",
                "origen": "el repositorio GitHub pocharlies-org/{} no existe: espejo de un upstream"
                          .format(repo[len(GHCR_ORG) + 1:]),
                "repo": repo, "refs": sorted(sufijos),
                "deployments": sorted(consumidores)}
    if repo.startswith(HARBOR + "/"):
        candidatos = [repo, HARBOR_LAN + repo[len(HARBOR):]]
    else:
        candidatos = [repo]
    sufijo = max(sufijos)
    resuelta, plataforma, comprimido, descomprimido, capas_top, build_fecha = (
        None, {"sin_dato": "sin resolucion"}, {"sin_dato": "sin resolucion"},
        {"sin_dato": "sin resolucion"}, {"sin_dato": "sin resolucion"},
        {"sin_dato": "sin resolucion"})
    for candidato in candidatos:
        r, p, c, d, t, f = resolver_tamanos(runner, candidato + sufijo, host_arq)
        if r is not None:
            resuelta, plataforma, comprimido, descomprimido, capas_top, build_fecha = r, p, c, d, t, f
            break
    entrada = {"build_fecha": build_fecha, "capas_top": capas_top, "clase": "propia",
               "comprimido": comprimido, "descomprimido": descomprimido,
               "deployments": sorted(consumidores), "dockerfile": dockerfile,
               "base_digest": bases_desde_dockerfile(runner, contenido_df),
               "plataforma": plataforma, "refs": sorted(sufijos), "repo": repo,
               "resuelta": resuelta if resuelta is not None else {"sin_dato": "crane no resolvio la ref"}}
    if workflow:
        entrada["workflow"] = workflow
    return entrada


def inventario(doc, runner, host_arq):
    por_repo = {}
    for ref, consumidor in consumidores_de(doc):
        if not dentro_de_alcance(ref):
            continue
        repo, sufijo = repo_logico(ref)
        entrada = por_repo.setdefault(repo, {"sufijos": set(), "consumidores": set()})
        entrada["sufijos"].add(sufijo)
        entrada["consumidores"].add(consumidor)
    # Las llamadas por repo (crane, gh) van en paralelo; las busquedas gh siguen
    # el ritmo global del limitador. La salida se ordena por repo: determinista.
    items = sorted(por_repo.items())
    with ThreadPoolExecutor(max_workers=TRABAJADORES) as pozo:
        entradas = list(pozo.map(
            lambda kv: entrada_de(runner, kv[0], kv[1]["sufijos"], kv[1]["consumidores"], host_arq),
            items))
    return sorted(entradas, key=lambda e: e["repo"])


def markdown(inventario):
    lineas = ["# Inventario de imagenes propias (INFRA-536)", "",
              "Regenerado por `scripts/image-inventory.py` a partir de las refs reales del cluster.",
              "No tocar a mano: se regenera.", "",
              "| imagen | clase | dockerfile | comprimido | descomprimido | build_fecha | despliegues |",
              "|---|---|---|---|---|---|---|"]
    for e in inventario:
        def campo(nombre):
            v = e.get(nombre)
            if isinstance(v, dict) and "sin_dato" in v:
                return "sin_dato: {}".format(v["sin_dato"])
            if v is None:
                return "-"
            return str(v)
        dockerfile = campo("dockerfile") if e["clase"] == "propia" else "-"
        lineas.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            e["repo"], e["clase"], dockerfile,
            campo("comprimido") if e["clase"] == "propia" else "-",
            campo("descomprimido") if e["clase"] == "propia" else "-",
            campo("build_fecha") if e["clase"] == "propia" else "-",
            len(e["deployments"])))
    return "\n".join(lineas) + "\n"


def baseline(inventario):
    imagenes = {}
    for e in inventario:
        if e["clase"] != "propia" or not isinstance(e["resuelta"], str) or "@" not in e["resuelta"]:
            continue
        digest = e["resuelta"].rsplit("@", 1)[1]
        imagenes.setdefault(e["repo"], {})[digest] = {
            "comprimido": e["comprimido"], "descomprimido": e["descomprimido"]}
    return {"formato": ("imagen logica -> digest resuelto -> {comprimido, descomprimido} en bytes. "
                        "Linea base del guard de tamano (INFRA-536 C4). Los no-datos van como "
                        'marcador {"sin_dato": motivo} dentro del campo. Regenerado por '
                        "scripts/image-inventory.py; no tocar a mano."),
            "imagenes": imagenes}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixture-dir", help="modo test: kubectl y respuestas crane/gh desde ficheros")
    ap.add_argument("--workloads", help="JSON de `kubectl get deploy,sts,ds,cronjob -A -o json` (real)")
    ap.add_argument("--out-dir", default="docs/images")
    args = ap.parse_args(argv)

    host_arq = "arm64" if platform.machine() in ("aarch64", "arm64") else "amd64"
    if args.fixture_dir:
        fdir = Path(args.fixture_dir)
        doc = json.loads((fdir / "kubectl-workloads.json").read_text(encoding="utf-8"))
        runner = RunnerFixture(
            json.loads((fdir / "registry-responses.json").read_text(encoding="utf-8")),
            json.loads((fdir / "github-responses.json").read_text(encoding="utf-8")))
    else:
        runner = RunnerReal()
        if args.workloads:
            doc = json.loads(Path(args.workloads).read_text(encoding="utf-8"))
        else:
            rc, out = reintentar(runner, ["kubectl", "get", "deploy,sts,ds,cronjob", "-A", "-o", "json"])
            if rc != 0:
                print("kubectl fallo; KUBECONFIG=~/.kube/config es obligatorio", file=sys.stderr)
                return 1
            doc = json.loads(out)

    inv = inventario(doc, runner, host_arq)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "inventario.json").write_text(
        json.dumps(inv, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    (out_dir / "inventario.md").write_text(markdown(inv), encoding="utf-8")
    (out_dir / "sizes-baseline.json").write_text(
        json.dumps(baseline(inv), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8")
    propias = sum(1 for e in inv if e["clase"] == "propia")
    print("{} imagenes ({} propias, {} espejos) en {}".format(len(inv), propias,
                                                               len(inv) - propias, out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
