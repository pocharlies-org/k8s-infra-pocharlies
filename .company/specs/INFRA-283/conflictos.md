# INFRA-283 H2 (INFRA-337) — Mapa de conflictos por recurso compartido

`sre` lo calculó el **30-09-2026 entre las 13:15 y las 13:45 CEST**, solo con lecturas. Las duraciones salen de
`inventario.md` (H1); los horarios, de su columna `horario` + `timeZone`. El recurso físico que toca cada job se ha
comprobado en vivo con `kubectl get endpointslices/cronjob/backuptargets` y leyendo los manifiestos; el host de cada
IP NFS, con `kubectl get nodes -o wide`, medido por el CTO el 30-09-2026. Las ejecuciones
reales vienen de los Jobs retenidos (`kubectl get jobs`), `journalctl --user`, `~/logs/backup-x86.log` y
VictoriaMetrics (48 h). No se ha aplicado, escalado ni suspendido nada. Este documento **no propone horarios**: eso
es H3.

Un **conflicto** es que dos trabajos usen **el mismo recurso** a la vez. Coincidir solo en la hora no cuenta. Para
cada par se calculan los minutos de solape en su peor noche de la semana (noches del lun 28-09 al dom 04-10) de dos
maneras: con la **mediana** de duración y con el **máximo** del inventario. La tabla por recurso es la salida literal
de `python3 mapa_conflictos.py` (junto a este fichero; importa el expansor de cron de `cuenta_ventana.py`), así que
se puede regenerar.

## Resumen para H3

- **Cobertura**: aparecen las **136 filas** del inventario (94 CronJobs + 36 del x86 + 5 de Hermes + la del VP), cada
  una con su estado en la tabla final. 48 están en conflicto (2 alta, 21 media, 25 baja), 39 son de fondo (cada
  ≤ 30 min), 29 no tienen conflicto por recurso, 7 están suspendidas, 6 no tienen duración medida y 7 no se calculan
  (retiradas, desactivadas o de hora aleatoria). Con las duraciones medidas hay **un solo par en alta**: el kit ×
  el backup de synapse sobre el disco de sauvage (81–111 min). El resto de lo alto es **latente**: dreaming en su
  peor caso documentado (5,5 h), ver más abajo.
- **Dos de los cinco conflictos de la base del 29-09 no comparten recurso.** `company-dreaming ×
  recovery-kit-to-drive` coincide en hora, pero el kit corre entero en sauvage. `shopify-sync-warehouse ×
  rag-provider-sourcing-backfill` tampoco: este último solo toca Postgres. `recovery-kit ×
  synapse-skirmbooks-s3-drive-backup` sí comparte recurso: Google Drive y **el disco de sauvage**. El kit usa
  `minio-0` y el de synapse lee el volumen `nfs-cold`, que es un NFS servido desde sauvage (100.109.183.9).
- **El disco que de verdad se pelea de madrugada es el de sauvage.** Allí están:
  - `minio-0`, donde escriben los 5 dumps lógicos y `localpath-x86-backup` y de donde lee el kit de recuperación, que
    empieza a descargar a las 23:31;
  - el NFS de `nfs-cold`, que el backup de synapse lee de 00:15 a 03:15 y en el que escribe `skirmshop-drive-mirror`
    a las 03:10.

  Entre 23:30 y 23:58 se cruzan tres pesados de disco; de 00:15 a ~02:06, el kit y el backup de synapse. A eso se
  suman todos los pods de sauvage (22 CronJobs). Está medido que el disco del nodo se satura: el propio CronJob del kit
  documenta que el 29-09 containerd daba `context deadline exceeded`. No se ha medido si `/srv/nfs/k8s-cold` y
  `minio-0` están en el mismo HDD RAID1.
- **El host x86 cruza tres backups de disco a partir de las 03:00.** Son `backup-runner` (restic),
  `x86-localpath-pull` y `restic-hostpath`, además de `company-dreaming`, `blog-daily` y otros 6 CronJobs que cargan el
  nodo. Solo pasa en las noches largas del backup (máx. 148 min, 29-09). Con la mediana (9 min) solo coincide con
  la cola del backup de synapse (9 min). Los domingos se suma `weekly-backup` (06:00–06:54): su BackupTarget es un NFS
  en ubuntu (100.83.56.98) y se cruza con el backup de synapse de las 06:15 durante 39 min.
- **El router no lo satura el calendario.** El 30-09 el clasificador de dreaming agotó el tiempo a las 01:55 sin
  ningún otro job de inferencia programado. El residente estaba en su techo observado (13–16 peticiones en curso,
  hasta 4 en cola) por tráfico de agentes: 2.781 peticiones de `claude-local` y 807 de `hermes` entre 01:05 y 01:55.
- **Las APIs externas apenas chocan.** Los únicos pares puntuales son Picqer (warehouse × price-sync, 2–3 min) y
  Drive (kit × backup de synapse, 81–111 min). El resto del tráfico a APIs es de fondo: labels cada 2 min contra
  Picqer y back-in-stock cada 10 min contra Shopify.

## Los 5 conflictos del Diseño, recalculados

Se recalculan con las duraciones del inventario. El «observado» sale de los Jobs retenidos (inicio→fin reales, hora
local).

