"""SC-6476: contract of the CNPG backup guard (databases/postgres-shared/stuck-backup-guard.yaml).

El 24-11-2026 el daily de postgres-shared-nvme falló a las 09:06 (el rollout de SC-6471 mató el
instance manager que lo ejecutaba); la guardia borró el Backup failed a las 09:15 y no creó ningún
retry: su bucle nacía de los Backup vivos de hoy, y el único había desaparecido por su propio
housekeeping. PostgresSharedBackupStale tardó 6 h más en avisar.

El test EXTRAE el script real del CronJob (PyYAML) y lo ejecuta end-to-end con `date` y `kubectl`
de pega (reloj fijo al 2026-11-24T10:00:00Z, la hora real del incidente) sobre fixtures, y prueba:

* el hueco cerrado: daily failed de hoy -> se borra Y se crea su retry en el mismo tick;
* catch-up: ScheduledBackup disparó hace >15 min sin ningún Backup de hoy -> se crea el retry;
* SC-6103 intacto: completed de hoy -> nada; en curso hoy -> nada; disparó hace <15 min -> nada;
* tope de intentos: 4 guard-retry fallados de hoy (conservados, no borrados) -> no se crea el 5º;
* housekeeping: el failed de ayer sí se borra (solo los de hoy son memoria de intentos);
* RBAC: el Role da get/list sobre scheduledbackups (sin eso el catch-up sería sordo).
"""

import os
import pathlib
import stat
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
GUARD = ROOT / "databases" / "postgres-shared" / "stuck-backup-guard.yaml"

# Reloj fijo: el tick de las 10:00 del 24-11, con el daily fallido a las 09:06 y nacido a las 05:00.
NOW_EPOCH = int(datetime(2026, 11, 24, 10, 0, 0, tzinfo=timezone.utc).timestamp())
DAILY_0500 = "2026-11-24T05:00:00Z"
FIRED_0500 = DAILY_0500          # ScheduledBackup disparó hoy a las 05:00
RECENT_0955 = "2026-11-24T09:55:00Z"  # disparó hace 5 min: ventana de carrera SC-6103


def guard_script():
    docs = [d for d in yaml.safe_load_all(GUARD.read_text()) if d]
    cron = next(d for d in docs if d.get("kind") == "CronJob")
    return cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]["args"][0]


DATE_STUB = """#!/bin/sh
# date de pega con reloj fijo en $NOW_EPOCH (solo los usos del script).
fmt=""
epoch="$NOW_EPOCH"
while [ "$#" -gt 0 ]; do
  case "$1" in
    -u) ;;
    -d) epoch="${2#@}"; shift ;;
    +*) fmt="${1#+}" ;;
  esac
  shift
done
[ "$fmt" = "%s" ] && { echo "$epoch"; exit 0; }
python3 -c "import datetime,sys; print(datetime.datetime.fromtimestamp(int(sys.argv[1]), datetime.timezone.utc).strftime(sys.argv[2]))" "$epoch" "$fmt"
"""

KUBECTL_STUB = """#!/bin/sh
# kubectl de pega: sirve fixtures y registra borrados/aplicados en $STATE.
case " $* " in
  *" scheduledbackups.postgresql.cnpg.io "*) cat "$FIX_SCHEDULED"; exit 0 ;;
esac
if [ "$1" = "delete" ]; then
  shift
  for a in "$@"; do
    case "$a" in
      backups.postgresql.cnpg.io|-n|databases|--wait=false) continue ;;
      *) echo "$a" >> "$STATE/deleted"; break ;;
    esac
  done
  exit 0
fi
if [ "$1" = "apply" ]; then
  sed -n 's/^  name: //p' >> "$STATE/applied"
  exit 0
fi
if [ "$1" = "get" ]; then
  selector=""
  prev=""
  for a in "$@"; do
    [ "$prev" = "-l" ] && selector="$a"
    prev="$a"
  done
  case "$selector" in
    cnpg.io/scheduled-backup) src="$FIX_CHILD" ;;
    cnpg.io/guard-retry=true) src="$FIX_RETRY" ;;
    *) exit 1 ;;
  esac
  while read -r name cluster phase created; do
    [ -n "$name" ] || continue
    if [ -f "$STATE/deleted" ] && grep -qx "$name" "$STATE/deleted"; then continue; fi
    echo "$name $cluster $phase $created"
  done < "$src"
  exit 0
fi
echo "stub kubectl: args no previstos: $*" >&2
exit 1
"""


