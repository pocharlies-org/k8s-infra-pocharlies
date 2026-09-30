#!/usr/bin/env python3
"""mapa_conflictos.py — INFRA-283 H2 (INFRA-337): solapes por recurso compartido.

Lee `inventario.md` (H1) y, para cada fila, toma horario, zona, duración medida
(mediana y máximo) y recursos. Expande los disparos sobre una semana de noches
22:00–08:00 Europe/Madrid (noches del lunes 28-09-2026 al domingo 04-10-2026,
fijas para que la salida sea reproducible) y cruza cada par de trabajos que
comparten un recurso: minutos de solape con la mediana y con el máximo.

- Trabajos de «fondo» (periodo <= 30 min o continuos): no se cruzan par a par
  (cruzarían con todo); se listan por recurso con su ocupación (duración/periodo).
- Filas sin duración (`sin historial`), suspendidas o retiradas: fuera del cálculo,
  cada una con su motivo en la tabla de cobertura.
- Recursos: los del manifiesto según `inventario.md` + los hechos físicos medidos
  en H2 (qué MinIO, qué nodo, qué volumen), que van en `EXTRA` con su fuente.

Solo stdlib; importa el expansor de cron de `cuenta_ventana.py` (H1).
Uso:  python3 mapa_conflictos.py [inventario.md] > salida.md
"""
from __future__ import annotations

import datetime as dt
import os
import re
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cuenta_ventana import Cron, LOCAL  # noqa: E402

NIGHT0 = dt.date(2026, 9, 28)  # lunes; 7 noches
NIGHTS = [NIGHT0 + dt.timedelta(days=i) for i in range(7)]
DOW = "lun mar mié jue vie sáb dom".split()
FONDO_MAX_PERIOD = 30  # min

# ---------------------------------------------------------------- recursos
RES = {
    "DISCO-SAUVAGE": ("disco", "minio-0 y disco del nodo sauvage (dumps, kit de recuperación, pods del nodo)"),
    "DISCO-DRIVE-S3": ("disco", "volumen nfs-cold `skirmshop-drive-mirror` (NFS en sauvage, 100.109.183.9) servido por el MinIO skirmshop-drive-s3 (pod en ubuntu)"),
    "DISCO-LONGHORN": ("disco", "Longhorn: snapshots y backup al BackupTarget default (NFS en ubuntu, 100.83.56.98)"),
    "HOST-X86": ("CPU/disco", "host x86 = nodo ubuntu: pods del nodo + unidades del host"),
    "ROUTER": ("router", "LiteLLM (pods en ubuntu) → residente qwen38-flash-next (Sparks)"),
    "PG": ("BD", "Postgres compartido (databases/postgres-shared)"),
    "BRAIN": ("BD", "brain de skirmshop-brain-prod (Qdrant/FalkorDB/Valkey)"),
    "RABBIT": ("cola", "RabbitMQ compartido → workers de synapse"),
    "API-SHOPIFY": ("límite API", "Shopify Admin API"),
    "API-PICQER": ("límite API", "Picqer API"),
    "API-GA4": ("límite API", "Google Analytics 4"),
    "API-DRIVE": ("límite API", "Google Drive (rclone)"),
    "API-AEAT": ("límite API", "AEAT (SII, DEH, DEHú)"),
    "API-GITHUB": ("límite API", "GitHub API"),
    "API-CLOUDFLARE": ("límite API", "Cloudflare DNS API"),
}
ORDER = list(RES)
SATURABLE = {"disco", "CPU/disco", "router", "BD"}