| # | par | recurso que comparten de verdad | ventana conjunta (peor caso) | solape med / máx | solape observado | severidad | frente a la base 29-09 |
|---|---|---|---|---|---|---|---|
| 1 | recovery-kit-to-drive × synapse-skirmbooks-s3-drive-backup | **disco del nodo sauvage + Google Drive (API)**. El kit lee `minio-0` en sauvage y escribe `/work` en sauvage. El de synapse lee `skirmshop-drive-s3` (pod en ubuntu), cuyo volumen `nfs-cold` es un NFS servido desde sauvage (100.109.183.9 = sauvage, `kubectl get nodes -o wide`, medido por el CTO el 30-09-2026) | 23:30–03:15 | 81 / 111 min | 29→30-09: 00:15–02:03 = **108 min** | **alta · disco** (mismo nodo; el mismo HDD no está medido) · media · límite API | base 83 min → 81 med / 111 máx. Se confirma como conflicto de disco, sobre el nodo sauvage |
| 1 | recovery-kit-to-drive × logical-dump-postgres-shared | disco sauvage (`minio-0`) | 23:00–02:06 | 0 / 9 min | 28-09: el dump acabó 23:39, el kit descargaba desde 23:31 → **8 min**; 27 y 29-09: 0 | media · disco | base sin minutos → 9 máx |
| 1 | recovery-kit-to-drive × localpath-x86-backup | disco sauvage (`minio-0`) | 23:30–02:06 | 10 / 12 min | 27/28/29-09: 11, 12 y 7 min | media · disco | nuevo con minutos; cruza todas las noches |
| 1 | recovery-kit-to-drive × logical-dump-postgres-shared-weekly | disco sauvage (`minio-0`) | 23:30–02:06 (dom) | 15 / 18 min | dom 27-09: 23:40–23:54 = 15 min | media · disco | nuevo; solo la noche del domingo |
| 1 | logical-dump-postgres-shared × dumps de keycloak y opencode | disco sauvage (`minio-0`) | 23:00–23:39 | <1 / 1 min | 23:10 y 23:20, 13–15 s cada uno | baja · disco | = base (0–1 min) |
| 2 | company-dreaming × recovery-kit-to-drive | **ninguno**: el kit corre en sauvage (nodeSelector, `minio-0` y subida a Drive desde sauvage); dreaming, en el host x86 | 01:30–02:06 | 6 / 36 min (solo en hora) | 29-09: 5 min · 30-09: 25 min | sin conflicto por recurso | base 8 min → coincidencia horaria, no conflicto |
| 2 | backup-runner.sh x86 × company-dreaming | host x86 (restic sobre el disco del host + pase de memorias con `nsenter`) | 01:30–05:27 | 0 / 6 min | 29-09: 03:00–03:06 = **6 min** | media · CPU/disco | base «cola» → 6 min |
| 2 | backup-runner.sh x86 × blog-daily | host x86 | 03:00–05:27 | 0 / 8 min | 29-09: blog 05:02:35–05:10:47, dentro del backup (03:00–05:27:34) = **8 min** | media · CPU/disco | base 27 min → 8. Los 27 eran la cola del backup desde las 05:00, no el cruce con el blog |
| 3 | company-dreaming × knowledge-pages 03:17 / memory-promotion 03:37 | router | — | **0 / 0 medido**: el máx. de dreaming (96 min) acaba a las 03:06, 11 min antes de las 03:17 | 29-09: dreaming acabó 03:06, memory-promotion 03:37–04:04 → 0 | sin conflicto medido; **latente alto** (ver abajo) | base «dentro de la ventana» → solo en el peor caso de 5,5 h |
| 3 | knowledge-pages × memory-promotion | router + brain | 03:17–04:12 | 0 / 6 min | 30-09: 03:17–03:18 y 03:37–03:38 → 0 | media · router | nuevo |
| 3 | «9 one-shot nocturnos tocan LiteLLM» | router | — | — | — | — | recontado: **12 puntuales de inferencia, 10 activos**: dreaming, knowledge-pages, memory-promotion, rag-nl-llm-matcher, blog-daily y 5 crons de Hermes; suspendidos rag-competitor-llm-matcher y brain-platform-refresh |
| 4 | logical-dump-postgres-shared × keycloak-role-drift / otros dumps | **no comparten Postgres**: role-drift usa la API de Keycloak y el dump de Keycloak es de su propia BD. En PG el dump cruza picker-picklist-close (23:00) y synapse-outbox-gc (23:17) | 23:00–23:39 | 1 / 6 min (picklist-close) · <1 (outbox-gc) | — | media · BD (picklist-close) · baja (outbox-gc) | base 0–1 min → 6 máx con picklist-close; además cruza 7 jobs de fondo de PG |
| 5 | shopify-sync-warehouse × rag-picqer-price-sync | API Picqer | 04:17–04:39 | 2 / 3 min | 30-09: 04:30–04:32 dentro de 04:17–04:35 = **2,4 min** | baja · límite API | base 3–4 min → 2–3 |
| 5 | shopify-sync-warehouse × rag-provider-sourcing-backfill | **ninguno**: provider-sourcing solo toca Postgres compartido (manifiesto), ni Shopify ni Picqer | — | — | — | sin conflicto por API | base 3–4 min → descartado |
| 5 | picker-ga4-refresh (GA4) | GA4 lo usa solo él | — | — | — | sin conflicto | = |

## Conflicto latente: dreaming en su peor caso documentado (5,5 h → 07:00)

Las dos pasadas medidas de dreaming son 96 min (29-09) y 25 min (30-09, fallida). El peor caso de 5,5 h está
**documentado en el spec de la épica, no medido**. Si ocurriera (01:30→07:00), dreaming cruzaría esto:

| recurso | cruza con | solape med / máx |
|---|---|---|
| router | knowledge-pages 03:17 | 9 / 26 min |
| router | memory-promotion 03:37 | 27 / 35 min |
| router | blog-daily 05:00 (además blog-daily depende del material de dreaming) | 5 / 8 min |
| router | Buenos días Hogar 06:00 (Hermes) | 7 / 60 min |
| router | rag-nl-llm-matcher 06:30 | 16 / 21 min |
| host x86 | backup-runner 03:00 | 9 / 148 min |
| host x86 | shopify-sync-warehouse 04:17 · x86-localpath-pull 04:30 · restic-hostpath 04:33 | 19 / 22 · <1 / 22 · 3 / 3 min |
| host x86 | synapse-skirmbooks-s3-drive-backup 00:15 y 06:15 (su MinIO está en ubuntu) | 99 / 105 · 45 / 45 min |

En el router serían dos pares **alta** (memory-promotion 35 min, Hogar 60 min) con otros dos pesados, y en el host
x86 uno alto (backup-runner). Con lo medido hoy, dreaming no toca a ningún job de inferencia.

## Router: qué ocupa el residente de madrugada

VictoriaMetrics, `vllm:num_requests_running` (máximo en ventanas de 10 min):

- **29-09 01:00–08:00**: 9–16 peticiones en curso toda la noche. Entre 01:30 y 03:10 no hay muestras (hueco de scrape
  o reinicio, sin medir).
- **30-09 01:30–02:20**, durante el fallo de dreaming: 13–16 en curso y hasta 4 en cola
  (`vllm:num_requests_waiting`, máximo de 30 min). Entre 03:20 y 08:00 baja a 0–5.
- **LiteLLM, 30-09 01:05–01:55**, peticiones por clave: `claude-local` 2.781, `hermes` 807, `aurora-rca` 210,
  `opencode-…-local` 91. Por modelo: `qwen38-flash-next` 1.931 y el fallback `alibaba-q38-flash` 1.907.

Lo que se observa es que el residente estaba lleno de tráfico de agentes cuando dreaming falló, y ningún CronJob de
inferencia estaba programado en esa franja. La hipótesis es que el techo real sea 16 concurrentes: es el máximo
observado, pero no se leyó `max-num-seqs`. Tampoco se ha medido qué parte de `claude-local` es el propio dreaming,
que también sale por claude-router.

## Límites de este mapa

- **Duraciones**: las del inventario. Se usa la mediana y el máximo de 3–5 noches (VM retiene 48 h). El único caso
  con más precisión que el redondeo del inventario es backup-runner (8853 s, citado en su propia fila). 6 filas no
  tienen duración y no se cruzan: brain-sweep, brain-opencode-sync, dgx463-perfil-watch, cron.daily,
  sii-monthly-report y skirmbooks-inventory-snapshot.
