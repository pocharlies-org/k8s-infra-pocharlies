#!/usr/bin/env python3
"""verifica_propuesta.py — INFRA-283 H3 (INFRA-338): comprueba la propuesta de horarios.

1. Expande cada horario propuesto de CronJob con `cuenta_ventana.analyse` (H1) y dice
   a qué horas locales dispara y si cae en la ventana 22:00–08:00.
2. Recalcula el mapa de conflictos de H2 (`mapa_conflictos.py`) antes y después de
   aplicar la propuesta, en una semana de verano (CEST, noches del 28-09-2026) y en una de
   invierno (CET, noches del 02-11-2026): los CronJobs en UTC se mueven una hora en
   hora local al cambiar la hora, y la propuesta tiene que aguantar las dos.
3. Comprueba las invariantes de la épica sobre el resultado:
   - company-dreaming sigue en `30 1 * * *` Europe/Madrid;
   - ningún job pesado se cruza con 04:50–05:10 (blog-daily);
   - ningún one-shot de inferencia se cruza con la ventana medida del clasificador de
     dreaming (01:30–03:06), ni —informativo— con su peor caso acotado por la propuesta.

Solo stdlib. Uso: python3 verifica_propuesta.py [inventario.md] > salida.md
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from collections import defaultdict
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mapa_conflictos as M  # noqa: E402
from cuenta_ventana import Cron, LOCAL, analyse  # noqa: E402

UTC = ZoneInfo("UTC")
MAD = ZoneInfo("Europe/Madrid")

# Horario base de los timers del x86 declarados en UTC (el inventario los da en CEST).
BASE_HOST_TZ = {
    "x86-localpath-pull": ("30 2 * * *", UTC, 0),
    "restic-hostpath-backup@ubuntu": ("33 2 * * *", UTC, 1),
}

# La propuesta: nombre de fila del inventario → (schedule, zona, desfase aleatorio en min).
PROPUESTA = {
    # disco de sauvage: el kit, después de todos los dumps (la familia sigue en UTC)
    "backup-hub/recovery-kit-to-drive": ("5 22 * * *", UTC, 0),
    "libreplay/localpath-x86-backup": ("30 20 * * *", UTC, 0),
    # fuera de la noche y 2 pasadas al día en vez de 4
    "synapse/synapse-skirmbooks-s3-drive-backup": ("15 8,19 * * *", MAD, 0),
    # router + brain
    "skirmshop-brain-prod/skirmshop-brain-knowledge-pages": ("15 5,11,17,23 * * *", MAD, 0),
    "skirmshop-brain-prod/skirmshop-brain-memory-promotion": ("45 5,11,17,23 * * *", MAD, 0),
    "skirmshop-brain-prod/skirmshop-brain-audit": ("30 3 * * *", MAD, 0),
    # API Shopify
    "skirmshop/rag-provider-sourcing-backfill": ("45 3 * * *", MAD, 0),
    # frecuencia (candidatos con evidencia)
    "skirmshop/shopify-sync-weights": ("41 6 * * *", MAD, 0),
    "synapse/synapse-dlq-archive-purge": ("41 5 * * 1", MAD, 0),
    # host x86 (cambios fuera de k8s)
    "backup-runner.sh x86": ("50 22 * * *", MAD, 0),
    "x86-localpath-pull": ("5 2 * * *", UTC, 0),
    "fstrim": ("45 3 * * 1", MAD, 0),
    # Longhorn RecurringJob (cron en UTC): en invierno caería en 04:50–05:10
    "longhorn-system/weekly-backup": ("0 5 * * 0", UTC, 0),
}
# Recursos que la evidencia de H3 añade al inventario (logs del Job del 30-09: Shopify «Throttled»).
EXTRA_RES = {"skirmshop/rag-provider-sourcing-backfill": {"API-SHOPIFY"}}
# company-dreaming: schedule intacto; tope de inicio y de duración (ver propuesta.md).
DREAMING = "kube-system/company-dreaming"
DREAMING_SDS_S, DREAMING_DEADLINE_S = 600, 11400
WORST_DREAMING_H = 5.5  # documentado en el spec de la épica, no medido


def build(inv, apply: bool):
    jobs = M.load(inv)
    for j in jobs:
        j.res |= EXTRA_RES.get(j.name, set())
        spec = BASE_HOST_TZ.get(j.name)
        if apply and j.name in PROPUESTA:
            spec = PROPUESTA[j.name]
        if spec:
            j.cron, j.tz, j.jitter = Cron(spec[0]), spec[1], spec[2]
            if j.kind == "fondo":
                j.kind = "puntual"
    return jobs


def pairs(jobs):
    active = [j for j in jobs if j.kind == "puntual" and j.dur and not j.suspended and j.cron]
    out = {}
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            for r in sorted(a.res & b.res, key=M.ORDER.index):
                omax, nights, win = M.overlap(a, b, 1)
                if omax <= 0 or (r in M.NODE_RES and not (a.heavy(r) or b.heavy(r))):
                    continue
                omed, _, _ = M.overlap(a, b, 0)
                key = (r,) + tuple(sorted((a.name, b.name)))
                out[key] = (omed, omax, M.severity(r, a, b, omax), nights)
    return out


def set_week(d0: dt.date):
    M.NIGHT0 = d0
    M.NIGHTS = [d0 + dt.timedelta(days=i) for i in range(7)]


def heavy_any(j):
    return any(r in M.NODE_RES and j.heavy(r) for r in j.res) or (j.dur and j.dur[1] >= 10)


def local_iv(night, hh, mm, minutes):
    base = dt.datetime.combine(night if hh >= 12 else night + dt.timedelta(days=1), dt.time(hh, mm), LOCAL)
    return base, base + dt.timedelta(minutes=minutes)


def invariants(jobs, label):
    print(f"#### Invariantes — {label}\n")
    by = {j.name: j for j in jobs}
    d = by[DREAMING]
    ok_sched = d.horario.strip("`") == "30 1 * * *" and d.tzcell == "Europe/Madrid" and DREAMING not in PROPUESTA
    print(f"- dreaming en `30 1 * * *` Europe/Madrid: {'SÍ' if ok_sched else 'NO'}")
    bad = []
    for j in jobs:
        if j.name == "blog-daily" or not j.dur or j.suspended or j.kind != "puntual" or not heavy_any(j):
            continue
        for night, s, e in j.intervals(1):
            ws, we = local_iv(night, 4, 50, 20)
            if s < we and e > ws:
                bad.append(f"{j.name} {s:%a %H:%M}–{e:%H:%M}")
    print(f"- pesados cruzando 04:50–05:10: {len(bad)}" + (" → " + "; ".join(sorted(set(bad))) if bad else ""))
    router = [j for j in jobs if "ROUTER" in j.res and j.kind == "puntual" and j.dur and not j.suspended
              and j.cron and j.name != DREAMING]
    for tag, mins in (("la ventana medida del clasificador (01:30–03:06)", 96),
                      (f"el peor caso acotado por la propuesta (01:30 + {DREAMING_SDS_S // 60} min de arranque + "
                       f"{DREAMING_DEADLINE_S // 60} min = 04:50)", (DREAMING_SDS_S + DREAMING_DEADLINE_S) / 60)):
        hits = []
        for j in router:
            for night, s, e in j.intervals(1):
                ws, we = local_iv(night, 1, 30, mins)
                ov = (min(e, we) - max(s, ws)).total_seconds() / 60
                if ov > 0:
                    hits.append(f"{j.name} {s:%H:%M} ({M.fm(min(ov, j.dur[1]))} min)")
        print(f"- one-shots de inferencia en {tag}: {len(set(hits))}"
              + (" → " + "; ".join(sorted(set(hits))) if hits else ""))
    print()


def report(inv, d0, label):
    set_week(d0)
    before, after = pairs(build(inv, False)), pairs(build(inv, True))
    rank = {"alta": 0, "media": 1, "baja": 2}

    def count(p):
        c = defaultdict(int)
        for v in p.values():
            c[v[2]] += 1
        return f"alta {c['alta']} · media {c['media']} · baja {c['baja']}"

    print(f"### {label}\n")
    print(f"- pares en conflicto ANTES: {count(before)} · DESPUÉS: {count(after)}\n")
    gone = [(k, before[k]) for k in before if k not in after or rank[after[k][2]] > rank[before[k][2]]]
    new = [(k, after[k]) for k in after if k not in before or rank[after[k][2]] < rank[before[k][2]]]
    for title, rows in (("Deshechos o rebajados (antes → después)", gone), ("Nuevos o agravados", new)):
        rows = [r for r in rows if r[1][2] != "baja" or title.startswith("Nuevos")]
        print(f"**{title}** ({len(rows)}; los que eran `baja` y desaparecen no se listan):\n")
        if not rows:
            print("ninguno\n")
            continue
        print("| recurso | par | antes | después |")
        print("|---|---|---|---|")
        for k, v in sorted(rows, key=lambda x: (rank[x[1][2]], x[0])):
            b, a = before.get(k), after.get(k)
            fb = f"{b[2]} {M.fm(b[0])}/{M.fm(b[1])} min" if b else "—"
            fa = f"{a[2]} {M.fm(a[0])}/{M.fm(a[1])} min ({M.fmt_nights(a[3])})" if a else "sin cruce"
            print(f"| {k[0]} | {k[1]} × {k[2]} | {fb} | {fa} |")
        print()
    left = sorted((k, v) for k, v in after.items() if v[2] != "baja")
    print(f"**Quedan en media o alta después** ({len(left)}):\n")
    print("| recurso | par | solape med/máx | noches |")
    print("|---|---|---|---|")
    for k, v in left:
        print(f"| {k[0]} | {k[1]} × {k[2]} | {v[2]} {M.fm(v[0])}/{M.fm(v[1])} min | {M.fmt_nights(v[3])} |")
    print()
    invariants(build(inv, True), label)


def expand_cronjobs():
    print("### Expansión con `cuenta_ventana.py` de cada horario de CronJob propuesto\n")
    items = []
    for name, (sched, tz, _) in PROPUESTA.items():
        if "/" not in name:
            continue
        ns, n = name.split("/", 1)
        items.append({"metadata": {"namespace": ns, "name": n}, "spec": {"schedule": sched, "timeZone": tz.key}})
    for label, d0 in (("verano", dt.date(2026, 9, 28)), ("invierno", dt.date(2026, 11, 2))):
        start = dt.datetime(d0.year, d0.month, d0.day, tzinfo=LOCAL)
        rows = analyse(items, dt.time(22), dt.time(8), start, 7)
        print(f"**{label}** (semana del {d0:%d-%m}):\n")
        print("| CronJob | schedule · timeZone | disparos en 22:00–08:00 (7 días) | horas locales en la ventana |")
        print("|---|---|---|---|")
        for r in rows:
            hrs = ", ".join(r["night_local"]) or "ninguna (fuera de la ventana a propósito)"
            print(f"| {r['ns']}/{r['name']} | `{r['schedule']}` · {r['tz']} | {r['night7d']} | {hrs} |")
        print()


def full_table(inv):
    print("### Tabla completa: una fila por cada fila del inventario, agrupada por repo dueño\n")
    repos = {}
    for line in open(inv, encoding="utf-8").read().splitlines()[2:]:
        if not line.strip():
            continue
        cells = line.strip().strip("|").split("|") if line.startswith("|") else line.split("|")
        cell = cells[7].strip()
        first = cell.split()[0].strip(",`") if cell else "—"
        if cell.startswith("sin repo"):
            first = "sin repo"
        elif first == "Ubuntu":
            first = "Ubuntu (paquetes del sistema)"
        repos[cells[0].strip()] = first
    groups = defaultdict(list)
    for j in M.load(inv):
        groups[repos[j.label]].append(j)
    for repo in sorted(groups):
        print(f"**{repo}**\n")
        print("| job | horario actual | propuesta |")
        print("|---|---|---|")
        for j in groups[repo]:
            if j.name in PROPUESTA:
                s, tz, _ = PROPUESTA[j.name]
                prop = f"**cambia** → `{s}` {tz.key} (ver tabla de cambios)"
            elif j.name == DREAMING:
                prop = ("**horario no cambia** (`30 1 * * *`); cambian `startingDeadlineSeconds` y "
                        "`activeDeadlineSeconds` (ver tabla de cambios)")
            elif j.kind == "fuera":
                prop = f"no cambia ({j.why})"
            elif j.suspended:
                prop = "no cambia (suspendido)"
            else:
                prop = "no cambia"
            print(f"| {j.label} | `{j.horario.strip('`')}` {j.tzcell} | {prop} |")
        print()


def main():
    inv = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "inventario.md")
    print("<!-- generado por verifica_propuesta.py -->\n")
    expand_cronjobs()
    report(inv, dt.date(2026, 9, 28), "Verano (CEST): noches del 28-09 al 04-10-2026")
    report(inv, dt.date(2026, 11, 2), "Invierno (CET): noches del 02-11 al 08-11-2026")
    full_table(inv)


if __name__ == "__main__":
    main()