# Reglas sobre la columna «recursos que toca» (en minúsculas).
RULES = [
    (r"residente|router local|modelo `tooling`|liteLLM \(api admin|litellm \(sonda|litellm \(gasto", "ROUTER"),
    (r"postgres compartido", "PG"),
    (r"^brain|\+ brain|brain \(|brain-ingest", "BRAIN"),
    (r"rabbitmq", "RABBIT"),
    (r"shopify", "API-SHOPIFY"),
    (r"picqer", "API-PICQER"),
    (r"analytics 4", "API-GA4"),
    (r"google drive", "API-DRIVE"),
    (r"aeat|deh", "API-AEAT"),
    (r"github", "API-GITHUB"),
    (r"cloudflare", "API-CLOUDFLARE"),
    (r"longhorn", "DISCO-LONGHORN"),
]
# Hechos físicos medidos en H2 (kubectl get endpointslices/cronjob/backuptargets,
# manifiestos de dgx-infra/k8s/backup/logical-dumps y k8s-skirmshop-drive-mirror) y
# `kubectl get nodes -o wide` (CTO, 30-09-2026): 100.109.183.9 = sauvage (servidor NFS de
# nfs-cold, /srv/nfs/k8s-cold) y 100.83.56.98 = ubuntu (BackupTarget default de Longhorn).
EXTRA = {
    # escriben o leen minio-0 (svc minio-s3, nodo sauvage)
    "databases/logical-dump-postgres-shared": {"DISCO-SAUVAGE", "PG"},
    "databases/logical-dump-postgres-shared-weekly": {"DISCO-SAUVAGE"},
    "keycloak/logical-dump-keycloak-postgres": {"DISCO-SAUVAGE"},
    "opencode/logical-dump-opencode": {"DISCO-SAUVAGE"},
    "aiops/logical-dump-aiops": {"DISCO-SAUVAGE"},
    "libreplay/localpath-x86-backup": {"DISCO-SAUVAGE"},
    "backup-hub/recovery-kit-to-drive": {"DISCO-SAUVAGE", "API-DRIVE"},
    # leen/escriben el volumen nfs-cold (NFS en sauvage) que sirve skirmshop-drive-s3 (pod en ubuntu)
    "synapse/synapse-skirmbooks-s3-drive-backup": {"DISCO-DRIVE-S3", "DISCO-SAUVAGE", "API-DRIVE", "HOST-X86"},
    "backup-hub/skirmshop-drive-mirror": {"DISCO-DRIVE-S3", "DISCO-SAUVAGE", "API-DRIVE"},
    "backup-hub/skirmshop-drive-s3-to-drive": {"DISCO-DRIVE-S3", "DISCO-SAUVAGE", "API-DRIVE"},
    # el BackupTarget default de Longhorn es un NFS en ubuntu
    "longhorn-system/weekly-backup": {"HOST-X86"},
    # el pase de memorias hace nsenter al host x86 y clasifica por el router
    "kube-system/company-dreaming": {"ROUTER", "HOST-X86"},
    "blog-daily": {"ROUTER", "HOST-X86"},
    # los embeddings (bge-m3) corren en ubuntu
    "whatsapp-mcp/brain-ingest": {"HOST-X86"},
    "skirmshop-brain-prod/skirmshop-brain-reembed-truncated": {"HOST-X86", "BRAIN"},
}
NOT = {  # falsos positivos de las reglas
    "chat/searxng-autoupdate": {"API-GITHUB"},
    "aurora/aurorasvc-brain-kb-sync": {"BRAIN"},  # Qdrant de aiops, no el brain
    "skirmshop-product-relations/brain-product-relations-projector": {"BRAIN"},  # su propio Qdrant/FalkorDB
}
# Pesados por recurso de disco/host (medido o declarado en el manifiesto). En los recursos de
# nodo (DISCO-*, HOST-X86) un par solo cuenta si al menos uno es pesado: dos pods ligeros en el
# mismo nodo no son un conflicto. En los demás recursos, pesado = duración máx >= 10 min.
HEAVY = {
    "backup-hub/recovery-kit-to-drive": {"DISCO-SAUVAGE"},
    "databases/logical-dump-postgres-shared": {"DISCO-SAUVAGE"},
    "databases/logical-dump-postgres-shared-weekly": {"DISCO-SAUVAGE"},
    "libreplay/localpath-x86-backup": {"DISCO-SAUVAGE", "HOST-X86"},
    "synapse/synapse-skirmbooks-s3-drive-backup": {"DISCO-DRIVE-S3", "DISCO-SAUVAGE"},
    "backup-hub/skirmshop-drive-mirror": {"DISCO-DRIVE-S3", "DISCO-SAUVAGE"},
    "longhorn-system/weekly-backup": {"DISCO-LONGHORN", "HOST-X86"},
    "backup-runner.sh x86": {"HOST-X86"},
    "x86-localpath-pull": {"HOST-X86"},
    "restic-hostpath-backup@ubuntu": {"HOST-X86"},
    "fstrim": {"HOST-X86"},
    "kube-system/company-dreaming": {"HOST-X86"},
}
NODE_RES = {"DISCO-SAUVAGE", "DISCO-DRIVE-S3", "DISCO-LONGHORN", "HOST-X86"}

