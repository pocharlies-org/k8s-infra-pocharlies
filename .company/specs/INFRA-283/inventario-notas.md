# INFRA-283 H1 (INFRA-336) — notas del inventario nocturno

Medido el **30-09-2026 entre las 12:40 y las 13:10 CEST** por `sre`, solo lectura: `kubectl get/describe/logs`,
consultas a VictoriaMetrics por el proxy del API server, `systemctl list-timers`, `journalctl` (grupo `adm`,
sin sudo), `/var/log/syslog`, logs bajo `~/logs` y `hermes` dentro del pod en modo lectura. Nada se ha
aplicado, escalado ni suspendido.

`inventario.md` es una sola tabla: 94 filas de CronJobs (empiezan por `|`) y después las filas del x86, de
Hermes y del informe del VP (sin `|` inicial). Así el `grep -c '^|'` de C1 cuenta solo CronJobs y el `awk` de
C2 no tropieza con texto suelto. Por esa misma razón el método va en este fichero y no en `inventario.md`.

## Cómo se reproduce

```sh
export KUBECONFIG=/home/dibanez/.kube/config
kubectl get cronjobs -A -o json | python3 .company/specs/INFRA-283/cuenta_ventana.py            # conteo (C1)
kubectl get cronjobs -A -o json | python3 .company/specs/INFRA-283/cuenta_ventana.py --list     # TSV de la ventana
kubectl get cronjobs -A -o json | python3 .company/specs/INFRA-283/cuenta_ventana.py --check-last  # TZ contra lastScheduleTime
```

`cuenta_ventana.py` solo usa la stdlib. Expande cada `schedule` sobre la semana en curso (de lunes a lunes)
en Europe/Madrid, toma `spec.timeZone` si existe (o `CRON_TZ=`) y, si no, UTC, que es la zona del
controller. Aplica la semántica OR de dom/dow de cron. Su conteo coincide con `croniter`: 94 y 94.

## Re-validación de la base del 29-09

| dato | base 29-09 | 30-09 | nota |
|---|---|---|---|
| CronJobs totales | 121 | 121 | = |
| en ventana 22:00–08:00 | 96 | **94** (87 activos + 7 suspendidos) | ±2, dentro de la tolerancia de C1 |
| timeZone (total) | 61 Madrid / 22 UTC / 38 sin campo | 61 / 22 / 38 | = |
| sin campo → UTC | 0 discrepancias | `--check-last`: 117 casan, 0 no casan, 4 sin `lastScheduleTime` | = |
| concurrencyPolicy | todos Forbid | 121 Forbid | = |
| suspendidos | 10 | 10 (7 en ventana) | = |
| en ventana sin `startingDeadlineSeconds` | 19 | **18** (todos activos) | ver lista abajo |
| repo dueño (grep `kind: CronJob`, ficheros) | skirmbooks 17, dgx-infra 15, brain 10, label 9, synapse 5, observability 5, infra 4, litellm 3 | = (mismos ficheros) | el grep cuenta ficheros; lo vivo por ArgoCD va abajo |

## Fuentes de la duración real y sus límites

- **Jobs vivos** (`kubectl get jobs -A`): `startTime` → `completionTime`, o la condición `Failed`. Por
  `successfulJobsHistoryLimit` y `ttlSecondsAfterFinished` quedan de 1 a 5 ejecuciones por CronJob.
- **VictoriaMetrics** (`kube_job_status_start_time` / `completion_time` / `kube_job_owner` / `kube_pod_info`):
  la **retención es de 48 h** (`vmsingle.spec.retentionPeriod`), así que solo añade las dos últimas noches.
  Sirve sobre todo para los jobs de alta frecuencia con TTL corto. No hay más historia en el cluster.
- Por eso las filas diarias llevan `n` pequeño (3–5 noches). El rango de fechas va en cada celda.
  «nocturnas» = ejecuciones que arrancaron entre las 22:00 y las 08:00. Si no hay ninguna retenida, se usan las
  diurnas y la celda lo dice.
- **x86**: journal desde el 29-09 01:13 (sistema) y 02:31 (user). Las semanales salen de `/var/log/syslog*`
  y el backup de `~/logs/backup-x86.log` (14 noches con «Duration:»).
- **Hermes**: tabla `executions` de `cron/executions.db`, del global y de cada perfil. Sus marcas de tiempo
  son hora local etiquetada como UTC. Las duraciones no se ven afectadas; las fechas de las celdas están
  corregidas.
- **Sin historial**: 8 CronJobs (6 suspendidos y 2 mensuales, `sii-monthly-report` y
  `skirmbooks-inventory-snapshot`) y 8 filas del x86/VP (crons sin log de fin, unidades retiradas o
  desactivadas, el VP). Cada una lleva su motivo. El séptimo suspendido de la ventana,
  `rag-competitor-llm-matcher`, sí conserva sus Jobs del 19–21-08.

## Resúmenes para H2/H3