- **Hora aleatoria**: los timers con RandomizedDelay de franja acotada (fstrim, apt-daily-upgrade, weekly-apt-upgrade,
  blog-daily) se modelan como su franja completa, pero el solape nunca pasa de la duración del más corto. Los de 12 h
  (apt-daily, man-db, fwupd-refresh) quedan fuera: duran 0–58 s.
- **Fondo**: los trabajos que corren cada ≤ 30 min cruzan con todo lo de su recurso. No se listan par a par; aparecen
  con su ocupación (duración/periodo). Si pasa del 100 %, su máximo supera el periodo y, con `Forbid`, se salta
  disparos (chatbot-sync: máx. 8,8 min cada 5).
- **Severidad**: el tipo sale del recurso (disco, CPU/disco, router, BD, cola, límite API). El nivel:
  - **alta**: dos pesados y ≥ 30 min en un recurso saturable.
  - **media**: ≥ 5 min con al menos un pesado; en APIs, ≥ 30 min.
  - **baja**: el resto.

  «Pesado» significa lo siguiente. En disco y en el host x86 son los jobs de backup, restic, dumps, rclone, fstrim y
  dreaming (lista `HEAVY` del script); en esos recursos de nodo, dos pods ligeros en el mismo nodo no cuentan como
  conflicto. En los demás recursos, pesado es una duración máxima de 10 min o más.
- **Sin resolver (hipótesis, no hechos)**:
  - **Cuenta de Google Drive**: si el kit (Secret `drive-info-backup`, OAuth `drive.file`) y el backup de synapse
    (`synapse-secrets`) usan la misma cuenta, comparten la cuota diaria de subida. No se leyeron los secretos.
  - **Disco físico de `nfs-cold`**: no se ha medido si `/srv/nfs/k8s-cold` (sauvage) está en el mismo HDD RAID1 que
    `minio-0` y `/work` del kit. El nodo es el mismo (medido), pero el disco podría no serlo.
- **Medido después (antes era hipótesis)**: servidores NFS, según `kubectl get nodes -o wide`, medido por el CTO el 30-09-2026.
  - **100.109.183.9 = nodo sauvage**. Es el servidor de `nfs-cold` (`/srv/nfs/k8s-cold`), así que
    `synapse-skirmbooks-s3-drive-backup` y `skirmshop-drive-mirror` cargan el disco de sauvage.
  - **100.83.56.98 = nodo ubuntu**. Es el BackupTarget default de Longhorn, así que `weekly-backup` carga el disco
    del x86.

  El script (`EXTRA`/`HEAVY`) ya lo incorpora y las tablas generadas lo reflejan.
  - **El kit y el dump del día**: el kit empieza a descargar a las 23:31 y el dump de postgres-shared puede acabar a
    las 23:39. El 28-09 el kit incluyó el manifest del día, pero no se ha comprobado que el dump estuviera completo al
    copiarse.
- **Corrección a H1**: `skirmshop-drive-mirror` copia de **Drive → volumen** (`drive-sync.sh`: `rclone ${mode}
  "${remote}" "${current_dir}"`), no «MinIO → Google Drive» como dice su fila del inventario.

## Mapa por recurso (generado)

Salida de `python3 .company/specs/INFRA-283/mapa_conflictos.py`. Formato de cada fila: par · ventana conjunta en
su peor noche · solape con la mediana · solape con el máximo · noches en que se cruzan · severidad.

<!-- generado por mapa_conflictos.py desde inventario.md: 136 filas; noches 28-09→04-10 -->

### DISCO-SAUVAGE — minio-0 y disco del nodo sauvage (dumps, kit de recuperación, pods del nodo)

| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |
|---|---|---|---|---|---|
| backup-hub/recovery-kit-to-drive × synapse/synapse-skirmbooks-s3-drive-backup | 23:30–03:15 | 81 min | 111 min | todas | alta · disco |
| backup-hub/recovery-kit-to-drive × databases/logical-dump-postgres-shared-weekly | 23:30–02:06 | 15 min | 18 min | dom→lun | media · disco |
| backup-hub/recovery-kit-to-drive × libreplay/localpath-x86-backup | 23:30–02:06 | 10 min | 12 min | todas | media · disco |
| databases/logical-dump-postgres-shared-weekly × libreplay/localpath-x86-backup | 23:40–23:58 | 10 min | 12 min | dom→lun | media · disco |
| databases/logical-dump-postgres-shared × backup-hub/recovery-kit-to-drive | 23:00–02:06 | 0 min | 9 min | todas | media · disco |
| skirmshop/picker-picklist-close × databases/logical-dump-postgres-shared | 23:00–23:39 | 1 min | 6 min | todas | media · disco |
| skirmshop/picker-picklist-close × backup-hub/recovery-kit-to-drive | 23:30–02:06 | 1 min | 6 min | todas | media · disco |
| skirmshop/picker-picklist-close × synapse/synapse-skirmbooks-s3-drive-backup | 00:15–03:15 | 1 min | 6 min | todas | media · disco |
| backup-hub/recovery-kit-to-drive × skirmshop/sii-invoicing | 23:30–02:06 | 5 min | 6 min | todas | media · disco |
| synapse/synapse-skirmbooks-s3-drive-backup × skirmshop/sii-invoicing | 00:15–03:15 | 5 min | 6 min | todas | media · disco |
| synapse/synapse-skirmbooks-s3-drive-backup × backup-hub/skirmshop-drive-mirror | 00:15–03:15 | 0 min | 5 min | todas | media · disco |
| databases/logical-dump-postgres-shared × opencode/logical-dump-opencode | 23:00–23:39 | <1 min | 1 min | todas | baja · disco |
| synapse/synapse-skirmbooks-s3-drive-backup × skirmshop/affiliate-gdpr-prune | 00:15–03:15 | 1 min | 1 min | todas | baja · disco |
| databases/logical-dump-postgres-shared × keycloak/logical-dump-keycloak-postgres | 23:00–23:39 | <1 min | <1 min | todas | baja · disco |
| backup-hub/skirmshop-drive-mirror × skirmshop/affiliate-sync-discounts | 03:10–03:15 | 0 min | <1 min | todas | baja · disco |

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): skirmshop/chatbot-sync cada 5 min, ocupa 11–176 %; skirmshop/back-in-stock-preorder-coverage-reconcile cada 10 min, ocupa 3–80 %; skirmshop/skirmbooks-dehu-fetch cada 15 min, ocupa 5–74 %; kube-system/sauvage-zombie-watchdog cada 5 min, ocupa 12–58 %; skirmshop/back-in-stock-preorder-hold-reconcile cada 10 min, ocupa 6–58 %; skirmshop/skirmbooks-reconcile-sweep cada 15 min, ocupa 6–33 %; kube-system/sauvage-pod-reaper cada 15 min, ocupa 5–26 %; skirmshop/skirmbooks-accounting-sweep cada 15 min, ocupa 3–24 %