# Filas del x86 y de Hermes: horario local en cron, desfase aleatorio (min) o fondo.
#   ("cron", expr, jitter) · ("fondo", periodo_min) · ("fuera", motivo)
HOSTSCHED = {
    "backup-runner.sh x86": ("cron", "0 3 * * *", 0),
    "cloudflare-ddns.sh": ("fondo", 5),
    "brain-sweep.sh": ("fondo", 5),
    "brain-opencode-sync.py": ("fondo", 10),
    "dgx463-perfil-watch.sh": ("cron", "17 * * * *", 0),
    "reinicio bge-m3-embedding (docker)": ("fuera", "no-op: el contenedor no existe"),
    "run-parts cron.daily": ("cron", "25 6 * * *", 0),
    "update-watch-host-versions": ("cron", "30 3 * * *", 0),
    "browser-harness-daily-update": ("cron", "23 4 * * *", 0),
    "company-kanban-limpieza": ("cron", "40 4 * * *", 0),
    "blog-daily": ("cron", "0 5 * * *", 3),
    "music3-window-rollout": ("fuera", "retirada: la unidad no existe el 30-09"),
    "vscode-archivadas-kill": ("fondo", 0.25),
    "company-agent": ("fondo", 0.5),
    "rc-title-sync": ("fondo", 1),
    "company-options-applier": ("fondo", 2),
    "company-freno-alibaba": ("fondo", 30),
    "owui-mcp-defaults-watch": ("fondo", 30),
    "claude-rc-keepalive": ("fondo", 60),
    "dpkg-db-backup": ("cron", "0 0 * * *", 0),
    "logrotate": ("cron", "0 0 * * *", 0),
    "man-db": ("fuera", "hora aleatoria en toda la noche (RandomizedDelay); 3 s"),
    "sysstat-summary": ("cron", "7 0 * * *", 0),
    "x86-localpath-pull": ("cron", "30 4 * * *", 0),
    "restic-hostpath-backup@ubuntu": ("cron", "33 4 * * *", 1),
    "apt-daily-upgrade": ("cron", "0 6 * * *", 60),
    "apt-daily": ("fuera", "hora aleatoria en 12 h (RandomizedDelay); 31–58 s"),
    "weekly-apt-upgrade": ("cron", "30 4 * * 6", 20),
    "e2scrub_all": ("cron", "10 3 * * 0", 0),
    "fstrim": ("cron", "0 0 * * 1", 100),
    "tesla-fleet-watchdog": ("fuera", "timer disabled: no dispara"),
    "flannel-heal": ("fondo", 2),
    "ext4-guard": ("fondo", 2),
    "sysstat-collect": ("fondo", 10),
    "github-app-token": ("fondo", 45),
    "fwupd-refresh": ("fuera", "hora aleatoria (RandomizedDelay 12 h); 0–1 s"),
    "Prep suplementación semanal": ("cron", "0 22 * * 1", 0),
    "HGH nocturna": ("cron", "30 22 * * *", 0),
    "Buenos días Hogar": ("cron", "0 6 * * *", 0),
    "Seguimiento envíos": ("cron", "0 7 * * *", 0),
    "pm-revision-diaria-backlog": ("cron", "0 7 * * *", 0),
    "informe del VP 08:00": ("fuera", "retirado (x86-host-runtime a40a329, 17-09)"),
}
# Duración con más precisión que el redondeo del inventario, citada en la propia fila.
DUR_OVERRIDE = {"backup-runner.sh x86": (9.2, 8853 / 60)}


# ---------------------------------------------------------------- parseo
def minutes(num: str, unit: str) -> float:
    v = float(num.replace(",", "."))
    return {"s": v / 60, "min": v, "h": v * 60}[unit]


def parse_dur(cell: str):
    c = cell.strip()
    if c.startswith("sin historial"):
        return None
    if c.startswith("menos de 1 s"):
        return (0.01, 0.01)
    m = re.search(r"med ([\d,]+) (s|min|h) · máx ([\d,]+) (s|min|h)", c)
    if m:
        return (minutes(m[1], m[2]), minutes(m[3], m[4]))
    m = re.match(r"([\d,]+) (s|min|h)\b", c)
    if m:
        v = minutes(m[1], m[2])
        return (v, v)
    raise ValueError(f"duración no reconocida: {cell!r}")