- **Nodo principal por CronJob de la ventana**: ks5-cp-3 49 · sauvage 22 · ubuntu (x86) 12 · sin pods medidos
  11 (7 suspendidos, 2 sin Job retenido, 2 con los pods ya borrados; la fila da su `nodeSelector`). Pods medidos en total (Jobs retenidos + VM 48 h): ks5-cp-3 7399 · sauvage 3243 · ubuntu 534 ·
  ks5-cp-2 4 · ks5-cp-1 2.
- **Repo dueño de los 94 de la ventana** (tracking de ArgoCD; los 6 sin tracking se resolvieron a mano):
  dgx-infra 19 · skirmshop-brain-k8s 17 · k8s-skirmbooks 10 · k8s-skirmshopshopifyapp 7 · k8s-shopify-label 6 ·
  k8s-infra 5 · k8s-shopify-picker 5 · k8s-observability 3 · k8s-shopify-back-in-stock 3 · k8s-synapse 3 ·
  k8s-shopify-sync 3 · k8s-skirmshop-drive-mirror 2 · k8s-litellm 2 · k8s-shopify-sii 2 · k8s-shopify-affiliate 2 ·
  langfuse-k8s 2 · descheduler 1 · k8s-shopify-chatbot 1 · k8s-socialmedia 1. Los timers del x86 son de
  **x86-host-runtime** o de **dgx-infra `scripts/`**; algunos no tienen repo (lo dice su fila).
- **Sin `startingDeadlineSeconds` en la ventana (18)**: chat/chat-tools-check, chat/reconcile-chat-catalog,
  kube-system/descheduler, kube-system/sauvage-pod-reaper, kube-system/sauvage-zombie-watchdog,
  langfuse/langfuse-clickhouse-retention, langfuse/langfuse-retention, litellm/litellm-spendlogs-retention,
  longhorn-system/{default, longhorn-no-snapshot-reconciler, openclaw-workspace-precutover-snapshot,
  sc80-drill-snap, weekly-backup}, skirmshop-product-relations/brain-product-relations-projector,
  skirmshop/labels-synapse-pod-reaper, skirmshop/labels-tracking-poll-scheduler, synapse/synapse-dlq-archive-purge,
  synapse/synapse-outbox-gc. Los cinco de Longhorn los genera longhorn-manager a partir de los RecurringJob, así
  que el campo no se fija en el CronJob.
- **Recursos**: salen de lo que declara el manifiesto (env, URLs, volúmenes, imagen, comando). No se midió el
  uso real. Donde solo el nombre lo sugiere, la celda lo dice.

## Informe del VP de las 08:00: localizado y retirado

No se encontró como disparo en ningún sitio el 30-09: ni en systemd/crontab del x86, ni entre los 121 CronJobs,
ni en los crons de Hermes (global y 8 perfiles con `cron/jobs.json`; no existe perfil `vp`). La historia de git
lo sitúa:

- Alta: x86-host-runtime `1640ac4` (07-09), «informe diario del VP a las 08:00».
- Baja: x86-host-runtime `a40a329` (17-09), que borra `libexec/vp-daily-report.sh` junto con el bot de Telegram
  de la compañía.
- Rol VP retirado: company-roles `989c341` (27-09). La maquinaria VP sale del harness en SC-1352
  (`51428a9`, 30-09).

Por tanto la invariante del spec «informe VP 08:00 tras las memorias que lee» **queda NO verificada**: el
disparo no existe. Siguen citándolo `company-options.json` (el `prompt_extra` del VP, «Every morning at
08:00…») y los comentarios de dreaming en el README de x86-host-runtime. H3 decide si la invariante cae.

## Hallazgos que afectan a H2/H3 (observados, no diagnosticados)

- **company-dreaming** es hoy un CronJob (`kube-system`, app k8s-infra, `30 1 * * *` Madrid, `activeDeadline 6 h`),
  no un timer del x86. Su unidad ya no está en x86-host-runtime `origin/main`. Hace `nsenter` al host x86 y usa el
  router local. Medido: el 29-09 tardó 1,6 h (01:30→03:06). **El 30-09 falló a los 25 min (01:55)** con «el
  clasificador no respondió tras 2 intentos (TimeoutError)» en el lote `index_catalog_picqer`.
- **backup-x86** (crontab 03:00): mediana 9,2 min. El 29-09 duró 2,5 h (03:00→05:27) y solapó con
  x86-localpath-pull (29-09 03:40, 22 min + 7 re-ejecuciones hasta 07:42) y con restic-hostpath 04:33.
- **Hermes contra LiteLLM/residente de madrugada**: «Buenos días Hogar» a las 06:00 (máx 71 min) y «Seguimiento
  envíos» a las 07:00 (máx 1,7 h) coinciden con rag-nl-llm-matcher 06:30 (máx 21 min). A las 03:17/03:37
  corren brain knowledge-pages (máx 26,5 min) y memory-promotion (máx 35 min), también contra LiteLLM.
- Los cambios de horario de las unidades del x86 irían a **x86-host-runtime** (units) o a **dgx-infra
  `scripts/`**. Los de Hermes van a su `jobs.json` en el PVC y no tienen repo.
