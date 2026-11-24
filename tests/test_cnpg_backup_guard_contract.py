"""SC-6476 / INFRA-1555: contract of the CNPG backup guard
(databases/postgres-shared/stuck-backup-guard.yaml).

El 24-11-2026 el daily de postgres-shared-nvme falló a las 09:06 (el rollout de SC-6471 mató el
instance manager que lo ejecutaba); la guardia borró el Backup failed a las 09:15 y no creó ningún
retry: su bucle nacía de los Backup vivos de hoy, y el único había desaparecido por su propio
housekeeping. PostgresSharedBackupStale tardó 6 h más en avisar.

INFRA-1555 (SC-5617): el CronJob */15 pasó a un Deployment-informer de backups.postgresql.cnpg.io
con un bucle level-triggered (evento del watch o event.wait(deadline) absoluto). El test EXTRAE el
guard.py real del ConfigMap (PyYAML), lo importa y ejercita reconcile() end-to-end con reloj fijo al
2026-11-24T10:00:00Z (la hora real del incidente) sobre fixtures, y prueba los MISMOS invariantes:

* el hueco cerrado: daily failed de hoy -> se borra Y se crea su retry en la misma pasada;
* catch-up: ScheduledBackup disparó hace >15 min sin ningún Backup de hoy -> se crea el retry;
* SC-6103 intacto: completed de hoy -> nada; en curso hoy -> nada; disparó hace <15 min -> nada;
* tope de intentos: 4 guard-retry fallados de hoy (conservados, no borrados) -> no se crea el 5º;
* housekeeping: el failed de ayer sí se borra (solo los de hoy son memoria de intentos);
* RBAC: el Role da get/list/watch sobre scheduledbackups y backups (sin update/patch);
* informer: Deployment replicas 1 Recreate; el reloj diario existe; el */15 ya no;
* umbrales por evento: failed <15 min arma deadline absoluto, failed >15 min borra en el acto,
  un retry de hoy no arma reloj que se rearma solo.
"""

import importlib.util
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD = ROOT / "databases" / "postgres-shared" / "stuck-backup-guard.yaml"

# Reloj fijo: el tick de las 10:00 del 24-11, con el daily fallido a las 09:06 y nacido a las 05:00.
NOW_EPOCH = int(datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc).timestamp())
TODAY = "2026-11-24"
DAILY_0500 = "2026-11-24T05:00:00Z"
FIRED_0500 = DAILY_0500          # ScheduledBackup disparó hoy a las 05:00
RECENT_0955 = "2026-11-24T09:55:00Z"  # disparó hace 5 min: ventana de carrera SC-6103


def _docs():
    return [d for d in yaml.safe_load_all(GUARD.read_text()) if d]