def main_node(cell: str) -> str:
    counts = re.findall(r"(ks5-cp-\d|sauvage|ubuntu)\s+(\d+)/\d+", cell)
    if counts:
        return max(counts, key=lambda x: int(x[1]))[0]
    if "host x86" in cell or "hostname=ubuntu" in cell:
        return "ubuntu"
    if "role=edge" in cell:  # etiqueta del nodo de borde (sauvage)
        return "sauvage"
    if "hermes-gateway" in cell:
        return "ks5-cp-3"
    return "?"


class Job:
    def __init__(self, cells: list[str], cronjob: bool):
        self.cronjob = cronjob
        raw = cells[0].strip()
        self.name = raw if cronjob else raw.split("·")[-1].strip()
        self.label = raw
        self.horario, self.tzcell, self.durcell = cells[1].strip(), cells[2].strip(), cells[3].strip()
        self.disparos, self.recursos, self.nodecell = cells[4].strip(), cells[5].strip(), cells[6].strip()
        self.notas = cells[8].strip() if len(cells) > 8 else ""
        self.dur = DUR_OVERRIDE.get(self.name) or parse_dur(self.durcell)
        self.node = main_node(self.nodecell)
        self.suspended = "SUSPENDIDO" in self.notas
        self.kind, self.period, self.why, self.jitter = "puntual", None, "", 0
        self.cron, self.tz = None, LOCAL
        if cronjob:
            self.cron = Cron(self.horario.strip("`"))
            tzs = self.tzcell
            self.tz = ZoneInfo("UTC") if tzs.startswith("sin campo") else ZoneInfo(tzs)
            m = re.search(r"cada ~(\d+) min", self.disparos)
            if m and int(m[1]) <= FONDO_MAX_PERIOD:
                self.kind, self.period = "fondo", int(m[1])
        else:
            spec = HOSTSCHED.get(self.name)
            if spec is None:
                raise KeyError(f"fila sin horario en HOSTSCHED: {self.name!r}")
            if spec[0] == "cron":
                self.cron, self.jitter = Cron(spec[1]), spec[2]
            elif spec[0] == "fondo":
                self.kind, self.period = "fondo", spec[1]
            else:
                self.kind, self.why = "fuera", spec[1]
        self.res = self._resources()

    def _resources(self) -> set[str]:
        low = self.recursos.lower()
        out = {r for pat, r in RULES if re.search(pat.lower(), low)}
        out |= EXTRA.get(self.name, set())
        out -= NOT.get(self.name, set())
        if self.node == "ubuntu":
            out.add("HOST-X86")
        if self.node == "sauvage":
            out.add("DISCO-SAUVAGE")
        return out

    def heavy(self, res: str) -> bool:
        if res in NODE_RES:
            return res in HEAVY.get(self.name, ())
        return bool(self.dur) and self.dur[1] >= 10

    def intervals(self, which: int):
        """[(noche, inicio, fin)] en hora local, con la duración med (0) o máx (1)."""
        if not self.cron or not self.dur:
            return []
        start = dt.datetime.combine(NIGHT0, dt.time(22), LOCAL)
        end = start + dt.timedelta(days=7)
        out = []
        for t in self.cron.fires(start - dt.timedelta(hours=10), end, self.tz):
            t = t.astimezone(LOCAL)
            lt = t.time()
            if not (lt >= dt.time(22) or lt < dt.time(8)):
                continue
            night = t.date() if lt >= dt.time(22) else t.date() - dt.timedelta(days=1)
            if night not in NIGHTS:
                continue
            d = self.dur[which] + (self.jitter if which == 1 else 0)
            out.append((night, t, t + dt.timedelta(minutes=d)))
        return out


def load(path: str) -> list[Job]:
    jobs = []
    for line in open(path, encoding="utf-8").read().splitlines()[2:]:
        if not line.strip():
            continue
        cronjob = line.startswith("|")
        cells = line.strip().strip("|").split("|") if cronjob else line.split("|")
        jobs.append(Job(cells, cronjob))
    return jobs


# ---------------------------------------------------------------- cruces
def overlap(a, b, which):
    best, nights, win = 0.0, set(), None
    for na, sa, ea in a.intervals(which):
        for nb, sb, eb in b.intervals(which):
            ov = (min(ea, eb) - max(sa, sb)).total_seconds() / 60
            # el desfase aleatorio ensancha la franja, no la duración: nunca más que el más corto
            ov = min(ov, a.dur[which], b.dur[which])
            if ov > 0:
                nights.add(na)
                if ov > best:
                    best, win = ov, (min(sa, sb), max(ea, eb))
    return best, nights, win


