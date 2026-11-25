# Evidencia INFRA-1032 — rama INFRA-1032-cnpg-backup-guard

## Test que debía fallar antes (medido en vivo 2026-11-19, sesión devops)
- `kubectl get cronjob -n databases cnpg-scheduled-backup-guard` → `Error from server (NotFound)` (no existía)
- `kubectl get scheduledbackup -n databases postgres-shared-daily -o jsonpath='{.spec.schedule}'` → `0 0 3 * * *`
- `kubectl auth can-i --as=system:serviceaccount:databases:cnpg-scheduled-backup-guard list backups.postgresql.cnpg.io -n databases` → `no`

## Render (local, worktree sobre origin/main)
`kubectl kustomize databases/postgres-shared` → exit 0; en el render: CronJob `schedule: '*/15 * * * *'` y ScheduledBackup `schedule: 0 0 5 * * *`.

## Simulación del script del job (mismo código extraído del manifiesto, kubectl stub con fixtures)
Fixtures: walArchivingFailing de 40 min, failed de 20 min, failed de 5 min (no tocar), completed de hace 3 días, running de hoy, guard-retry de 8 días, cluster b completed hoy, cluster c con 4 intentos hoy. Salida:
```
GUARD: deleted stuck backup postgres-d-stuck30
GUARD: deleted stuck backup postgres-d-fail20
GUARD: deleted stuck backup guard-retry-postgres-shared-nvme-202611110300
GUARD: cluster postgres-b already completed today, nothing to do
GUARD: cluster postgres-c has 4 attempts today, not retrying
GUARD: created guard-retry-postgres-shared-nvme-202611190336 (cluster postgres-shared-nvme, attempts today before this one: 2)
```
El Backup creado lleva `cnpg.io/guard-retry: "true"`, SIN `cnpg.io/scheduled-backup`, `spec: {method: barmanObjectStore, cluster: {name: ...}}`.

## Criterios
- C1: por medir tras el merge (ArgoCD `k8s-infra` Synced con el commit).
- C2: `*/15 * * * *` verificado en el render; a medir en vivo tras el sync.
- C3: `0 0 5 * * *` verificado en el render; a medir en vivo tras el sync.
- C4: simulación de arriba (no solo render: el código real del args del CronJob ejecutado contra fixtures). En vivo quedará en los logs del primer job y en el siguiente atasco real (walArchivingFailing/failed recurrentes; hoy 19-11 el backup de las 03:00 quedó `running`).
- C5: RBAC namespaced (Role en databases, verbs get,list,create,delete sobre backups de postgresql.cnpg.io); `auth can-i` a medir en vivo tras el sync.

## Atajo conocido
`date -u -d "@epoch"` (busybox) no pudo probarse en un pod efímero (creación de pods imperativa negada al rol); es comportamiento documentado de busybox y lo confirmará el log del primer job del CronJob.