### DISCO-DRIVE-S3 — volumen nfs-cold `skirmshop-drive-mirror` (NFS en sauvage, 100.109.183.9) servido por el MinIO skirmshop-drive-s3 (pod en ubuntu)

| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |
|---|---|---|---|---|---|
| synapse/synapse-skirmbooks-s3-drive-backup × backup-hub/skirmshop-drive-mirror | 00:15–03:15 | 0 min | 5 min | todas | media · disco |

### DISCO-LONGHORN — Longhorn: snapshots y backup al BackupTarget default (NFS en ubuntu, 100.83.56.98)

Sin pares puntuales que se crucen en este recurso.

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): longhorn-system/sc80-drill-snap cada 5 min, ocupa 2–4 %; longhorn-system/longhorn-no-snapshot-reconciler cada 20 min, ocupa 0–2 %

### HOST-X86 — host x86 = nodo ubuntu: pods del nodo + unidades del host

| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |
|---|---|---|---|---|---|
| synapse/synapse-skirmbooks-s3-drive-backup × kube-system/company-dreaming | 00:15–03:15 | 61 min | 96 min | todas | media · CPU/disco |
| synapse/synapse-skirmbooks-s3-drive-backup × longhorn-system/weekly-backup | 06:00–09:15 | 39 min | 39 min | sáb→dom | media · CPU/disco |
| skirmshop/shopify-sync-warehouse × backup-runner.sh x86 | 03:00–05:27 | 0 min | 22 min | todas | media · CPU/disco |
| backup-runner.sh x86 × x86-localpath-pull | 03:00–05:27 | 0 min | 22 min | todas | media · CPU/disco |
| synapse/synapse-skirmbooks-s3-drive-backup × backup-runner.sh x86 | 00:15–05:27 | 9 min | 15 min | todas | media · CPU/disco |
| synapse/synapse-skirmbooks-s3-drive-backup × fstrim | 00:00–03:15 | 0 min | 14 min | dom→lun | media · CPU/disco |
| skirmshop/shopify-sync-warehouse × fstrim | 00:00–01:54 | 0 min | 14 min | dom→lun | media · CPU/disco |
| kube-system/company-dreaming × fstrim | 00:00–03:06 | 0 min | 14 min | dom→lun | media · CPU/disco |
| skirmshop/shopify-sync-warehouse × x86-localpath-pull | 04:17–04:52 | <1 min | 9 min | todas | media · CPU/disco |
| backup-runner.sh x86 × blog-daily | 03:00–05:27 | 0 min | 8 min | todas | media · CPU/disco |
| kube-system/company-dreaming × backup-runner.sh x86 | 01:30–05:27 | 0 min | 6 min | todas | media · CPU/disco |
| backup-hub/skirmshop-drive-mirror × backup-runner.sh x86 | 03:00–05:27 | 0 min | 5 min | todas | media · CPU/disco |
| skirmshop/shopify-sync-warehouse × restic-hostpath-backup@ubuntu | 04:17–04:39 | 3 min | 3 min | todas | baja · CPU/disco |
| backup-runner.sh x86 × restic-hostpath-backup@ubuntu | 03:00–05:27 | 0 min | 3 min | todas | baja · CPU/disco |
| x86-localpath-pull × restic-hostpath-backup@ubuntu | 04:30–04:52 | 0 min | 3 min | todas | baja · CPU/disco |
| longhorn-system/weekly-backup × apt-daily-upgrade | 06:00–07:01 | 1 min | 1 min | sáb→dom | baja · CPU/disco |
| backup-runner.sh x86 × weekly-apt-upgrade | 03:00–05:27 | 0 min | 1 min | vie→sáb | baja · CPU/disco |
| x86-localpath-pull × weekly-apt-upgrade | 04:30–04:52 | <1 min | 1 min | vie→sáb | baja · CPU/disco |
| restic-hostpath-backup@ubuntu × weekly-apt-upgrade | 04:30–04:51 | 0 min | 1 min | vie→sáb | baja · CPU/disco |
| skirmshop/shopify-sync-weights × longhorn-system/weekly-backup | 06:00–06:54 | <1 min | <1 min | sáb→dom | baja · CPU/disco |
| skirmshop/shopify-sync-weights × fstrim | 00:00–01:54 | 0 min | <1 min | dom→lun | baja · CPU/disco |
| kube-system/company-dreaming × skirmshop/shopify-picqer-order-audit | 01:30–03:06 | <1 min | <1 min | todas | baja · CPU/disco |
| update-watch/update-watch × backup-runner.sh x86 | 03:00–05:27 | 0 min | <1 min | todas | baja · CPU/disco |
| backup-runner.sh x86 × browser-harness-daily-update | 03:00–05:27 | 0 min | <1 min | todas | baja · CPU/disco |
| backup-runner.sh x86 × company-kanban-limpieza | 03:00–05:27 | 0 min | <1 min | todas | baja · CPU/disco |
| company-kanban-limpieza × x86-localpath-pull | 04:30–04:52 | 0 min | <1 min | todas | baja · CPU/disco |
| backup-runner.sh x86 × update-watch-host-versions | 03:00–05:27 | 0 min | <1 min | todas | baja · CPU/disco |
| logrotate × fstrim | 00:00–01:54 | <1 min | <1 min | dom→lun | baja · CPU/disco |
| backup-runner.sh x86 × e2scrub_all | 03:00–05:27 | 0 min | <1 min | sáb→dom | baja · CPU/disco |

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): whatsapp-mcp/brain-ingest cada 5 min, ocupa 10–96 %; vscode-archivadas-kill cada 0.25 min, ocupa 7–93 %; company-agent cada 0.5 min, ocupa 10–33 %; rc-title-sync cada 1 min, ocupa 2–30 %; litellm/litellm-watchdog cada 10 min, ocupa 1–16 %; company-options-applier cada 2 min, ocupa 3–6 %; skirmshop-brain-prod/skirmshop-brain-reembed-truncated cada 20 min, ocupa 1–3 %; cloudflare-ddns.sh cada 5 min, ocupa 0–2 %; company-freno-alibaba cada 30 min, ocupa 0–1 %; control-nexus/home-ddns cada 15 min, ocupa 1–1 %; claude-rc-keepalive cada 60 min, ocupa 0–0 %; owui-mcp-defaults-watch cada 30 min, ocupa 0–0 %; github-app-token cada 45 min, ocupa 0–0 %; brain-sweep.sh cada 5 min, ocupa ¿? (sin historial); brain-opencode-sync.py cada 10 min, ocupa ¿? (sin historial); flannel-heal cada 2 min, ocupa 0–0 %; ext4-guard cada 2 min, ocupa 0–0 %; sysstat-collect cada 10 min, ocupa 0–0 %

### ROUTER — LiteLLM (pods en ubuntu) → residente qwen38-flash-next (Sparks)

| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |
|---|---|---|---|---|---|
| skirmshop/rag-nl-llm-matcher × Buenos días Hogar | 06:00–07:11 | 0 min | 21 min | todas | media · router |
| Buenos días Hogar × Seguimiento envíos | 06:00–08:42 | 0 min | 11 min | todas | media · router |
| skirmshop-brain-prod/skirmshop-brain-knowledge-pages × skirmshop-brain-prod/skirmshop-brain-memory-promotion | 03:17–04:12 | 0 min | 6 min | todas | media · router |
| Buenos días Hogar × pm-revision-diaria-backlog | 06:00–07:11 | 0 min | <1 min | todas | baja · router |
| Seguimiento envíos × pm-revision-diaria-backlog | 07:00–08:42 | <1 min | <1 min | todas | baja · router |

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): litellm/litellm-watchdog cada 10 min, ocupa 1–16 %; chat/reconcile-chat-catalog cada 15 min, ocupa 1–2 %; company-freno-alibaba cada 30 min, ocupa 0–1 %

### PG — Postgres compartido (databases/postgres-shared)

| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |
|---|---|---|---|---|---|
| skirmshop/picker-picklist-close × databases/logical-dump-postgres-shared | 23:00–23:39 | 1 min | 6 min | todas | media · BD |
| skirmshop/picker-picklist-close × skirmshop/picker-purchase-signals | 04:00–04:13 | 1 min | 6 min | todas | media · BD |
| skirmshop/picker-picklist-close × skirmshop/sii-invoicing | 01:00–01:05 | 1 min | 6 min | todas | baja · BD |
| skirmshop/picker-picklist-close × skirmshop/skirmbooks-classifier-sweep | 05:00–05:05 | <1 min | 1 min | todas | baja · BD |
| skirmshop/picker-picklist-close × skirmshop/picker-retention | 05:00–05:05 | <1 min | 1 min | todas | baja · BD |
| skirmshop/picker-retention × skirmshop/skirmbooks-classifier-sweep | 05:00–05:01 | <1 min | 1 min | todas | baja · BD |
| skirmshop/picker-picklist-close × skirmshop/affiliate-gdpr-prune | 03:00–03:05 | 1 min | 1 min | todas | baja · BD |
| skirmshop/picker-picklist-close × skirmshop/skirmbooks-patterns-weekly | 06:00–06:05 | 1 min | 1 min | dom→lun | baja · BD |
| synapse/synapse-outbox-gc × databases/logical-dump-postgres-shared | 23:00–23:39 | <1 min | <1 min | todas | baja · BD |
| synapse/synapse-outbox-gc × skirmshop/skirmbooks-banking-klarna-sync | 05:17–05:17 | <1 min | <1 min | todas | baja · BD |

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): whatsapp-mcp/brain-ingest cada 5 min, ocupa 10–96 %; skirmshop/skirmbooks-reconcile-sweep cada 15 min, ocupa 6–33 %; skirmshop/skirmbooks-accounting-sweep cada 15 min, ocupa 3–24 %; skirmshop/labels-pickup-point-reminder cada 2 min, ocupa 7–21 %; skirmshop/labels-ops-edit-hold-reconciler cada 2 min, ocupa 3–9 %; skirmshop/labels-tracking-poll-scheduler cada 15 min, ocupa 1–2 %; chat/reconcile-chat-catalog cada 15 min, ocupa 1–2 %

### BRAIN — brain de skirmshop-brain-prod (Qdrant/FalkorDB/Valkey)

| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |
|---|---|---|---|---|---|
| skirmshop-brain-prod/skirmshop-brain-personal-graph-enrichment × skirmshop-brain-prod/skirmshop-brain-audit | 04:17–04:40 | 4 min | 10 min | todas | media · BD |
| skirmshop-brain-prod/skirmshop-brain-knowledge-pages × skirmshop-brain-prod/skirmshop-brain-memory-promotion | 03:17–04:12 | 0 min | 6 min | todas | media · BD |
| skirmshop-brain-prod/skirmshop-brain-neural-gardener-claude × skirmshop/rag-nl-llm-matcher | 06:30–06:51 | 0 min | 4 min | todas | baja · BD |
| skirmshop-brain-prod/skirmshop-brain-personal-graph-enrichment × skirmshop-brain-prod/skirmshop-brain-claude-session-graph | 04:17–04:40 | 2 min | 3 min | todas | baja · BD |
| skirmshop-brain-prod/skirmshop-brain-audit × skirmshop-brain-prod/skirmshop-brain-claude-session-graph | 04:30–04:40 | 0 min | 3 min | todas | baja · BD |
| skirmshop-brain-prod/skirmshop-brain-personal-graph-enrichment × skirmshop/rag-picqer-price-sync | 04:17–04:40 | 2 min | 3 min | todas | baja · BD |
| skirmshop/rag-picqer-price-sync × skirmshop-brain-prod/skirmshop-brain-audit | 04:30–04:40 | 2 min | 3 min | todas | baja · BD |
| skirmshop-brain-prod/skirmshop-brain-knowledge-pages × skirmshop-brain-prod/skirmshop-brain-personal-payload-indexes | 03:17–03:43 | <1 min | <1 min | todas | baja · BD |

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): whatsapp-mcp/brain-ingest cada 5 min, ocupa 10–96 %; skirmshop-brain-prod/skirmshop-brain-personal-payload-normalization cada 30 min, ocupa 11–29 %; skirmshop-brain-prod/skirmshop-brain-status-snapshot cada 5 min, ocupa 1–5 %; skirmshop-brain-prod/skirmshop-brain-reembed-truncated cada 20 min, ocupa 1–3 %; skirmshop-brain-prod/skirmshop-brain-gmail-cleanup-metrics cada 10 min, ocupa 1–3 %; brain-sweep.sh cada 5 min, ocupa ¿? (sin historial); brain-opencode-sync.py cada 10 min, ocupa ¿? (sin historial)

### RABBIT — RabbitMQ compartido → workers de synapse

Sin pares puntuales que se crucen en este recurso.

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): skirmshop/skirmbooks-dehu-fetch cada 15 min, ocupa 5–74 %; skirmshop/skirmbooks-reconcile-sweep cada 15 min, ocupa 6–33 %; skirmshop/skirmbooks-accounting-sweep cada 15 min, ocupa 3–24 %

### API-SHOPIFY — Shopify Admin API

Sin pares puntuales que se crucen en este recurso.

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): skirmshop/back-in-stock-preorder-coverage-reconcile cada 10 min, ocupa 3–80 %; skirmshop/back-in-stock-preorder-hold-reconcile cada 10 min, ocupa 6–58 %

### API-PICQER — Picqer API

| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |
|---|---|---|---|---|---|
| skirmshop/shopify-sync-warehouse × skirmshop/rag-picqer-price-sync | 04:17–04:39 | 2 min | 3 min | todas | baja · límite API |
| skirmshop/shopify-sync-weights × skirmshop/rag-nl-llm-matcher | 06:30–06:51 | <1 min | <1 min | todas | baja · límite API |

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): skirmshop/labels-ops-edit-hold-reconciler cada 2 min, ocupa 3–9 %

### API-DRIVE — Google Drive (rclone)

| par (A × B) | ventana conjunta, peor caso | solape med | solape máx | noches | severidad |
|---|---|---|---|---|---|
| backup-hub/recovery-kit-to-drive × synapse/synapse-skirmbooks-s3-drive-backup | 23:30–03:15 | 81 min | 111 min | todas | media · límite API |
| synapse/synapse-skirmbooks-s3-drive-backup × backup-hub/skirmshop-drive-mirror | 00:15–03:15 | 0 min | 5 min | todas | baja · límite API |

### API-AEAT — AEAT (SII, DEH, DEHú)

Sin pares puntuales que se crucen en este recurso.

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): skirmshop/skirmbooks-dehu-fetch cada 15 min, ocupa 5–74 %

### API-GITHUB — GitHub API

Sin pares puntuales que se crucen en este recurso.

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): control-nexus/github-token-refresh cada 30 min, ocupa 1–2 %; github-app-token cada 45 min, ocupa 0–0 %

### API-CLOUDFLARE — Cloudflare DNS API

Sin pares puntuales que se crucen en este recurso.

Fondo (periodo ≤ 30 min o continuo; cruza con todo lo de arriba): cloudflare-ddns.sh cada 5 min, ocupa 0–2 %; control-nexus/home-ddns cada 15 min, ocupa 1–1 %

### Cobertura: las 136 filas del inventario