def run_guard(fix_child=(), fix_retry=(), fix_scheduled=()):
    """Ejecuta el script real del CronJob con reloj y kubectl simulados."""
    with tempfile.TemporaryDirectory() as tmp:
        state = pathlib.Path(tmp, "state")
        state.mkdir()
        bin_dir = pathlib.Path(tmp, "bin")
        bin_dir.mkdir()
        for name, body in (("kubectl", KUBECTL_STUB), ("date", DATE_STUB)):
            stub = bin_dir / name
            stub.write_text(body)
            stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        paths = {}
        for key, lines in (("child", fix_child), ("retry", fix_retry), ("scheduled", fix_scheduled)):
            p = pathlib.Path(tmp, key)
            p.write_text("".join(f"{line}\n" for line in lines))
            paths[key.upper()] = str(p)
        env = dict(os.environ, STATE=str(state), NOW_EPOCH=str(NOW_EPOCH),
                   FIX_CHILD=paths["CHILD"], FIX_RETRY=paths["RETRY"],
                   FIX_SCHEDULED=paths["SCHEDULED"],
                   PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        proc = subprocess.run(["/bin/sh", "-c", guard_script()], env=env,
                              capture_output=True, text=True, timeout=60)
        read = lambda n: (state / n).read_text().split() if (state / n).exists() else []
        return proc.returncode, proc.stdout + proc.stderr, read("deleted"), read("applied")


class TestGuardManifest(unittest.TestCase):
    def test_role_can_read_scheduledbackups(self):
        """SC-6476: el catch-up lee ScheduledBackup; sin get/list el script quedaría sordo."""
        docs = [d for d in yaml.safe_load_all(GUARD.read_text()) if d]
        role = next(d for d in docs if d.get("kind") == "Role")
        rules = {tuple(sorted(r["resources"])): sorted(r["verbs"]) for r in role["rules"]}
        self.assertEqual(rules.get(("scheduledbackups",)), ["get", "list"])

    def test_script_parses(self):
        proc = subprocess.run(["/bin/sh", "-n", "-c", guard_script()], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)


class TestGuardBehaviour(unittest.TestCase):
    def test_s6476_failed_daily_deleted_and_retried_same_tick(self):
        """El caso del 24-11: daily failed nacido 05:00 -> borrado Y retry 202611241000 creado."""
        rc, out, deleted, applied = run_guard(
            fix_child=[f"postgres-shared-daily-20261124050000 postgres-shared-nvme failed {DAILY_0500}"],
            fix_scheduled=[f"postgres-shared-nvme {FIRED_0500}"],
        )
        self.assertEqual(rc, 0, out)
        self.assertEqual(deleted, ["postgres-shared-daily-20261124050000"])
        self.assertEqual(applied, ["guard-retry-postgres-shared-nvme-202611241000"], out)

    def test_catchup_scheduled_fired_no_backup_object(self):
        """Disparó a las 05:00 y no hay ningún Backup (operador caído al nacer el daily): se crea."""
        rc, out, deleted, applied = run_guard(fix_scheduled=[f"postgres-shared-nvme {FIRED_0500}"])
        self.assertEqual(rc, 0, out)
        self.assertEqual(deleted, [])
        self.assertEqual(applied, ["guard-retry-postgres-shared-nvme-202611241000"], out)

    def test_completed_today_noop(self):
        rc, out, deleted, applied = run_guard(
            fix_child=[f"postgres-shared-daily-20261124050000 postgres-shared-nvme completed {DAILY_0500}"],
            fix_scheduled=[f"postgres-shared-nvme {FIRED_0500}"],
        )
        self.assertEqual(rc, 0, out)
        self.assertEqual((deleted, applied), ([], []))
        self.assertIn("already completed today", out)

    def test_in_progress_today_noop_sc6103(self):
        rc, out, deleted, applied = run_guard(
            fix_child=[f"postgres-shared-daily-20261124050000 postgres-shared-nvme running {DAILY_0500}"],
            fix_scheduled=[f"postgres-shared-nvme {FIRED_0500}"],
        )
        self.assertEqual(rc, 0, out)
        self.assertEqual((deleted, applied), ([], []))
        self.assertIn("in progress or wedged today", out)

    def test_wedged_retry_today_survives_and_blocks_no_storm(self):
        """SC-6103: un retry de hoy enquistado en walArchivingFailing se conserva (no se borra),
        no genera otro retry ese día y deja que lo cace PostgresSharedBackupStale."""
        rc, out, deleted, applied = run_guard(
            fix_retry=["guard-retry-postgres-shared-nvme-202611240900 postgres-shared-nvme walArchivingFailing 2026-11-24T09:00:00Z"],
            fix_scheduled=[f"postgres-shared-nvme {FIRED_0500}"],
        )
        self.assertEqual(rc, 0, out)
        self.assertEqual(deleted, [], out)
        self.assertEqual(applied, [], out)
        self.assertIn("in progress or wedged today", out)

    def test_race_guard_fired_less_than_15min(self):
        """SC-6103: disparó a las 09:55 (tick 10:00, hijo aún no creado): no se crea nada."""
        rc, out, deleted, applied = run_guard(fix_scheduled=[f"postgres-shared-nvme {RECENT_0955}"])
        self.assertEqual(rc, 0, out)
        self.assertEqual((deleted, applied), ([], []))

    def test_attempts_cap_four_and_today_retries_survive(self):
        """4 retries fallados de hoy (06:15-09:15): conservados por la regla de atascos y no hay quinto."""
        retries = [
            f"guard-retry-postgres-shared-nvme-2026112{h:02}15 postgres-shared-nvme failed 2026-11-24T{h:02}:15:00Z"
            for h in (6, 7, 8, 9)
        ]
        rc, out, deleted, applied = run_guard(
            fix_retry=retries,
            fix_scheduled=[f"postgres-shared-nvme {FIRED_0500}"],
        )
        self.assertEqual(rc, 0, out)
        self.assertEqual(deleted, [], out)
        self.assertEqual(applied, [], out)
        self.assertIn("not retrying", out)

    def test_yesterday_failed_retry_is_housekept(self):
        """El failed de ayer sí se borra: solo los nacidos hoy son memoria de intentos."""
        rc, out, deleted, applied = run_guard(
            fix_retry=["guard-retry-postgres-shared-nvme-202611230515 postgres-shared-nvme failed 2026-11-23T05:15:00Z"],
            fix_scheduled=["postgres-shared-nvme 2026-11-23T05:00:00Z"],
        )
        self.assertEqual(rc, 0, out)
        self.assertEqual(deleted, ["guard-retry-postgres-shared-nvme-202611230515"])
        self.assertEqual(applied, [], out)


if __name__ == "__main__":
    unittest.main()