def severity(res, a, b, omax):
    kind = RES[res][0]
    heavy = a.heavy(res) + b.heavy(res)
    if kind in SATURABLE:
        if heavy == 2 and omax >= 30:
            return "alta"
        if heavy >= 1 and omax >= 5:
            return "media"
        return "baja"
    return "media" if omax >= 30 else "baja"


def fmt_nights(ns):
    if len(ns) == 7:
        return "todas"
    return ", ".join(f"{DOW[(n - NIGHT0).days]}→{DOW[((n - NIGHT0).days + 1) % 7]}" for n in sorted(ns))


def fm(x):
    return f"{x:.0f}" if x >= 1 else ("<1" if x > 0 else "0")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "inventario.md")
    jobs = load(path)
    active = [j for j in jobs if j.kind == "puntual" and j.dur and not j.suspended and j.cron]
    fondo = [j for j in jobs if j.kind == "fondo" and not j.suspended]
    pairs = defaultdict(list)
    touched = defaultdict(set)
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            for r in sorted(a.res & b.res, key=ORDER.index):
                omax, nights, win = overlap(a, b, 1)
                if omax <= 0 or (r in NODE_RES and not (a.heavy(r) or b.heavy(r))):
                    continue
                omed, _, _ = overlap(a, b, 0)
                sev = severity(r, a, b, omax)
                pairs[r].append((a, b, win, omed, omax, nights, sev))
                touched[a.name].add((r, sev))
                touched[b.name].add((r, sev))

    print(f"<!-- generado por mapa_conflictos.py desde inventario.md: {len(jobs)} filas; noches {NIGHTS[0]:%d-%m}→{NIGHTS[-1]:%d-%m} -->\n")
    rank = {"alta": 0, "media": 1, "baja": 2}
    for r in ORDER:
        fr = [j for j in fondo if r in j.res]
        if not pairs[r] and not fr:
            continue
        print(f"### {r} — {RES[r][1]}\n")
        if pairs[r]:
            print("| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |")
            print("|---|---|---|---|---|---|")
            for a, b, win, omed, omax, nights, sev in sorted(pairs[r], key=lambda p: (rank[p[6]], -p[4])):
                print(f"| {a.name} × {b.name} | {win[0]:%H:%M}–{win[1]:%H:%M} | {fm(omed)} min | {fm(omax)} min "
                      f"| {fmt_nights(nights)} | {sev} · {RES[r][0]} |")
        else:
            print("Sin pares puntuales que se crucen en este recurso.")
        if fr:
            print("\nFondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): "
                  + "; ".join(f"{j.name} cada {j.period:g} min, ocupa "
                              + (f"{100 * j.dur[0] / j.period:.0f}–{100 * j.dur[1] / j.period:.0f} %" if j.dur else "¿? (sin historial)")
                              for j in sorted(fr, key=lambda j: -(j.dur[1] / j.period if j.dur else 0))))
        print()

    print("### Cobertura: las", len(jobs), "filas del inventario\n")
    print("| fila | recursos | estado en el mapa |")
    print("|---|---|---|")
    for j in jobs:
        res = ", ".join(sorted(j.res, key=ORDER.index)) or "propio (no compartido con otro nocturno)"
        if j.kind == "fuera":
            st = f"fuera del cálculo: {j.why}"
        elif j.suspended:
            st = "SUSPENDIDO: no dispara, sin conflicto hoy"
        elif not j.dur:
            st = "sin duración medida (sin historial): no calculable"
        elif j.kind == "fondo":
            st = f"fondo, cada {j.period:g} min (ocupación en la tabla de su recurso)"
            if j.dur[1] > j.period:
                st += f"; su máx ({fm(j.dur[1])} min) supera el periodo: con Forbid se salta disparos"
        elif touched[j.name]:
            best = {}
            for r, s in touched[j.name]:
                if r not in best or rank[s] < rank[best[r]]:
                    best[r] = s
            by = defaultdict(list)
            for r, s in best.items():
                by[s].append(r)
            st = "EN CONFLICTO: " + "; ".join(f"{s} en {', '.join(sorted(v, key=ORDER.index))}" for s, v in sorted(by.items(), key=lambda x: rank[x[0]]))
        else:
            st = "sin conflicto por recurso"
        print(f"| {j.label} | {res} | {st} |")


if __name__ == "__main__":
    main()