| fila | recursos | estado en el mapa |
|---|---|---|
| backup-hub/skirmshop-drive-s3-to-drive | DISCO-SAUVAGE, DISCO-DRIVE-S3, HOST-X86, API-DRIVE | SUSPENDIDO: no dispara, sin conflicto hoy |
| chat/reconcile-chat-catalog | ROUTER, PG | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| control-nexus/github-token-refresh | API-GITHUB | fondo, cada 30 min (ocupación en la tabla de su recurso) |
| control-nexus/home-ddns | HOST-X86, API-CLOUDFLARE | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| keycloak/keycloak-role-drift | propio (no compartido con otro nocturno) | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| kube-system/descheduler | propio (no compartido con otro nocturno) | fondo, cada 2 min (ocupación en la tabla de su recurso) |
| kube-system/sauvage-pod-reaper | DISCO-SAUVAGE | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| kube-system/sauvage-zombie-watchdog | DISCO-SAUVAGE | fondo, cada 5 min (ocupación en la tabla de su recurso) |
| litellm/litellm-watchdog | HOST-X86, ROUTER | fondo, cada 10 min (ocupación en la tabla de su recurso) |
| longhorn-system/longhorn-no-snapshot-reconciler | DISCO-LONGHORN | fondo, cada 20 min (ocupación en la tabla de su recurso) |
| longhorn-system/sc80-drill-snap | DISCO-LONGHORN | fondo, cada 5 min (ocupación en la tabla de su recurso) |
| monitoring/keepsvc-stale-reaper | propio (no compartido con otro nocturno) | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| renovate/github-token-refresh | HOST-X86, API-GITHUB | SUSPENDIDO: no dispara, sin conflicto hoy |
| skirmshop/back-in-stock-preorder-hold-reconcile | DISCO-SAUVAGE, API-SHOPIFY | fondo, cada 10 min (ocupación en la tabla de su recurso) |
| skirmshop/chatbot-sync | DISCO-SAUVAGE | fondo, cada 5 min (ocupación en la tabla de su recurso); su máx (9 min) supera el periodo: con Forbid se salta disparos |
| skirmshop/labels-deep-monitor | propio (no compartido con otro nocturno) | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| skirmshop/labels-ops-edit-hold-reconciler | PG, API-PICQER | fondo, cada 2 min (ocupación en la tabla de su recurso) |
| skirmshop/labels-pickup-point-reminder | PG | fondo, cada 2 min (ocupación en la tabla de su recurso) |
| skirmshop/labels-synapse-pod-reaper | propio (no compartido con otro nocturno) | fondo, cada 10 min (ocupación en la tabla de su recurso) |
| skirmshop/labels-tracking-poll-scheduler | PG | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| skirmshop/picker-picklist-close | DISCO-SAUVAGE, PG, API-PICQER | EN CONFLICTO: media en DISCO-SAUVAGE, PG |
| skirmshop/skirmbooks-dehu-fetch | DISCO-SAUVAGE, RABBIT, API-AEAT | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| skirmshop/skirmbooks-reconcile-sweep | DISCO-SAUVAGE, PG, RABBIT | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| skirmshop-brain-prod/skirmshop-brain-gmail-cleanup-metrics | BRAIN | fondo, cada 10 min (ocupación en la tabla de su recurso) |
| skirmshop-brain-prod/skirmshop-brain-reembed-truncated | HOST-X86, BRAIN | fondo, cada 20 min (ocupación en la tabla de su recurso) |
| skirmshop-brain-prod/skirmshop-brain-status-snapshot | BRAIN | fondo, cada 5 min (ocupación en la tabla de su recurso) |
| whatsapp-mcp/brain-ingest | HOST-X86, PG, BRAIN | fondo, cada 5 min (ocupación en la tabla de su recurso) |
| skirmshop/back-in-stock-preorder-coverage-reconcile | DISCO-SAUVAGE, API-SHOPIFY | fondo, cada 10 min (ocupación en la tabla de su recurso) |
| skirmshop/skirmbooks-accounting-sweep | DISCO-SAUVAGE, PG, RABBIT | fondo, cada 15 min (ocupación en la tabla de su recurso) |
| skirmshop-brain-prod/skirmshop-brain-personal-payload-normalization | BRAIN | fondo, cada 30 min (ocupación en la tabla de su recurso) |
| synapse/synapse-outbox-gc | PG | EN CONFLICTO: baja en PG |
| skirmshop/skirmbooks-deh-poll-night | DISCO-SAUVAGE, RABBIT, API-AEAT | sin conflicto por recurso |
| databases/logical-dump-postgres-shared | DISCO-SAUVAGE, PG | EN CONFLICTO: media en DISCO-SAUVAGE, PG |
| keycloak/logical-dump-keycloak-postgres | DISCO-SAUVAGE | EN CONFLICTO: baja en DISCO-SAUVAGE |
| aiops/logical-dump-aiops | DISCO-SAUVAGE | SUSPENDIDO: no dispara, sin conflicto hoy |
| opencode/logical-dump-opencode | DISCO-SAUVAGE, HOST-X86 | EN CONFLICTO: baja en DISCO-SAUVAGE |
| backup-hub/recovery-kit-to-drive | DISCO-SAUVAGE, API-DRIVE | EN CONFLICTO: alta en DISCO-SAUVAGE; media en API-DRIVE |
| databases/logical-dump-postgres-shared-weekly | DISCO-SAUVAGE | EN CONFLICTO: media en DISCO-SAUVAGE |
| libreplay/localpath-x86-backup | DISCO-SAUVAGE, HOST-X86 | EN CONFLICTO: media en DISCO-SAUVAGE |
| skirmshop-brain-prod/skirmshop-brain-reembed-watchdog | propio (no compartido con otro nocturno) | sin conflicto por recurso |
| skirmshop-brain-prod/skirmshop-brain-neural-gardener-skirmshop | BRAIN | sin conflicto por recurso |
| synapse/synapse-skirmbooks-s3-drive-backup | DISCO-SAUVAGE, DISCO-DRIVE-S3, HOST-X86, API-DRIVE | EN CONFLICTO: alta en DISCO-SAUVAGE; media en DISCO-DRIVE-S3, HOST-X86, API-DRIVE |
| skirmshop/shopify-sync-warehouse | HOST-X86, API-SHOPIFY, API-PICQER | EN CONFLICTO: media en HOST-X86; baja en API-PICQER |
| skirmshop-brain-prod/skirmshop-brain-neural-gardener-personal | BRAIN | sin conflicto por recurso |
| skirmshop/shopify-sync-weights | HOST-X86, API-SHOPIFY, API-PICQER | EN CONFLICTO: baja en HOST-X86, API-PICQER |
| skirmshop-brain-prod/skirmshop-brain-neural-gardener-claude | BRAIN | EN CONFLICTO: baja en BRAIN |
| skirmshop/sii-invoicing | DISCO-SAUVAGE, PG, RABBIT, API-SHOPIFY, API-AEAT | EN CONFLICTO: media en DISCO-SAUVAGE; baja en PG |
| skirmshop/sii-monthly-report | DISCO-SAUVAGE, PG, RABBIT | sin duración medida (sin historial): no calculable |
| kube-system/company-dreaming | HOST-X86, ROUTER | EN CONFLICTO: media en HOST-X86 |
| skirmshop/back-in-stock-backorder-enroll | DISCO-SAUVAGE, API-SHOPIFY, API-PICQER | SUSPENDIDO: no dispara, sin conflicto hoy |
| skirmshop/rag-taxonomy-canonicalize | PG | sin conflicto por recurso |
| skirmshop/shopify-picqer-order-audit | HOST-X86, API-SHOPIFY, API-PICQER | EN CONFLICTO: baja en HOST-X86 |
| skirmshop/affiliate-gdpr-prune | DISCO-SAUVAGE, PG | EN CONFLICTO: baja en DISCO-SAUVAGE, PG |
| backup-hub/skirmshop-drive-mirror | DISCO-SAUVAGE, DISCO-DRIVE-S3, HOST-X86, API-DRIVE | EN CONFLICTO: media en DISCO-SAUVAGE, DISCO-DRIVE-S3, HOST-X86; baja en API-DRIVE |
| skirmshop/affiliate-sync-discounts | DISCO-SAUVAGE, PG, RABBIT, API-SHOPIFY | EN CONFLICTO: baja en DISCO-SAUVAGE |
| skirmshop-brain-prod/skirmshop-brain-knowledge-pages | ROUTER, BRAIN | EN CONFLICTO: media en ROUTER, BRAIN |
| skirmshop-brain-prod/skirmshop-brain-personal-payload-indexes | BRAIN | EN CONFLICTO: baja en BRAIN |
| skirmshop/picker-ga4-refresh | DISCO-SAUVAGE, API-GA4 | sin conflicto por recurso |
| skirmshop-brain-prod/skirmshop-brain-memory-promotion | ROUTER, BRAIN | EN CONFLICTO: media en ROUTER, BRAIN |
| monitoring/keepsvc-maintenance-window | propio (no compartido con otro nocturno) | sin conflicto por recurso |
| longhorn-system/default | DISCO-LONGHORN | sin conflicto por recurso |
| skirmshop/picker-purchase-signals | DISCO-SAUVAGE, PG | EN CONFLICTO: media en PG |
| longhorn-system/openclaw-workspace-precutover-snapshot | DISCO-LONGHORN | sin conflicto por recurso |
| skirmshop/rag-redirect-health | API-SHOPIFY | sin conflicto por recurso |
| chat/searxng-autoupdate | propio (no compartido con otro nocturno) | sin conflicto por recurso |
| skirmshop-brain-prod/skirmshop-brain-personal-graph-enrichment | BRAIN | EN CONFLICTO: media en BRAIN |
| chat/chat-tools-check | propio (no compartido con otro nocturno) | sin conflicto por recurso |
| skirmshop/rag-picqer-price-sync | BRAIN, API-PICQER | EN CONFLICTO: baja en BRAIN, API-PICQER |
| skirmshop/rag-provider-sourcing-backfill | PG | sin conflicto por recurso |
| skirmshop-brain-prod/skirmshop-brain-audit | BRAIN | EN CONFLICTO: media en BRAIN |
| skirmshop-brain-prod/skirmshop-brain-claude-session-graph | BRAIN | EN CONFLICTO: baja en BRAIN |
| skirmshop-brain-prod/skirmshop-brain-pages-reconcile | BRAIN, API-SHOPIFY | sin conflicto por recurso |
| skirmshop/labels-vat-sync | DISCO-SAUVAGE, API-SHOPIFY | sin conflicto por recurso |
| skirmshop/picker-retention | DISCO-SAUVAGE, PG | EN CONFLICTO: baja en PG |
| skirmshop/skirmbooks-classifier-sweep | DISCO-SAUVAGE, PG, RABBIT | EN CONFLICTO: baja en PG |
| aurora/aurorasvc-brain-kb-sync | DISCO-SAUVAGE | sin conflicto por recurso |
| skirmshop/skirmbooks-deh-poll-morning | DISCO-SAUVAGE, RABBIT, API-AEAT | sin conflicto por recurso |
| update-watch/update-watch | HOST-X86, API-GITHUB | EN CONFLICTO: baja en HOST-X86 |
| skirmshop/skirmbooks-banking-klarna-sync | DISCO-SAUVAGE, PG, RABBIT | EN CONFLICTO: baja en PG |
| skirmshop-product-relations/brain-product-relations-projector | propio (no compartido con otro nocturno) | sin conflicto por recurso |
| skirmshop/skirmbooks-banking-paypal-sync | DISCO-SAUVAGE, PG, RABBIT | sin conflicto por recurso |
| langfuse/langfuse-clickhouse-retention | propio (no compartido con otro nocturno) | sin conflicto por recurso |
| skirmshop/rag-competitor-llm-matcher | ROUTER, BRAIN | SUSPENDIDO: no dispara, sin conflicto hoy |
| litellm/litellm-spendlogs-retention | HOST-X86, PG | sin conflicto por recurso |
| synapse/synapse-dlq-archive-purge | PG | sin conflicto por recurso |
| renovate/renovate | HOST-X86, API-GITHUB | sin conflicto por recurso |
| langfuse/langfuse-retention | propio (no compartido con otro nocturno) | sin conflicto por recurso |
| longhorn-system/weekly-backup | DISCO-LONGHORN, HOST-X86 | EN CONFLICTO: media en HOST-X86 |
| skirmshop/picker-purchase-recommend | DISCO-SAUVAGE, PG, RABBIT | SUSPENDIDO: no dispara, sin conflicto hoy |
| skirmshop/skirmbooks-inventory-snapshot | PG, RABBIT | sin duración medida (sin historial): no calculable |
| skirmshop/skirmbooks-patterns-weekly | PG | EN CONFLICTO: baja en PG |
| skirmshop/rag-parent-health | API-SHOPIFY | sin conflicto por recurso |
| skirmshop/rag-nl-llm-matcher | ROUTER, BRAIN, API-PICQER | EN CONFLICTO: media en ROUTER; baja en BRAIN, API-PICQER |
| skirmshop-brain-prod/skirmshop-brain-platform-refresh | ROUTER, BRAIN | SUSPENDIDO: no dispara, sin conflicto hoy |
| x86 · crontab · backup-runner.sh x86 | HOST-X86 | EN CONFLICTO: media en HOST-X86 |
| x86 · crontab · cloudflare-ddns.sh | HOST-X86, API-CLOUDFLARE | fondo, cada 5 min (ocupación en la tabla de su recurso) |
| x86 · crontab · brain-sweep.sh | HOST-X86, BRAIN | sin duración medida (sin historial): no calculable |
| x86 · crontab · brain-opencode-sync.py | HOST-X86, BRAIN | sin duración medida (sin historial): no calculable |
| x86 · crontab · dgx463-perfil-watch.sh | HOST-X86 | sin duración medida (sin historial): no calculable |
| x86 · crontab · reinicio bge-m3-embedding (docker) | HOST-X86 | fuera del cálculo: no-op: el contenedor no existe |
| x86 · /etc/crontab · run-parts cron.daily | HOST-X86 | sin duración medida (sin historial): no calculable |
| x86 · timer user · update-watch-host-versions | HOST-X86 | EN CONFLICTO: baja en HOST-X86 |
| x86 · timer user · browser-harness-daily-update | HOST-X86, API-GITHUB | EN CONFLICTO: baja en HOST-X86 |
| x86 · timer user · company-kanban-limpieza | HOST-X86 | EN CONFLICTO: baja en HOST-X86 |
| x86 · timer user · blog-daily | HOST-X86, ROUTER | EN CONFLICTO: media en HOST-X86 |
| x86 · timer user · music3-window-rollout | HOST-X86 | fuera del cálculo: retirada: la unidad no existe el 30-09 |
| x86 · timer user · vscode-archivadas-kill | HOST-X86 | fondo, cada 0.25 min (ocupación en la tabla de su recurso) |
| x86 · timer user · company-agent | HOST-X86 | fondo, cada 0.5 min (ocupación en la tabla de su recurso) |
| x86 · timer user · rc-title-sync | HOST-X86 | fondo, cada 1 min (ocupación en la tabla de su recurso) |
| x86 · timer user · company-options-applier | HOST-X86 | fondo, cada 2 min (ocupación en la tabla de su recurso) |
| x86 · timer user · company-freno-alibaba | HOST-X86, ROUTER | fondo, cada 30 min (ocupación en la tabla de su recurso) |
| x86 · timer user · owui-mcp-defaults-watch | HOST-X86 | fondo, cada 30 min (ocupación en la tabla de su recurso) |
| x86 · timer user · claude-rc-keepalive | HOST-X86 | fondo, cada 60 min (ocupación en la tabla de su recurso) |
| x86 · timer sistema · dpkg-db-backup | HOST-X86 | sin conflicto por recurso |
| x86 · timer sistema · logrotate | HOST-X86 | EN CONFLICTO: baja en HOST-X86 |
| x86 · timer sistema · man-db | HOST-X86 | fuera del cálculo: hora aleatoria en toda la noche (RandomizedDelay); 3 s |
| x86 · timer sistema · sysstat-summary | HOST-X86 | sin conflicto por recurso |
| x86 · timer sistema · x86-localpath-pull | HOST-X86 | EN CONFLICTO: media en HOST-X86 |
| x86 · timer sistema · restic-hostpath-backup@ubuntu | HOST-X86 | EN CONFLICTO: baja en HOST-X86 |
| x86 · timer sistema · apt-daily-upgrade | HOST-X86 | EN CONFLICTO: baja en HOST-X86 |
| x86 · timer sistema · apt-daily | HOST-X86 | fuera del cálculo: hora aleatoria en 12 h (RandomizedDelay); 31–58 s |
| x86 · timer sistema · weekly-apt-upgrade | HOST-X86 | EN CONFLICTO: baja en HOST-X86 |
| x86 · timer sistema · e2scrub_all | HOST-X86 | EN CONFLICTO: baja en HOST-X86 |
| x86 · timer sistema · fstrim | HOST-X86 | EN CONFLICTO: media en HOST-X86 |
| x86 · timer sistema · tesla-fleet-watchdog | HOST-X86 | fuera del cálculo: timer disabled: no dispara |
| x86 · timer sistema · flannel-heal | HOST-X86 | fondo, cada 2 min (ocupación en la tabla de su recurso) |
| x86 · timer sistema · ext4-guard | HOST-X86 | fondo, cada 2 min (ocupación en la tabla de su recurso) |
| x86 · timer sistema · sysstat-collect | HOST-X86 | fondo, cada 10 min (ocupación en la tabla de su recurso) |
| x86 · timer sistema · github-app-token | HOST-X86, API-GITHUB | fondo, cada 45 min (ocupación en la tabla de su recurso) |
| x86 · timer sistema · fwupd-refresh | HOST-X86 | fuera del cálculo: hora aleatoria (RandomizedDelay 12 h); 0–1 s |
| hermes · global · Prep suplementación semanal | ROUTER | sin conflicto por recurso |
| hermes · global · HGH nocturna | ROUTER | sin conflicto por recurso |
| hermes · hogar · Buenos días Hogar | ROUTER | EN CONFLICTO: media en ROUTER |
| hermes · hogar · Seguimiento envíos | ROUTER | EN CONFLICTO: media en ROUTER |
| hermes · analista · pm-revision-diaria-backlog | ROUTER | EN CONFLICTO: baja en ROUTER |
| informe del VP 08:00 | propio (no compartido con otro nocturno) | fuera del cálculo: retirado (x86-host-runtime a40a329, 17-09) |