def _guard_module():
    """Importa el guard.py real del ConfigMap (main() no corre: va bajo __name__)."""
    cm = next(d for d in _docs() if d.get("kind") == "ConfigMap"
              and d["metadata"]["name"] == "cnpg-backup-guard")
    src = cm["data"]["guard.py"]
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp, "guard.py")
        p.write_text(src)
        spec = importlib.util.spec_from_file_location("cnpg_guard", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


G = _guard_module()


def _row(name, cluster, phase, created):
    ce = G.epoch(created) if created else 0.0
    return {"name": name, "cluster": cluster, "phase": phase, "created": created,
            "ce": ce, "day": created[:10]}


def _sb(cluster, last):
    le = G.epoch(last) if last else 0.0
    return {"cluster": cluster, "last": last, "le": le, "day": last[:10]}


def run_guard(children=(), retries=(), scheduled=()):
    """reconcile() real con reloj fijo; devuelve (deletes, creates-nombres, out-no-usado)."""
    rows = [_row(n, c, p, t) for (n, c, p, t) in list(children) + list(retries)]
    sched = [_sb(c, t) for (c, t) in scheduled]
    deletes, creates, deadline = G.reconcile(rows, sched, NOW_EPOCH, TODAY)
    return deletes, [c[1] for c in creates], deadline


class TestGuardManifest(unittest.TestCase):
    def test_role_verbs(self):
        """RBAC: watch para el informer; get/list/create/delete en backups; SIN update/patch
        (fuerza no tocar ScheduledBackup.lastScheduleTime). scheduledbackups get/list/watch."""
        role = next(d for d in _docs() if d.get("kind") == "Role")
        rules = {tuple(sorted(r["resources"])): sorted(r["verbs"]) for r in role["rules"]}
        self.assertEqual(rules.get(("backups",)), ["create", "delete", "get", "list", "watch"])
        self.assertEqual(rules.get(("scheduledbackups",)), ["get", "list", "watch"])
        for verbs in rules.values():
            self.assertNotIn("update", verbs)
            self.assertNotIn("patch", verbs)

    def test_informer_deployment_single_recreate(self):
        """SC-6103: un solo watcher (replicas 1, Recreate) evita dos retries en paralelo."""
        dep = next(d for d in _docs() if d.get("kind") == "Deployment")
        self.assertEqual(dep["spec"]["replicas"], 1)
        self.assertEqual(dep["spec"]["strategy"]["type"], "Recreate")

    def test_daily_clock_exists_and_quarter_gone(self):
        """Queda UN reloj diario (agregación + red de vida); el */15 muere (SC-5617)."""
        crons = [d for d in _docs() if d.get("kind") == "CronJob"]
        names = {c["metadata"]["name"] for c in crons}
        self.assertIn("cnpg-backup-guard-daily", names)
        self.assertNotIn("cnpg-scheduled-backup-guard", names)
        daily = next(c for c in crons if c["metadata"]["name"] == "cnpg-backup-guard-daily")
        self.assertEqual(daily["spec"]["schedule"], "0 12 * * *")
        cmd = daily["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["command"]
        self.assertIn("--daily", cmd)

    def test_guard_py_compiles(self):
        cm = next(d for d in _docs() if d.get("kind") == "ConfigMap"
                  and d["metadata"]["name"] == "cnpg-backup-guard")
        compile(cm["data"]["guard.py"], "guard.py", "exec")


class TestGuardBehaviour(unittest.TestCase):
    def test_s6476_failed_daily_deleted_and_retried_same_tick(self):
        """El caso del 24-11: daily failed nacido 05:00 -> borrado Y retry 202611241000 creado."""
        deleted, applied, _ = run_guard(
            children=[("postgres-shared-daily-20261124050000", "postgres-shared-nvme", "failed", DAILY_0500)],
            scheduled=[("postgres-shared-nvme", FIRED_0500)],
        )
        self.assertEqual(deleted, ["postgres-shared-daily-20261124050000"])
        self.assertEqual(applied, ["guard-retry-postgres-shared-nvme-202611241000"])

    def test_catchup_scheduled_fired_no_backup_object(self):
        """Disparó a las 05:00 y no hay ningún Backup (operador caído al nacer el daily): se crea."""
        deleted, applied, _ = run_guard(scheduled=[("postgres-shared-nvme", FIRED_0500)])
        self.assertEqual(deleted, [])
        self.assertEqual(applied, ["guard-retry-postgres-shared-nvme-202611241000"])

    def test_completed_today_noop(self):
        deleted, applied, _ = run_guard(
            children=[("postgres-shared-daily-20261124050000", "postgres-shared-nvme", "completed", DAILY_0500)],
            scheduled=[("postgres-shared-nvme", FIRED_0500)],
        )
        self.assertEqual((deleted, applied), ([], []))

    def test_in_progress_today_noop_sc6103(self):
        deleted, applied, _ = run_guard(
            children=[("postgres-shared-daily-20261124050000", "postgres-shared-nvme", "running", DAILY_0500)],
            scheduled=[("postgres-shared-nvme", FIRED_0500)],
        )
        self.assertEqual((deleted, applied), ([], []))

    def test_wedged_retry_today_survives_and_blocks_no_storm(self):
        """SC-6103: un retry de hoy enquistado en walArchivingFailing se conserva (no se borra),
        no genera otro retry ese día y deja que lo cace PostgresSharedBackupStale."""
        deleted, applied, _ = run_guard(
            retries=[("guard-retry-postgres-shared-nvme-202611240900", "postgres-shared-nvme",
                      "walArchivingFailing", "2026-11-24T09:00:00Z")],
            scheduled=[("postgres-shared-nvme", FIRED_0500)],
        )
        self.assertEqual(deleted, [])
        self.assertEqual(applied, [])

    def test_race_guard_fired_less_than_15min(self):
        """SC-6103: disparó a las 09:55 (tick 10:00, hijo aún no creado): no se crea nada."""
        deleted, applied, _ = run_guard(scheduled=[("postgres-shared-nvme", RECENT_0955)])
        self.assertEqual((deleted, applied), ([], []))

    def test_attempts_cap_four_and_today_retries_survive(self):
        """4 retries fallados de hoy (06:15-09:15): conservados por la regla de atascos y no hay quinto."""
        retries = [
            ("guard-retry-postgres-shared-nvme-2026112%02d15" % h, "postgres-shared-nvme",
             "failed", "2026-11-24T%02d:15:00Z" % h)
            for h in (6, 7, 8, 9)
        ]
        deleted, applied, _ = run_guard(retries=retries, scheduled=[("postgres-shared-nvme", FIRED_0500)])
        self.assertEqual(deleted, [])
        self.assertEqual(applied, [])

    def test_yesterday_failed_retry_is_housekept(self):
        """El failed de ayer sí se borra: solo los nacidos hoy son memoria de intentos."""
        deleted, applied, _ = run_guard(
            retries=[("guard-retry-postgres-shared-nvme-202611230515", "postgres-shared-nvme",
                      "failed", "2026-11-23T05:15:00Z")],
            scheduled=[("postgres-shared-nvme", "2026-11-23T05:00:00Z")],
        )
        self.assertEqual(deleted, ["guard-retry-postgres-shared-nvme-202611230515"])
        self.assertEqual(applied, [])


class TestGuardEventThresholds(unittest.TestCase):
    """INFRA-1555: los umbrales 15/30 min se resuelven por evento + deadline absoluto, sin sondeo."""

    def test_failed_over_15min_deleted_no_deadline(self):
        rows = [_row("daily-old", "cl", "failed", "2026-11-24T09:00:00Z")]  # 60 min > 15
        d, c, dl = G.reconcile(rows, [], NOW_EPOCH, TODAY)
        self.assertEqual(d, ["daily-old"])
        self.assertIsNone(dl)

    def test_failed_under_15min_arms_absolute_deadline(self):
        created = "2026-11-24T09:55:00Z"  # 5 min de vida
        rows = [_row("daily-new", "cl", "failed", created)]
        d, c, dl = G.reconcile(rows, [], NOW_EPOCH, TODAY)
        self.assertEqual(d, [])
        self.assertAlmostEqual(dl, G.epoch(created) + 900, delta=1)

    def test_walfail_under_30min_arms_absolute_deadline(self):
        created = "2026-11-24T09:40:00Z"  # 20 min de vida
        rows = [_row("w-new", "cl", "walArchivingFailing", created)]
        d, c, dl = G.reconcile(rows, [], NOW_EPOCH, TODAY)
        self.assertEqual(d, [])
        self.assertAlmostEqual(dl, G.epoch(created) + 1800, delta=1)

    def test_retry_today_does_not_arm_self_rearming_clock(self):
        """Un retry de hoy failed no es borrable: no arma deadline (sería un reloj que se rearma)."""
        rows = [_row("guard-retry-cl-x", "cl", "failed", "2026-11-24T09:55:00Z")]
        d, c, dl = G.reconcile(rows, [], NOW_EPOCH, TODAY)
        self.assertEqual(d, [])
        self.assertIsNone(dl)


if __name__ == "__main__":
    unittest.main()
