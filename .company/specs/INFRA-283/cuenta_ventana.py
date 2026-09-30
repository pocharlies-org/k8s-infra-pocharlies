#!/usr/bin/env python3
"""cuenta_ventana.py — INFRA-283 H1 (INFRA-336): qué CronJobs disparan de noche.

Lee `kubectl get cronjobs -A -o json` (stdin o fichero como primer argumento),
expande cada `spec.schedule` sobre 7 días en hora local Europe/Madrid y marca
los que tienen al menos un disparo dentro de la ventana 22:00–08:00.

Zona horaria de cada CronJob:
  - `spec.timeZone` si existe;
  - prefijo `CRON_TZ=`/`TZ=` en el schedule si existe;
  - si no, la del kube-controller-manager (UTC en este cluster: comprobado
    contra `status.lastScheduleTime`, ver `--check-last`).

Sin dependencias fuera de la stdlib (zoneinfo, Python >= 3.9).

Uso:
  kubectl get cronjobs -A -o json | python3 cuenta_ventana.py            # conteo
  kubectl get cronjobs -A -o json | python3 cuenta_ventana.py --list     # TSV de la ventana
  kubectl get cronjobs -A -o json | python3 cuenta_ventana.py --all      # TSV de todos
  kubectl get cronjobs -A -o json | python3 cuenta_ventana.py --check-last  # TZ vs lastScheduleTime
Opciones: --start HH:MM --end HH:MM (ventana, por defecto 22:00 y 08:00),
          --days N (horizonte, 7), --from YYYY-MM-DD (lunes de referencia; por defecto
          el lunes de la semana en curso en Europe/Madrid).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("Europe/Madrid")
CONTROLLER_TZ = "UTC"  # zona del kube-controller-manager si el CronJob no declara ninguna

MACROS = {
    "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}
DOWS = {d: i for i, d in enumerate("sun mon tue wed thu fri sat".split())}


def _field(expr: str, lo: int, hi: int, names: dict | None = None) -> tuple[set[int], bool]:
    """Devuelve (valores, restringido). `restringido` es False para '*' / '?'."""
    out: set[int] = set()
    star = expr in ("*", "?")
    for part in expr.split(","):
        step = 1
        if "/" in part:
            part, s = part.split("/", 1)
            step = int(s)
        if part in ("*", "?"):
            a, b = lo, hi
        elif "-" in part:
            a_s, b_s = part.split("-", 1)
            a, b = _val(a_s, names), _val(b_s, names)
        else:
            a = _val(part, names)
            b = hi if step != 1 else a
        out.update(range(a, b + 1, step))
    if hi == 7:  # día de la semana: 7 == domingo
        out = {0 if v == 7 else v for v in out}
    return out, not star


def _val(s: str, names: dict | None) -> int:
    s = s.strip().lower()
    if names and s[:3] in names:
        return names[s[:3]]
    return int(s)


class Cron:
    def __init__(self, schedule: str):
        s = schedule.strip()
        self.tz: str | None = None
        if s.startswith(("CRON_TZ=", "TZ=")):
            head, s = s.split(None, 1)
            self.tz = head.split("=", 1)[1]
        s = MACROS.get(s, s)
        f = s.split()
        if len(f) != 5:
            raise ValueError(f"schedule no soportado: {schedule!r}")
        self.minute, _ = _field(f[0], 0, 59)
        self.hour, _ = _field(f[1], 0, 23)
        self.dom, self.dom_r = _field(f[2], 1, 31)
        self.month, _ = _field(f[3], 1, 12, MONTHS)
        self.dow, self.dow_r = _field(f[4], 0, 7, DOWS)

    def day_matches(self, d: dt.date) -> bool:
        if d.month not in self.month:
            return False
        cron_dow = (d.weekday() + 1) % 7  # python lun=0 → cron dom=0
        in_dom, in_dow = d.day in self.dom, cron_dow in self.dow
        if self.dom_r and self.dow_r:  # semántica Vixie/robfig: OR si ambos restringidos
            return in_dom or in_dow
        return in_dom and in_dow

    def fires(self, start: dt.datetime, end: dt.datetime, tz: ZoneInfo):
        """Disparos (aware, en `tz`) en [start, end)."""
        day = start.astimezone(tz).date() - dt.timedelta(days=1)
        last = end.astimezone(tz).date() + dt.timedelta(days=1)
        while day <= last:
            if self.day_matches(day):
                for h in sorted(self.hour):
                    for m in sorted(self.minute):
                        t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
                        # descarta horas inexistentes (salto de primavera)
                        if t.astimezone(dt.timezone.utc).astimezone(tz).replace(tzinfo=None) != t.replace(tzinfo=None):
                            continue
                        if start <= t < end:
                            yield t
            day += dt.timedelta(days=1)


def in_window(t: dt.datetime, ws: dt.time, we: dt.time) -> bool:
    lt = t.astimezone(LOCAL).time()
    if ws <= we:
        return ws <= lt < we
    return lt >= ws or lt < we


def analyse(items, ws, we, start, days):
    end = start + dt.timedelta(days=days)
    rows = []
    for it in items:
        md, sp = it["metadata"], it["spec"]
        cron = Cron(sp["schedule"])
        tzname = sp.get("timeZone") or cron.tz
        tz = ZoneInfo(tzname or CONTROLLER_TZ)
        fires = list(cron.fires(start, end, tz))
        night = [t.astimezone(LOCAL) for t in fires if in_window(t, ws, we)]
        rows.append({
            "ns": md["namespace"], "name": md["name"], "schedule": sp["schedule"],
            "tz": tzname or "(sin campo→UTC)", "suspend": bool(sp.get("suspend")),
            "sds": sp.get("startingDeadlineSeconds"),
            "fires7d": len(fires), "night7d": len(night),
            "night_local": sorted({t.strftime("%H:%M") for t in night}),
            "night_days": sorted({t.strftime("%a") for t in night},
                                 key="Mon Tue Wed Thu Fri Sat Sun".split().index),
            "last": (it.get("status") or {}).get("lastScheduleTime"),
            "cron": cron, "tzobj": tz,
        })
    return rows


def check_last(rows):
    """¿El lastScheduleTime cae en un disparo del schedule leído en su TZ?"""
    ok = bad = none = 0
    for r in rows:
        if not r["last"]:
            none += 1
            continue
        t = dt.datetime.fromisoformat(r["last"].replace("Z", "+00:00"))
        hits = list(r["cron"].fires(t - dt.timedelta(seconds=1), t + dt.timedelta(seconds=1), r["tzobj"]))
        if hits:
            ok += 1
        else:
            bad += 1
            print(f"NO CASA\t{r['ns']}/{r['name']}\t{r['schedule']}\t{r['tz']}\tlast={r['last']}")
    print(f"lastScheduleTime casa con el schedule en su TZ: {ok} · no casa: {bad} · sin lastScheduleTime: {none}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", nargs="?", help="JSON de kubectl (por defecto stdin)")
    ap.add_argument("--start", default="22:00")
    ap.add_argument("--end", default="08:00")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--from", dest="frm")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--list", action="store_true")
    g.add_argument("--all", action="store_true")
    g.add_argument("--check-last", action="store_true")
    a = ap.parse_args()

    data = json.load(open(a.file) if a.file else sys.stdin)
    items = data["items"] if "items" in data else [data]
    ws, we = dt.time.fromisoformat(a.start), dt.time.fromisoformat(a.end)
    if a.frm:
        d0 = dt.date.fromisoformat(a.frm)
    else:
        today = dt.datetime.now(LOCAL).date()
        d0 = today - dt.timedelta(days=today.weekday())
    start = dt.datetime(d0.year, d0.month, d0.day, tzinfo=LOCAL)
    rows = analyse(items, ws, we, start, a.days)
    night = [r for r in rows if r["night7d"]]

    if a.check_last:
        check_last(rows)
        return
    if a.list or a.all:
        print("ns\tname\tschedule\ttimeZone\tsuspend\tstartingDeadlineSeconds\tdisparos_7d\tnocturnos_7d\thoras_locales\tdias")
        for r in sorted(rows if a.all else night, key=lambda r: (r["night_local"][:1] or ["99"], r["ns"], r["name"])):
            print("\t".join(str(x) for x in (
                r["ns"], r["name"], r["schedule"], r["tz"], r["suspend"], r["sds"],
                r["fires7d"], r["night7d"], ",".join(r["night_local"]), ",".join(r["night_days"]))))
        return
    susp = sum(r["suspend"] for r in night)
    print(f"CronJobs totales: {len(rows)}")
    print(f"En ventana {a.start}-{a.end} Europe/Madrid (7 días desde {d0}): {len(night)}"
          f" (activos {len(night) - susp}, suspendidos {susp})")
    print(f"Disparos nocturnos en 7 días: {sum(r['night7d'] for r in night)}")


if __name__ == "__main__":
    main()
