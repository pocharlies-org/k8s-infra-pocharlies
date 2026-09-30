# INFRA-283 H3 (INFRA-338) — Propuesta de escalonamiento nocturno

`sre` la redactó el **30-09-2026 entre las 13:55 y las 14:25 CEST** a partir de `inventario.md` (H1) y
`conflictos.md` (H2), con lecturas nuevas donde hacía falta evidencia: logs de los Jobs retenidos,
VictoriaMetrics (48 h), `journalctl --user`, `systemctl cat` y el skill `backup-pvc-hub`. **Es una propuesta:
no se ha aplicado nada.** Cada cambio se abrirá como historia propia, con su PR GitOps en el repo dueño.

Cada horario propuesto se comprueba con `python3 verifica_propuesta.py` (en este mismo directorio). El script:

- expande cada horario nuevo con `cuenta_ventana.py`;
- recalcula el mapa de H2 antes y después, en una semana de **verano** (CEST) y otra de **invierno** (CET);
- comprueba las invariantes.

Su salida es la segunda mitad de este documento.

## Resultado en una línea por estación

| estación | pares en conflicto antes | después | invariantes |
|---|---|---|---|
| verano (CEST) | alta 1 · media 31 · baja 41 | **alta 0 · media 10 · baja 26** | las 4 se cumplen. Hoy incumplen la franja 04:50–05:10, en su peor caso, backup-runner y x86-localpath-pull |
| invierno (CET) | alta 1 · media 31 · baja 41 | **alta 0 · media 10 · baja 27** | las 4 se cumplen. Hoy la incumplen backup-runner y weekly-backup |

Se deshace el único par alto: el kit de recuperación × el backup de synapse, sobre el disco de sauvage y Google
Drive. También 22 de los 31 medios en verano (23 en invierno). De los medios que quedan, casi todos solo aparecen
cuando un trabajo ligero tiene una pasada atípica. Dos se dan también con la mediana: kit × sii-invoicing (5 min) y
memory-promotion × «Buenos días Hogar» (7 min). Todos se declaran como riesgo aceptado (§6).

## 1. Cambios propuestos (14 trabajos)

La columna «repo dueño» dice dónde iría la PR. Los timers del x86 se marcan aparte: su cambio no va a k8s.

| # | trabajo | repo dueño (dónde va el cambio) | hoy | propuesto | qué solape de H2 deshace (med/máx) |
|---|---|---|---|---|---|
| 1 | backup-hub/recovery-kit-to-drive | dgx-infra `k8s/backup/logical-dumps` | `30 21 * * *` Etc/UTC (23:30 CEST) | `5 22 * * *` Etc/UTC (00:05 CEST / 23:05 CET) | Pasa a correr detrás de todos los dumps. Deshace kit × localpath-x86-backup (10/12, todas las noches), kit × dump postgres-shared (0/9; 8 min reales el 28-09) y kit × dump semanal (15/18, dom). Con el nº 3, también kit × backup de synapse (**alta**, 81/111; 108 min reales el 29→30-09). Además corrige la carrera: hoy el kit empieza a copiar a las 23:31 con el dump del día aún escribiéndose (hasta 23:39) |
| 2 | libreplay/localpath-x86-backup | dgx-infra `k8s/backup/logical-dumps` | `40 21 * * *` Etc/UTC (23:40 CEST) | `30 20 * * *` Etc/UTC (22:30 CEST / 21:30 CET) | Deshace localpath × kit (10/12) y × dump semanal (10/12, dom). Queda antes del dump de postgres-shared (23:00) en `minio-0`. La familia de dumps sigue en UTC, así que el orden entre ellos se mantiene en invierno |
| 3 | synapse/synapse-skirmbooks-s3-drive-backup | k8s-synapse-pocharlies `k8s` | `15 */6 * * *` Europe/Madrid (4 pasadas de ~3 h) | `15 8,19 * * *` Europe/Madrid (2 pasadas, **fuera de la noche**) | Deshace el único par **alto** (kit × s3-backup, disco de sauvage), s3-backup × dreaming en el x86 (61/96), × backup-runner (9/15), × weekly-backup (39, dom), × drive-mirror (0/5), × sii-invoicing y picklist-close. Frecuencia de 4 a 2 pasadas: ver evidencia en §2 |
| 4 | skirmshop-brain-prod/skirmshop-brain-knowledge-pages | skirmshop-brain-k8s `apps/brain/overlays/prod` | `17 3,9,15,21 * * *` Europe/Madrid | `15 5,11,17,23 * * *` Europe/Madrid | Sale de la ventana del clasificador de dreaming también en su peor caso acotado (01:30–04:50, ver §4). Deshace knowledge × memory-promotion (router y brain, 0/6). Sigue después de dreaming y antes de las 08:00 |
| 5 | skirmshop-brain-prod/skirmshop-brain-memory-promotion | skirmshop-brain-k8s `apps/brain/overlays/prod` | `37 3,9,15,21 * * *` Europe/Madrid | `45 5,11,17,23 * * *` Europe/Madrid | Igual que el nº 4. Arranca cuando ha terminado knowledge-pages (máx. 05:42) y mantiene el orden knowledge → memory |
| 6 | skirmshop-brain-prod/skirmshop-brain-audit | skirmshop-brain-k8s `apps/brain/overlays/prod` | `30 4 * * *` Europe/Madrid | `30 3 * * *` Europe/Madrid | Deshace audit × personal-graph-enrichment (4/10), × claude-session-graph (0/3) y × rag-picqer-price-sync (2/3), todos en el brain. A las 03:30 el brain está libre |
| 7 | skirmshop/rag-provider-sourcing-backfill | k8s-skirmshopshopifyapp-pocharlies `k8s` | `30 4 * * *` Europe/Madrid | `45 3 * * *` Europe/Madrid | **Corrige a H2**: sí llama a la API de Shopify. El 30-09 su Job recibió `Shopify Admin GraphQL errors: Throttled` mientras `shopify-sync-warehouse` sincronizaba (04:17–04:35). A las 03:45 no hay otro trabajo contra Shopify |
| 8 | skirmshop/shopify-sync-weights | k8s-shopify-sync-pocharlies `k8s` | `41 */6 * * *` Europe/Madrid | `41 6 * * *` Europe/Madrid | Frecuencia de 4 a 1 pasada al día (evidencia en §2). Quita la pasada de las 00:41 |
| 9 | synapse/synapse-dlq-archive-purge | k8s-synapse-pocharlies `k8s` | `41 3 * * *` sin zona → UTC (05:41 CEST) | `41 5 * * 1` Europe/Madrid (lunes) | De diario a semanal (evidencia en §2). Fija la zona horaria |
| 10 | longhorn-system/weekly-backup | dgx-infra `k8s/backup/longhorn-recurring/recurringjob-default.yaml` (RecurringJob; se aplica a mano, sin ArgoCD) | `0 4 * * 0` UTC (dom 06:00 CEST / **05:00 CET**) | `0 5 * * 0` UTC (dom 07:00 CEST / 06:00 CET) | **En invierno hoy rompe la invariante**: 54 min de backup a su destino NFS en el x86, en plena franja 04:50–05:10. Deshace también weekly × s3-backup (39, dom) |
| 11 | kube-system/company-dreaming | k8s-infra-pocharlies `.` | `30 1 * * *` Europe/Madrid | **el horario no cambia**. `startingDeadlineSeconds` 43200 → 600 y `activeDeadlineSeconds` 21600 → 11400 | Acota su peor caso: como mucho arranca a las 01:40 y acaba a las 04:50, antes de blog-daily. Ver §4 |
| 12 | backup-runner.sh x86 (crontab) — **fuera de k8s** | crontab de `dibanez`; el script no está versionado. Si se versiona, x86-host-runtime | `0 3 * * *` | `50 22 * * *` | Su máximo (148 min, 29-09) llegó a las 05:27, dentro de la franja del blog: 8 min reales cruzados con blog-daily. Deshace × x86-localpath-pull (22), × blog-daily (8), × dreaming (6), × drive-mirror (5) y × s3-backup (15). Su peor caso pasa a acabar a las 01:18, antes de dreaming |
| 13 | x86-localpath-pull (timer del sistema) — **fuera de k8s** | dgx-infra `scripts/ovh-pvc-hub/x86-localpath-pull.timer` (se instala a mano, no es de x86-host-runtime) | `OnCalendar=*-*-* 02:30:00 UTC` | `OnCalendar=*-*-* 02:05:00 UTC` | Su máximo (22 min) acabó a las 04:52 CEST: en la franja del blog y **después** de que sauvage empezara a tirar del hub (`x86-hub-pull` a las 02:45 UTC, según el skill `backup-pvc-hub`). Así podía subirse a OVH un volcado a medias. Ahora acaba como tarde a las 02:27 UTC, antes de restic-hostpath (02:33 UTC) y del hub-pull, en las dos estaciones |
| 14 | fstrim (timer del sistema, paquete util-linux) — **fuera de k8s** | drop-in en `/etc/systemd/system/fstrim.timer.d/`; sin repo, x86-host-runtime si se versiona | `OnCalendar=weekly` + `RandomizedDelaySec=100min` (lun 00:00–01:40) | `OnCalendar=Mon 03:45` + `RandomizedDelaySec=0` | Deshace fstrim × dreaming, × s3-backup y × shopify-sync-warehouse (0/14 cada uno, noche del domingo) |

**Alternativa descartada para los nº 4 y 5.** Dejarlos a las 03:17 y 03:45 era el cambio mínimo, pero cruzaban el
peor caso acotado de dreaming (26 y 35 min). Anclarlos a las 0, 6, 12 y 18 h cumplía la invariante, pero creaba un par
alto con «Buenos días Hogar» (31 min).

## 2. Candidatos a días alternos o semanales

Solo se propone cambiar la frecuencia donde hay evidencia de que la pasada extra no aporta:

| trabajo | evidencia (logs de sus Jobs retenidos) | propuesta |
|---|---|---|
| synapse-skirmbooks-s3-drive-backup | Se miraron las pasadas del 30-09. La de 00:15 pasó 2 h 45 min listando (`0 B / 0 B`) y en 15 min subió **121,7 MiB**. La de 06:15 listó 2 h 36 min y subió **6,4 MiB** (32.223 objetos comprobados). El disco `md3` de sauvage está al 85–100 % de ocupación todas las horas (VictoriaMetrics, 48 h), con picos del 100 % a la 01:00, que es el cruce con el kit | 4 → **2 pasadas al día** (cambio nº 3). El RPO de la copia en Drive pasa de ≤ 6 h a ≤ 13 h. No se baja a 1 pasada: rebajar la protección de datos más allá es decisión de negocio |
| shopify-sync-weights | Pasadas 30-09 06:41 y 12:41: `matched=3823 to-update=0 … Nothing to update.` | 4 → **1 al día** (cambio nº 8) |
| synapse-dlq-archive-purge | Pasadas 29-09 y 30-09: `"purged": 0` | diaria → **semanal**, lunes (cambio nº 9) |

**Revisados y descartados**, porque la evidencia dice que la pasada diaria sí hace trabajo:

- **rag-taxonomy-canonicalize**: canoniza **los mismos 108 valores** (`brand_line`) cada noche, en modo WRITE; el
  inventario decía «dry-run». Es un síntoma de dos escritores peleándose, no de un trabajo sobrante. Espaciarlo no lo
  arregla (ver §6).
- **shopify-picqer-order-audit**: 3 hallazgos y 2 reparaciones manuales el 30-09.
- **searxng-autoupdate**: el 30-09 actualizó la imagen.
- **litellm-spendlogs-retention**: borró 4.194 filas.
- **langfuse-retention**: borró 311.
- **rag-parent-health**: es un monitor; su valor es detectar el día que falle.

**Sin evidencia** (sus Jobs no dejan logs útiles o ya no existen), así que no se proponen: affiliate-gdpr-prune,
picker-ga4-refresh, picker-retention, affiliate-sync-discounts, skirmshop-drive-mirror y
personal-graph-enrichment. Este último reconstruye el grafo entero cada pasada (`added=40827`), y eso no dice cuánto
cambia de un día a otro.

## 3. Riesgo de catch-up por cada trabajo modificado

Así funciona el controlador. Si un CronJob estuvo suspendido o el controlador caído, y no tiene
`startingDeadlineSeconds`, al volver lanza **inmediatamente** la última ejecución perdida. Es el efecto del 28-09:
`suspend:false` relanzó la ocurrencia de las 03:30, que ya estaba cubierta. **Cambiar el horario de un CronJob que ya
existe tiene el mismo efecto.** Si la hora nueva ya ha pasado hoy y es posterior al último disparo, cuenta como
perdida y se lanza al aplicar, salvo que el `startingDeadlineSeconds` sea menor que el tiempo transcurrido desde esa
hora nueva. Regla general: **aplicar cada cambio fuera del intervalo [hora nueva, hora nueva + startingDeadlineSeconds]**.
Aplicado de día, ninguno de los de abajo se dispara, salvo donde se indica.

| # | trabajo | startingDeadlineSeconds (hoy → propuesto) | tras suspensión o caída | al aplicar el cambio de horario |
|---|---|---|---|---|
| 1 | recovery-kit-to-drive | startingDeadlineSeconds: 1800 (no cambia) | Si vuelve antes de las 22:35 UTC, lanza la del día con retraso; si no, la pierde hasta la noche siguiente | La hora nueva (22:05 UTC) es posterior al último disparo (21:30 UTC): cuenta como perdida, pero con 1800 solo se lanzaría aplicando entre 22:05 y 22:35 UTC |
| 2 | localpath-x86-backup | startingDeadlineSeconds: 1800 (no cambia) | Igual, con franja 20:30–21:00 UTC | Adelanta la hora: no hay ocurrencia perdida. Aplicado entre 20:30 y 21:00 UTC correría en ese momento y ya no a las 21:40 |
| 3 | synapse-skirmbooks-s3-drive-backup | startingDeadlineSeconds: 900 (no cambia) | Una pasada perdida se recupera solo en los 15 min siguientes | Aplicado a las 14:00, la última hora nueva (08:15) es anterior al último disparo (12:15): no dispara |
| 4 | skirmshop-brain-knowledge-pages | startingDeadlineSeconds: 900 (no cambia) | Recupera en 15 min o espera a la siguiente, 6 h después | Aplicado a las 14:00: 11:15 queda después del último disparo (09:17), pero hace más de 900 s → no dispara. No aplicar entre hh:15 y hh:30 de las horas 5, 11, 17 y 23 |
| 5 | skirmshop-brain-memory-promotion | startingDeadlineSeconds: 900 (no cambia) | Igual que el nº 4 | No aplicar entre hh:45 y hh+1:00 de las horas 5, 11, 17 y 23 |
| 6 | skirmshop-brain-audit | startingDeadlineSeconds: 600 (no cambia) | Recupera en 10 min o espera al día siguiente | Aplicado de día no dispara (03:30 queda antes del último disparo, 04:30) |
| 7 | rag-provider-sourcing-backfill | startingDeadlineSeconds: 600 (no cambia) | Igual | No dispara (adelanta de 04:30 a 03:45) |
| 8 | shopify-sync-weights | startingDeadlineSeconds: 600 (no cambia) | Igual; ahora esperar a la siguiente es esperar 24 h | No dispara (06:41 queda antes del último disparo, 12:41) |
| 9 | synapse-dlq-archive-purge | startingDeadlineSeconds: **ausente → 3600** (en el mismo PR) | **Hoy**: al reanudar lanza al instante la purga perdida, a cualquier hora. Con 3600, solo en la hora siguiente | No dispara (el lunes 05:41 Madrid queda antes del último disparo diario); añadir el campo antes o junto con el horario |
| 10 | longhorn-system/weekly-backup | startingDeadlineSeconds: **ausente, no configurable** (el CronJob lo genera longhorn-manager a partir del RecurringJob). Riesgo aceptado | Al volver lanza el backup semanal perdido, a cualquier hora (54 min pesados en el x86 y en Longhorn) | De lunes a sábado, el domingo 05:00 UTC anterior es posterior al último disparo (domingo 04:00 UTC): **se lanzaría un backup semanal al aplicar**, si longhorn-manager actualiza el CronJob en sitio (no verificado). Para evitarlo: aplicar el domingo entre 04:00 y 05:00 UTC, o aceptar un backup extra |
| 11 | company-dreaming | startingDeadlineSeconds: **43200 → 600**; activeDeadlineSeconds 21600 → 11400 | **Hoy** una reanudación antes de las 13:30 lanza un pase de memorias de día (el efecto del 28-09 con 12 h de margen). Con 600, solo entre 01:30 y 01:40 | El horario no cambia: no hay ocurrencia perdida nueva |
| 12 | backup-runner.sh x86 | startingDeadlineSeconds: no aplica (cron no recupera ejecuciones perdidas) | Si el x86 está apagado a las 22:50, esa noche no hay backup (hoy pasa lo mismo a las 03:00) | El día del cambio corre dos veces (03:00 y 22:50): inofensivo |
| 13 | x86-localpath-pull | startingDeadlineSeconds: no aplica (timer systemd con `Persistent=true`) | Si el x86 estaba apagado, corre al arrancar. Así se explica el disparo de las 03:40 del 29-09 y sus 7 reintentos | Adelanta la hora: tras `daemon-reload` no hay disparo inmediato (el último fue a las 02:30 UTC) |
| 14 | fstrim | startingDeadlineSeconds: no aplica (timer systemd, `Persistent=true`) | Corre al arrancar si se saltó el lunes | Sin efecto inmediato |

## 4. Invariantes (revisión CTO)

- **`company-dreaming` sigue en `30 1 * * *`** Europe/Madrid (cambio nº 11: solo sus topes).
  - Justificación medida: sus dos pasadas medidas duran 96 min (29-09) y 25 min (30-09, fallida).
  - El tope de 190 min (`activeDeadlineSeconds` 11400) es el doble del máximo medido. Con `startingDeadlineSeconds`
    600 garantiza que **acaba antes de las 04:50**, antes de blog-daily a las 05:00.
- **Conflicto latente (peor caso de 5,5 h → 07:00) y su mitigación.** Hoy ese peor caso cruzaría:
  - en el router: memory-promotion (35 min), «Buenos días Hogar» (60), knowledge-pages (26), rag-nl-llm-matcher (21)
    y blog-daily (8);
  - en el x86: backup-runner (148).

  La mitigación es el tope del nº 11: dreaming no puede pasar de las 04:50. El coste es que una pasada que necesite
  más de 190 min se corta. No está medido qué hace dreaming al cortarse; lo único observado es la pasada fallida del
  30-09, que terminó con error sin más efectos. Lo que quede sin procesar entra en la pasada siguiente, si dreaming es
  incremental (**no verificado**).
- **Ningún trabajo pesado en 04:50–05:10**: el verificador da 0 en verano y en invierno. Hoy hay tres que lo
  incumplen, y los tres se corrigen: backup-runner (nº 12) y x86-localpath-pull (nº 13) en su peor caso, y
  weekly-backup en invierno (nº 10).
  **No verificable**: `x86-hub-pull` (02:45 UTC) y Veeam (03:15 UTC) corren en el host sauvage. H1 no los
  inventarió (sre no tiene acceso a sauvage) y no hay duración medida. Según el skill `backup-pvc-hub` son 04:45 y
  05:15 CEST. No cargan el x86, pero sí el disco de sauvage.
- **Informe del VP a las 08:00**: H1 lo encontró **retirado** (x86-host-runtime `a40a329`), así que la invariante
  sigue **NO verificada**. Las memorias siguen frescas antes de las 08:00: la pasada de memory-promotion de las 05:45
  acaba como tarde a las 06:20.
- **Los one-shot de inferencia no coinciden con la ventana del clasificador de dreaming**: 0 cruces con la ventana
  medida (01:30–03:06) y 0 con el peor caso acotado (01:30–04:50), en las dos estaciones. El patrón del aborto del
  27-09 queda cubierto también en el peor caso.

## 5. Los 18 CronJobs de la ventana sin `startingDeadlineSeconds`

H1 volvió a medirlos: son 18, no 19. Recomendación para cada uno:

| CronJob | periodo | recomendación |
|---|---|---|
| chat/reconcile-chat-catalog | cada 15 min | startingDeadlineSeconds 300. Sin él: al volver, una pasada inmediata (reconciliador idempotente). Riesgo bajo |
| kube-system/descheduler | cada 2 min | startingDeadlineSeconds 60, con el valor del chart del descheduler. Riesgo bajo |
| kube-system/sauvage-pod-reaper | cada 15 min | startingDeadlineSeconds 300. Riesgo bajo |
| kube-system/sauvage-zombie-watchdog | cada 5 min | startingDeadlineSeconds 120. Riesgo bajo |
| longhorn-system/longhorn-no-snapshot-reconciler | cada 20 min | startingDeadlineSeconds 600. Su fila es un CronJob propio de dgx-infra, no uno generado por Longhorn. Riesgo bajo |
| skirmshop/labels-synapse-pod-reaper | cada 10 min | startingDeadlineSeconds 300. Riesgo bajo |
| skirmshop/labels-tracking-poll-scheduler | cada 15 min | startingDeadlineSeconds 300. Riesgo bajo |
| synapse/synapse-outbox-gc | cada hora | startingDeadlineSeconds 600. Riesgo bajo |
| chat/chat-tools-check | diario 04:30 | startingDeadlineSeconds 600. Sin él, una reanudación de día lanza el chequeo a destiempo. Riesgo bajo |
| langfuse/langfuse-clickhouse-retention | diario 05:30 | startingDeadlineSeconds 600. Sin él, un DELETE de retención en ClickHouse en horario de uso. **Recomendado** |
| langfuse/langfuse-retention | diario 06:00 | startingDeadlineSeconds 600. Mismo motivo (borró 311 el 30-09). **Recomendado** |
| litellm/litellm-spendlogs-retention | diario 05:40 | startingDeadlineSeconds 600. Mismo motivo: un DELETE de ~4.000 filas en el Postgres compartido. **Recomendado** |
| skirmshop-product-relations/brain-product-relations-projector | diario 05:17 | startingDeadlineSeconds 600. **Recomendado** |
| synapse/synapse-dlq-archive-purge | pasa a semanal | startingDeadlineSeconds 3600 (cambio nº 9) |
| longhorn-system/default | diario 04:00 | no configurable (lo genera longhorn-manager). Riesgo aceptado: un snapshot inmediato al volver (1,6 min) |
| longhorn-system/openclaw-workspace-precutover-snapshot | diario 04:15 | no configurable. Riesgo aceptado: un snapshot inmediato (4 s) |
| longhorn-system/sc80-drill-snap | cada 5 min | no configurable. Riesgo aceptado |
| longhorn-system/weekly-backup | semanal | no configurable. Riesgo aceptado y documentado en la fila 10 de §3 |

## 6. Riesgos aceptados y hallazgos que no se arreglan con horarios

**Medios que quedan** (tabla «Quedan…» del verificador). Salvo los dos que se dan también con la mediana
(sii-invoicing × kit y «Buenos días Hogar» × memory-promotion), salen del máximo atípico de un trabajo ligero:

- **picker-picklist-close** (cada hora, mediana 69 s) × kit, × dump de postgres-shared y × picker-purchase-signals.
- **sii-invoicing** × kit: 5 min, pods ligeros de sauvage. Cualquier pesado en sauvage se cruza con ellos.
- **backup-runner** × shopify-sync-warehouse: 22 min, solo si el backup es atípico.
- **warehouse** × x86-localpath-pull (10) y **drive-mirror** × x86-localpath-pull (5, invierno): solo si el pull es
  atípico (su mediana son 9 s).
- **«Buenos días Hogar»** (Hermes, mediana 7 min, máx. 71) × Seguimiento envíos (0/11), × rag-nl-llm-matcher (0/21) y
  × memory-promotion (7/20). Los horarios de Hermes viven en su `jobs.json` (PVC, sin repo).

**Hallazgos que no son de horario** (van en historias aparte, si se quiere):

- **Router**: lo satura el tráfico de agentes, no el calendario (H2: `claude-local` y `hermes` en el fallo de dreaming
  del 30-09). Ningún cambio de horario lo resuelve.
- **Disco de sauvage** (`md3`): está al 85–100 % todo el día. Repartir la noche quita picos, pero no crea margen.
- **synapse-skirmbooks-s3-drive-backup**: el 92 % de cada pasada es listar. Es configuración de rclone
  (`--fast-list`, o `--max-age` para pasadas incrementales) en k8s-synapse-pocharlies.
- **rag-taxonomy-canonicalize**: reescribe los mismos 108 `brand_line` cada noche. Otro proceso los vuelve a desviar
  a diario; hay que buscar quién.
- **cloudflare-ddns.sh** (crontab x86, cada 5 min): **el horario no cambia; el fallo es de lógica.**
  - Compara la IP pública con la resolución DNS de un registro con proxy (104.21.78.58 es el borde de Cloudflare). Por
    eso ve un cambio en cada pasada y reescribe `dgx.e-dani.com` 288 veces al día.
  - Arreglo: comparar con el contenido del registro leído por la API de Cloudflare (dgx-infra
    `scripts/cloudflare-ddns.sh`, rama `fase2-dominios`).
  - `home-ddns` (k8s, cada 15 min) hace el mismo trabajo para `webhooks.e-dani.com`: se podrían unificar.
- **browser-harness-daily-update**: el 30-09 terminó con `CONFLICT (content): Merge conflict in manifest.json`, así que
  la actualización no se aplicó. El horario no cambia.
- **Cambio de hora**: 60 CronJobs usan UTC (22 `Etc/UTC` y 38 sin campo), así que en invierno corren una hora antes
  en hora local. Por eso la propuesta se verifica en las dos estaciones, y la familia de dumps y el kit se quedan
  **en UTC** a propósito, para mantener su orden relativo. Fijar `timeZone` en todos es otra historia, y habría que
  volver a pasar este verificador.
- **Timers del host sauvage** (`x86-hub-pull`, Veeam, frescura del hub): faltan en el inventario. Hacen falta para
  cerrar la invariante 04:50–05:10 en sauvage; su lectura necesita acceso a sauvage.

## 7. Historias de implementación previstas, por repo dueño

Cada una con su PR contra el tronco que lea ArgoCD; se comprueba al abrirla.

- **dgx-infra** (`master`):
  - kit y localpath-x86-backup (nº 1 y 2), en `k8s/backup/logical-dumps`;
  - weekly-backup (nº 10), en el RecurringJob, que se aplica a mano;
  - x86-localpath-pull (nº 13), en `scripts/ovh-pvc-hub`, con instalación manual del timer;
  - `startingDeadlineSeconds` de no-snapshot-reconciler.
- **k8s-synapse-pocharlies**: s3-drive-backup (nº 3), dlq-archive-purge (nº 9) y el `startingDeadlineSeconds` de
  outbox-gc.
- **skirmshop-brain-k8s**: knowledge-pages, memory-promotion y audit (nº 4–6).
- **k8s-skirmshopshopifyapp-pocharlies**: rag-provider-sourcing-backfill (nº 7).
- **k8s-shopify-sync-pocharlies**: shopify-sync-weights (nº 8).
- **k8s-infra-pocharlies**: los topes de company-dreaming (nº 11) y el `startingDeadlineSeconds` de
  sauvage-pod-reaper y sauvage-zombie-watchdog.
- **x86-host-runtime**, o el host si no se versiona: crontab de backup-runner (nº 12) y drop-in de fstrim (nº 14).
- **Higiene de `startingDeadlineSeconds`** (§5): chat (dgx-infra), langfuse-k8s, k8s-litellm-pocharlies,
  skirmshop-brain-k8s (product-relations), k8s-shopify-label-pocharlies, descheduler.

## 8. Comprobación generada

Salida literal de `python3 .company/specs/INFRA-283/verifica_propuesta.py`.

<!-- generado por verifica_propuesta.py -->

### Expansión con `cuenta_ventana.py` de cada horario de CronJob propuesto

**verano** (semana del 28-09):

| CronJob | schedule · timeZone | disparos en 22:00–08:00 (7 días) | horas locales en la ventana |
|---|---|---|---|
| backup-hub/recovery-kit-to-drive | `5 22 * * *` · UTC | 7 | 00:05 |
| libreplay/localpath-x86-backup | `30 20 * * *` · UTC | 7 | 22:30 |
| synapse/synapse-skirmbooks-s3-drive-backup | `15 8,19 * * *` · Europe/Madrid | 0 | ninguna (fuera de la ventana a propósito) |
| skirmshop-brain-prod/skirmshop-brain-knowledge-pages | `15 5,11,17,23 * * *` · Europe/Madrid | 14 | 05:15, 23:15 |
| skirmshop-brain-prod/skirmshop-brain-memory-promotion | `45 5,11,17,23 * * *` · Europe/Madrid | 14 | 05:45, 23:45 |
| skirmshop-brain-prod/skirmshop-brain-audit | `30 3 * * *` · Europe/Madrid | 7 | 03:30 |
| skirmshop/rag-provider-sourcing-backfill | `45 3 * * *` · Europe/Madrid | 7 | 03:45 |
| skirmshop/shopify-sync-weights | `41 6 * * *` · Europe/Madrid | 7 | 06:41 |
| synapse/synapse-dlq-archive-purge | `41 5 * * 1` · Europe/Madrid | 1 | 05:41 |
| longhorn-system/weekly-backup | `0 5 * * 0` · UTC | 1 | 07:00 |

**invierno** (semana del 02-11):

| CronJob | schedule · timeZone | disparos en 22:00–08:00 (7 días) | horas locales en la ventana |
|---|---|---|---|
| backup-hub/recovery-kit-to-drive | `5 22 * * *` · UTC | 7 | 23:05 |
| libreplay/localpath-x86-backup | `30 20 * * *` · UTC | 0 | ninguna (fuera de la ventana a propósito) |
| synapse/synapse-skirmbooks-s3-drive-backup | `15 8,19 * * *` · Europe/Madrid | 0 | ninguna (fuera de la ventana a propósito) |
| skirmshop-brain-prod/skirmshop-brain-knowledge-pages | `15 5,11,17,23 * * *` · Europe/Madrid | 14 | 05:15, 23:15 |
| skirmshop-brain-prod/skirmshop-brain-memory-promotion | `45 5,11,17,23 * * *` · Europe/Madrid | 14 | 05:45, 23:45 |
| skirmshop-brain-prod/skirmshop-brain-audit | `30 3 * * *` · Europe/Madrid | 7 | 03:30 |
| skirmshop/rag-provider-sourcing-backfill | `45 3 * * *` · Europe/Madrid | 7 | 03:45 |
| skirmshop/shopify-sync-weights | `41 6 * * *` · Europe/Madrid | 7 | 06:41 |
| synapse/synapse-dlq-archive-purge | `41 5 * * 1` · Europe/Madrid | 1 | 05:41 |
| longhorn-system/weekly-backup | `0 5 * * 0` · UTC | 1 | 06:00 |

### Verano (CEST): noches del 28-09 al 04-10-2026

- pares en conflicto ANTES: alta 1 · media 31 · baja 41 · DESPUÉS: alta 0 · media 10 · baja 26

**Deshechos o rebajados (antes → después)** (23; los que eran `baja` y desaparecen no se listan):

| recurso | par | antes | después |
|---|---|---|---|
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × synapse/synapse-skirmbooks-s3-drive-backup | alta 81/111 min | sin cruce |
| API-DRIVE | backup-hub/recovery-kit-to-drive × synapse/synapse-skirmbooks-s3-drive-backup | media 81/111 min | sin cruce |
| BRAIN | skirmshop-brain-prod/skirmshop-brain-audit × skirmshop-brain-prod/skirmshop-brain-personal-graph-enrichment | media 4/10 min | sin cruce |
| BRAIN | skirmshop-brain-prod/skirmshop-brain-knowledge-pages × skirmshop-brain-prod/skirmshop-brain-memory-promotion | media 0/6 min | sin cruce |
| DISCO-DRIVE-S3 | backup-hub/skirmshop-drive-mirror × synapse/synapse-skirmbooks-s3-drive-backup | media 0/5 min | sin cruce |
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × databases/logical-dump-postgres-shared | media 0/9 min | sin cruce |
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × databases/logical-dump-postgres-shared-weekly | media 15/18 min | sin cruce |
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × libreplay/localpath-x86-backup | media 10/12 min | sin cruce |
| DISCO-SAUVAGE | backup-hub/skirmshop-drive-mirror × synapse/synapse-skirmbooks-s3-drive-backup | media 0/5 min | sin cruce |
| DISCO-SAUVAGE | databases/logical-dump-postgres-shared-weekly × libreplay/localpath-x86-backup | media 10/12 min | sin cruce |
| DISCO-SAUVAGE | skirmshop/picker-picklist-close × synapse/synapse-skirmbooks-s3-drive-backup | media 1/6 min | sin cruce |
| DISCO-SAUVAGE | skirmshop/sii-invoicing × synapse/synapse-skirmbooks-s3-drive-backup | media 5/6 min | sin cruce |
| HOST-X86 | backup-hub/skirmshop-drive-mirror × backup-runner.sh x86 | media 0/5 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × blog-daily | media 0/8 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × kube-system/company-dreaming | media 0/6 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × synapse/synapse-skirmbooks-s3-drive-backup | media 9/15 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × x86-localpath-pull | media 0/22 min | sin cruce |
| HOST-X86 | fstrim × kube-system/company-dreaming | media 0/14 min | sin cruce |
| HOST-X86 | fstrim × skirmshop/shopify-sync-warehouse | media 0/14 min | sin cruce |
| HOST-X86 | fstrim × synapse/synapse-skirmbooks-s3-drive-backup | media 0/14 min | sin cruce |
| HOST-X86 | kube-system/company-dreaming × synapse/synapse-skirmbooks-s3-drive-backup | media 61/96 min | sin cruce |
| HOST-X86 | longhorn-system/weekly-backup × synapse/synapse-skirmbooks-s3-drive-backup | media 39/39 min | sin cruce |
| ROUTER | skirmshop-brain-prod/skirmshop-brain-knowledge-pages × skirmshop-brain-prod/skirmshop-brain-memory-promotion | media 0/6 min | sin cruce |

**Nuevos o agravados** (5; los que eran `baja` y desaparecen no se listan):

| recurso | par | antes | después |
|---|---|---|---|
| ROUTER | Buenos días Hogar × skirmshop-brain-prod/skirmshop-brain-memory-promotion | — | media 7/20 min (todas) |
| BRAIN | skirmshop-brain-prod/skirmshop-brain-memory-promotion × skirmshop-brain-prod/skirmshop-brain-neural-gardener-skirmshop | — | baja 0/<1 min (todas) |
| HOST-X86 | backup-runner.sh x86 × logrotate | — | baja 0/<1 min (todas) |
| HOST-X86 | backup-runner.sh x86 × opencode/logical-dump-opencode | — | baja 0/1 min (todas) |
| HOST-X86 | browser-harness-daily-update × x86-localpath-pull | — | baja 0/<1 min (todas) |

**Quedan en media o alta después** (10):

| recurso | par | solape med/máx | noches |
|---|---|---|---|
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × skirmshop/picker-picklist-close | media 1/6 min | todas |
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × skirmshop/sii-invoicing | media 5/6 min | todas |
| DISCO-SAUVAGE | databases/logical-dump-postgres-shared × skirmshop/picker-picklist-close | media 1/6 min | todas |
| HOST-X86 | backup-runner.sh x86 × skirmshop/shopify-sync-warehouse | media 0/22 min | todas |
| HOST-X86 | skirmshop/shopify-sync-warehouse × x86-localpath-pull | media 0/10 min | todas |
| PG | databases/logical-dump-postgres-shared × skirmshop/picker-picklist-close | media 1/6 min | todas |
| PG | skirmshop/picker-picklist-close × skirmshop/picker-purchase-signals | media 1/6 min | todas |
| ROUTER | Buenos días Hogar × Seguimiento envíos | media 0/11 min | todas |
| ROUTER | Buenos días Hogar × skirmshop-brain-prod/skirmshop-brain-memory-promotion | media 7/20 min | todas |
| ROUTER | Buenos días Hogar × skirmshop/rag-nl-llm-matcher | media 0/21 min | todas |

#### Invariantes — Verano (CEST): noches del 28-09 al 04-10-2026

- dreaming en `30 1 * * *` Europe/Madrid: SÍ
- pesados cruzando 04:50–05:10: 0
- one-shots de inferencia en la ventana medida del clasificador (01:30–03:06): 0
- one-shots de inferencia en el peor caso acotado por la propuesta (01:30 + 10 min de arranque + 190 min = 04:50): 0

### Invierno (CET): noches del 02-11 al 08-11-2026

- pares en conflicto ANTES: alta 1 · media 31 · baja 41 · DESPUÉS: alta 0 · media 10 · baja 27

**Deshechos o rebajados (antes → después)** (24; los que eran `baja` y desaparecen no se listan):

| recurso | par | antes | después |
|---|---|---|---|
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × synapse/synapse-skirmbooks-s3-drive-backup | alta 21/51 min | sin cruce |
| API-DRIVE | backup-hub/recovery-kit-to-drive × synapse/synapse-skirmbooks-s3-drive-backup | media 21/51 min | sin cruce |
| BRAIN | skirmshop-brain-prod/skirmshop-brain-audit × skirmshop-brain-prod/skirmshop-brain-personal-graph-enrichment | media 4/10 min | sin cruce |
| BRAIN | skirmshop-brain-prod/skirmshop-brain-knowledge-pages × skirmshop-brain-prod/skirmshop-brain-memory-promotion | media 0/6 min | sin cruce |
| DISCO-DRIVE-S3 | backup-hub/skirmshop-drive-mirror × synapse/synapse-skirmbooks-s3-drive-backup | media 0/5 min | sin cruce |
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × databases/logical-dump-postgres-shared | media 0/9 min | sin cruce |
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × databases/logical-dump-postgres-shared-weekly | media 15/18 min | sin cruce |
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × libreplay/localpath-x86-backup | media 10/12 min | sin cruce |
| DISCO-SAUVAGE | backup-hub/skirmshop-drive-mirror × synapse/synapse-skirmbooks-s3-drive-backup | media 0/5 min | sin cruce |
| DISCO-SAUVAGE | databases/logical-dump-postgres-shared-weekly × libreplay/localpath-x86-backup | media 10/12 min | sin cruce |
| DISCO-SAUVAGE | skirmshop/picker-picklist-close × synapse/synapse-skirmbooks-s3-drive-backup | media 1/6 min | sin cruce |
| DISCO-SAUVAGE | skirmshop/sii-invoicing × synapse/synapse-skirmbooks-s3-drive-backup | media 5/6 min | sin cruce |
| HOST-X86 | backup-hub/skirmshop-drive-mirror × backup-runner.sh x86 | media 0/5 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × blog-daily | media 0/8 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × kube-system/company-dreaming | media 0/6 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × longhorn-system/weekly-backup | media 0/28 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × synapse/synapse-skirmbooks-s3-drive-backup | media 9/15 min | sin cruce |
| HOST-X86 | backup-runner.sh x86 × x86-localpath-pull | media 0/22 min | sin cruce |
| HOST-X86 | blog-daily × longhorn-system/weekly-backup | media 5/8 min | sin cruce |
| HOST-X86 | fstrim × kube-system/company-dreaming | media 0/14 min | sin cruce |
| HOST-X86 | fstrim × skirmshop/shopify-sync-warehouse | media 0/14 min | sin cruce |
| HOST-X86 | fstrim × synapse/synapse-skirmbooks-s3-drive-backup | media 0/14 min | sin cruce |
| HOST-X86 | kube-system/company-dreaming × synapse/synapse-skirmbooks-s3-drive-backup | media 61/96 min | sin cruce |
| ROUTER | skirmshop-brain-prod/skirmshop-brain-knowledge-pages × skirmshop-brain-prod/skirmshop-brain-memory-promotion | media 0/6 min | sin cruce |

**Nuevos o agravados** (8; los que eran `baja` y desaparecen no se listan):

| recurso | par | antes | después |
|---|---|---|---|
| HOST-X86 | backup-hub/skirmshop-drive-mirror × x86-localpath-pull | — | media 0/5 min (todas) |
| ROUTER | Buenos días Hogar × skirmshop-brain-prod/skirmshop-brain-memory-promotion | — | media 7/20 min (todas) |
| BRAIN | skirmshop-brain-prod/skirmshop-brain-memory-promotion × skirmshop-brain-prod/skirmshop-brain-neural-gardener-skirmshop | — | baja 0/<1 min (todas) |
| HOST-X86 | apt-daily-upgrade × longhorn-system/weekly-backup | — | baja 1/1 min (sáb→dom) |
| HOST-X86 | backup-runner.sh x86 × logrotate | — | baja 0/<1 min (todas) |
| HOST-X86 | e2scrub_all × x86-localpath-pull | — | baja 0/<1 min (sáb→dom) |
| HOST-X86 | kube-system/company-dreaming × x86-localpath-pull | — | baja 0/1 min (todas) |
| HOST-X86 | longhorn-system/weekly-backup × skirmshop/shopify-sync-weights | — | baja <1/<1 min (sáb→dom) |

**Quedan en media o alta después** (10):

| recurso | par | solape med/máx | noches |
|---|---|---|---|
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × skirmshop/picker-picklist-close | media 1/6 min | todas |
| DISCO-SAUVAGE | backup-hub/recovery-kit-to-drive × skirmshop/sii-invoicing | media 5/6 min | todas |
| DISCO-SAUVAGE | databases/logical-dump-postgres-shared × skirmshop/picker-picklist-close | media 1/6 min | todas |
| HOST-X86 | backup-hub/skirmshop-drive-mirror × x86-localpath-pull | media 0/5 min | todas |
| HOST-X86 | backup-runner.sh x86 × skirmshop/shopify-sync-warehouse | media 0/22 min | todas |
| PG | databases/logical-dump-postgres-shared × skirmshop/picker-picklist-close | media 1/6 min | todas |
| PG | skirmshop/picker-picklist-close × skirmshop/picker-purchase-signals | media 1/6 min | todas |
| ROUTER | Buenos días Hogar × Seguimiento envíos | media 0/11 min | todas |
| ROUTER | Buenos días Hogar × skirmshop-brain-prod/skirmshop-brain-memory-promotion | media 7/20 min | todas |
| ROUTER | Buenos días Hogar × skirmshop/rag-nl-llm-matcher | media 0/21 min | todas |

#### Invariantes — Invierno (CET): noches del 02-11 al 08-11-2026

- dreaming en `30 1 * * *` Europe/Madrid: SÍ
- pesados cruzando 04:50–05:10: 0
- one-shots de inferencia en la ventana medida del clasificador (01:30–03:06): 0
- one-shots de inferencia en el peor caso acotado por la propuesta (01:30 + 10 min de arranque + 190 min = 04:50): 0

### Tabla completa: una fila por cada fila del inventario, agrupada por repo dueño

**Ubuntu (paquetes del sistema)**

| job | horario actual | propuesta |
|---|---|---|
| x86 · /etc/crontab · run-parts cron.daily | `25 6 * * *` (root; sin anacron instalado, así que corre)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · dpkg-db-backup | `OnCalendar 00:00` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · logrotate | `OnCalendar 00:00` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · man-db | `OnCalendar 00:00` + RandomizedDelay` hora local del host (Europe/Madrid) | no cambia (hora aleatoria en toda la noche (RandomizedDelay); 3 s) |
| x86 · timer sistema · sysstat-summary | `OnCalendar 00:07` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · apt-daily-upgrade | `OnCalendar 06:00` + RandomizedDelay` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · apt-daily | `OnCalendar 06:00,18:00` + RandomizedDelay 12 h` hora local del host (Europe/Madrid) | no cambia (hora aleatoria en 12 h (RandomizedDelay); 31–58 s) |
| x86 · timer sistema · e2scrub_all | `OnCalendar Sun 03:10` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · fstrim | `OnCalendar Mon 00:00` + RandomizedDelay` hora local del host (Europe/Madrid) | **cambia** → `45 3 * * 1` Europe/Madrid (ver tabla de cambios) |
| x86 · timer sistema · sysstat-collect | `OnCalendar */10 min` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · fwupd-refresh | `OnCalendar` + RandomizedDelay 12 h` hora local del host (Europe/Madrid) | no cambia (hora aleatoria (RandomizedDelay 12 h); 0–1 s) |

**descheduler**

| job | horario actual | propuesta |
|---|---|---|
| kube-system/descheduler | `*/2 * * * *` sin campo → UTC | no cambia |

**dgx-infra**

| job | horario actual | propuesta |
|---|---|---|
| chat/reconcile-chat-catalog | `*/15 * * * *` Europe/Madrid | no cambia |
| control-nexus/github-token-refresh | `*/30 * * * *` sin campo → UTC | no cambia |
| control-nexus/home-ddns | `*/15 * * * *` sin campo → UTC | no cambia |
| longhorn-system/longhorn-no-snapshot-reconciler | `*/20 * * * *` Etc/UTC | no cambia |
| longhorn-system/sc80-drill-snap | `*/5 * * * *` sin campo → UTC | no cambia |
| renovate/github-token-refresh | `*/30 * * * *` sin campo → UTC | no cambia (suspendido) |
| databases/logical-dump-postgres-shared | `0 21 * * *` Etc/UTC | no cambia |
| keycloak/logical-dump-keycloak-postgres | `10 21 * * *` Etc/UTC | no cambia |
| aiops/logical-dump-aiops | `20 21 * * *` Etc/UTC | no cambia (suspendido) |
| opencode/logical-dump-opencode | `20 21 * * *` Etc/UTC | no cambia |
| backup-hub/recovery-kit-to-drive | `30 21 * * *` Etc/UTC | **cambia** → `5 22 * * *` UTC (ver tabla de cambios) |
| databases/logical-dump-postgres-shared-weekly | `40 21 * * 0` Etc/UTC | no cambia |
| libreplay/localpath-x86-backup | `40 21 * * *` Etc/UTC | **cambia** → `30 20 * * *` UTC (ver tabla de cambios) |
| longhorn-system/default | `0 2 * * *` sin campo → UTC | no cambia |
| chat/searxng-autoupdate | `17 4 * * *` Europe/Madrid | no cambia |
| chat/chat-tools-check | `30 4 * * *` Europe/Madrid | no cambia |
| update-watch/update-watch | `15 5 * * *` Europe/Madrid | no cambia |
| renovate/renovate | `45 5 * * *` Europe/Madrid | no cambia |
| longhorn-system/weekly-backup | `0 4 * * 0` sin campo → UTC | **cambia** → `0 5 * * 0` UTC (ver tabla de cambios) |
| x86 · crontab · cloudflare-ddns.sh | `*/5 * * * *` (crontab de dibanez)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · x86-localpath-pull | `OnCalendar 02:30 UTC` UTC (04:30 CEST) | **cambia** → `5 2 * * *` UTC (ver tabla de cambios) |
| x86 · timer sistema · restic-hostpath-backup@ubuntu | `OnCalendar 02:30 UTC` + RandomizedDelay` UTC (04:30 CEST) | no cambia |
| x86 · timer sistema · weekly-apt-upgrade | `OnCalendar Sat 04:30` + retraso observado` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · ext4-guard | `periódico, intervalo medido (~2 min)` hora local del host (Europe/Madrid) | no cambia |

**k8s-infra-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| keycloak/keycloak-role-drift | `*/15 * * * *` Etc/UTC | no cambia |
| kube-system/sauvage-pod-reaper | `*/15 * * * *` sin campo → UTC | no cambia |
| kube-system/sauvage-zombie-watchdog | `*/5 * * * *` sin campo → UTC | no cambia |
| kube-system/company-dreaming | `30 1 * * *` Europe/Madrid | **horario no cambia** (`30 1 * * *`); cambian `startingDeadlineSeconds` y `activeDeadlineSeconds` (ver tabla de cambios) |
| longhorn-system/openclaw-workspace-precutover-snapshot | `15 2 * * *` sin campo → UTC | no cambia |

**k8s-litellm-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| litellm/litellm-watchdog | `*/10 * * * *` Europe/Madrid | no cambia |
| litellm/litellm-spendlogs-retention | `40 3 * * *` Etc/UTC | no cambia |

**k8s-observability-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| monitoring/keepsvc-stale-reaper | `*/15 * * * *` Europe/Madrid | no cambia |
| monitoring/keepsvc-maintenance-window | `50 3 * * *` Europe/Madrid | no cambia |
| aurora/aurorasvc-brain-kb-sync | `15 5 * * *` Europe/Madrid | no cambia |

**k8s-shopify-affiliate-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/affiliate-gdpr-prune | `0 3 * * *` Europe/Madrid | no cambia |
| skirmshop/affiliate-sync-discounts | `15 3 * * *` Europe/Madrid | no cambia |

**k8s-shopify-back-in-stock-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/back-in-stock-preorder-hold-reconcile | `*/10 * * * *` sin campo → UTC | no cambia |
| skirmshop/back-in-stock-preorder-coverage-reconcile | `3-59/10 * * * *` sin campo → UTC | no cambia |
| skirmshop/back-in-stock-backorder-enroll | `15 */6 * * *` sin campo → UTC | no cambia (suspendido) |

**k8s-shopify-chatbot-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/chatbot-sync | `*/5 * * * *` Europe/Madrid | no cambia |

**k8s-shopify-label-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/labels-deep-monitor | `*/15 * * * *` Etc/UTC | no cambia |
| skirmshop/labels-ops-edit-hold-reconciler | `*/2 * * * *` Etc/UTC | no cambia |
| skirmshop/labels-pickup-point-reminder | `*/2 * * * *` Etc/UTC | no cambia |
| skirmshop/labels-synapse-pod-reaper | `*/10 * * * *` sin campo → UTC | no cambia |
| skirmshop/labels-tracking-poll-scheduler | `*/15 * * * *` sin campo → UTC | no cambia |
| skirmshop/labels-vat-sync | `0 3 * * 0` Etc/UTC | no cambia |

**k8s-shopify-picker-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/picker-picklist-close | `0 * * * *` Europe/Madrid | no cambia |
| skirmshop/picker-ga4-refresh | `30 3 * * *` Europe/Madrid | no cambia |
| skirmshop/picker-purchase-signals | `0 4 * * *` Europe/Madrid | no cambia |
| skirmshop/picker-retention | `0 5 * * *` Europe/Madrid | no cambia |
| skirmshop/picker-purchase-recommend | `0 6 * * 1` Europe/Madrid | no cambia (suspendido) |

**k8s-shopify-sii-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/sii-invoicing | `0 1 * * *` Europe/Madrid | no cambia |
| skirmshop/sii-monthly-report | `10 1 1 * *` Europe/Madrid | no cambia |

**k8s-shopify-sync-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/shopify-sync-warehouse | `17 */4 * * *` Europe/Madrid | no cambia |
| skirmshop/shopify-sync-weights | `41 */6 * * *` Europe/Madrid | **cambia** → `41 6 * * *` Europe/Madrid (ver tabla de cambios) |
| skirmshop/shopify-picqer-order-audit | `30 2 * * *` Europe/Madrid | no cambia |

**k8s-skirmbooks-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/skirmbooks-dehu-fetch | `*/15 * * * *` Europe/Madrid | no cambia |
| skirmshop/skirmbooks-reconcile-sweep | `*/15 * * * *` sin campo → UTC | no cambia |
| skirmshop/skirmbooks-accounting-sweep | `7,22,37,52 * * * *` sin campo → UTC | no cambia |
| skirmshop/skirmbooks-deh-poll-night | `15 22 * * *` Europe/Madrid | no cambia |
| skirmshop/skirmbooks-classifier-sweep | `0 3 * * *` sin campo → UTC | no cambia |
| skirmshop/skirmbooks-deh-poll-morning | `15 5 * * *` Europe/Madrid | no cambia |
| skirmshop/skirmbooks-banking-klarna-sync | `17 3 * * *` sin campo → UTC | no cambia |
| skirmshop/skirmbooks-banking-paypal-sync | `23 3 * * *` sin campo → UTC | no cambia |
| skirmshop/skirmbooks-inventory-snapshot | `0 4 3 * *` sin campo → UTC | no cambia |
| skirmshop/skirmbooks-patterns-weekly | `0 4 * * 1` sin campo → UTC | no cambia |

**k8s-skirmshop-drive-mirror-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| backup-hub/skirmshop-drive-s3-to-drive | `*/15 * * * *` Europe/Madrid | no cambia (suspendido) |
| backup-hub/skirmshop-drive-mirror | `10 3 * * *` Europe/Madrid | no cambia |

**k8s-skirmshopshopifyapp-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop/rag-taxonomy-canonicalize | `30 2 * * *` Europe/Madrid | no cambia |
| skirmshop/rag-redirect-health | `15 4 * * 1` Europe/Madrid | no cambia |
| skirmshop/rag-picqer-price-sync | `30 4 * * *` Europe/Madrid | no cambia |
| skirmshop/rag-provider-sourcing-backfill | `30 4 * * *` Europe/Madrid | **cambia** → `45 3 * * *` Europe/Madrid (ver tabla de cambios) |
| skirmshop/rag-competitor-llm-matcher | `30 5 * * *` Europe/Madrid | no cambia (suspendido) |
| skirmshop/rag-parent-health | `20 6 * * *` Europe/Madrid | no cambia |
| skirmshop/rag-nl-llm-matcher | `30 6 * * *` Europe/Madrid | no cambia |

**k8s-socialmedia-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| whatsapp-mcp/brain-ingest | `*/5 * * * *` Europe/Madrid | no cambia |

**k8s-synapse-pocharlies**

| job | horario actual | propuesta |
|---|---|---|
| synapse/synapse-outbox-gc | `17 * * * *` sin campo → UTC | no cambia |
| synapse/synapse-skirmbooks-s3-drive-backup | `15 */6 * * *` Europe/Madrid | **cambia** → `15 8,19 * * *` Europe/Madrid (ver tabla de cambios) |
| synapse/synapse-dlq-archive-purge | `41 3 * * *` sin campo → UTC | **cambia** → `41 5 * * 1` Europe/Madrid (ver tabla de cambios) |

**langfuse-k8s**

| job | horario actual | propuesta |
|---|---|---|
| langfuse/langfuse-clickhouse-retention | `30 3 * * *` Etc/UTC | no cambia |
| langfuse/langfuse-retention | `0 4 * * *` sin campo → UTC | no cambia |

**retirada**

| job | horario actual | propuesta |
|---|---|---|
| x86 · timer user · music3-window-rollout | `03:20` (según base 29-09)` hora local del host (Europe/Madrid) | no cambia (retirada: la unidad no existe el 30-09) |

**sin repo**

| job | horario actual | propuesta |
|---|---|---|
| x86 · crontab · backup-runner.sh x86 | `0 3 * * *` (crontab de dibanez)` hora local del host (Europe/Madrid) | **cambia** → `50 22 * * *` Europe/Madrid (ver tabla de cambios) |
| x86 · crontab · brain-sweep.sh | `*/5 * * * *` (crontab de dibanez)` hora local del host (Europe/Madrid) | no cambia |
| x86 · crontab · brain-opencode-sync.py | `*/10 * * * *` (crontab de dibanez)` hora local del host (Europe/Madrid) | no cambia |
| x86 · crontab · dgx463-perfil-watch.sh | `17 * * * *` (crontab de dibanez)` hora local del host (Europe/Madrid) | no cambia |
| x86 · crontab · reinicio bge-m3-embedding (docker) | `*/15 * * * *` (crontab de dibanez)` hora local del host (Europe/Madrid) | no cambia (no-op: el contenedor no existe) |
| x86 · timer user · browser-harness-daily-update | `OnCalendar 04:23` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · rc-title-sync | `periódico, intervalo medido (~1 min)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · owui-mcp-defaults-watch | `periódico, intervalo medido (~30 min)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · tesla-fleet-watchdog | `OnCalendar 04:00` hora local del host (Europe/Madrid) | no cambia (timer disabled: no dispara) |
| x86 · timer sistema · flannel-heal | `periódico, intervalo medido (~2 min)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer sistema · github-app-token | `periódico, intervalo medido (~45 min)` hora local del host (Europe/Madrid) | no cambia |
| hermes · global · Prep suplementación semanal | `0 22 * * 1` (cron de Hermes)` hora local de Hermes (Europe/Madrid) | no cambia |
| hermes · global · HGH nocturna | `30 22 * * *` (cron de Hermes)` hora local de Hermes (Europe/Madrid) | no cambia |
| hermes · hogar · Buenos días Hogar | `0 6 * * *` (cron de Hermes)` hora local de Hermes (Europe/Madrid) | no cambia |
| hermes · hogar · Seguimiento envíos | `0 7 * * *` (cron de Hermes)` hora local de Hermes (Europe/Madrid) | no cambia |
| hermes · analista · pm-revision-diaria-backlog | `0 7 * * *` (cron de Hermes)` hora local de Hermes (Europe/Madrid) | no cambia |

**skirmshop-brain-k8s**

| job | horario actual | propuesta |
|---|---|---|
| skirmshop-brain-prod/skirmshop-brain-gmail-cleanup-metrics | `*/10 * * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-reembed-truncated | `*/20 * * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-status-snapshot | `*/5 * * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-personal-payload-normalization | `7,37 * * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-reembed-watchdog | `7 */4 * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-neural-gardener-skirmshop | `13 */4 * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-neural-gardener-personal | `23 */8 * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-neural-gardener-claude | `47 */6 * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-knowledge-pages | `17 3,9,15,21 * * *` Europe/Madrid | **cambia** → `15 5,11,17,23 * * *` Europe/Madrid (ver tabla de cambios) |
| skirmshop-brain-prod/skirmshop-brain-personal-payload-indexes | `23 3 * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-memory-promotion | `37 3,9,15,21 * * *` Europe/Madrid | **cambia** → `45 5,11,17,23 * * *` Europe/Madrid (ver tabla de cambios) |
| skirmshop-brain-prod/skirmshop-brain-personal-graph-enrichment | `17 4 * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-audit | `30 4 * * *` Europe/Madrid | **cambia** → `30 3 * * *` Europe/Madrid (ver tabla de cambios) |
| skirmshop-brain-prod/skirmshop-brain-claude-session-graph | `37 4 * * *` Europe/Madrid | no cambia |
| skirmshop-brain-prod/skirmshop-brain-pages-reconcile | `45 4 * * *` Europe/Madrid | no cambia |
| skirmshop-product-relations/brain-product-relations-projector | `17 3 * * *` sin campo → UTC | no cambia |
| skirmshop-brain-prod/skirmshop-brain-platform-refresh | `30 4 * * *` Etc/UTC | no cambia (suspendido) |

**x86-host-runtime**

| job | horario actual | propuesta |
|---|---|---|
| x86 · timer user · update-watch-host-versions | `OnCalendar 03:30` y `15:30`, Persistent` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · company-kanban-limpieza | `OnCalendar 04:40` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · blog-daily | `OnCalendar 05:00` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · vscode-archivadas-kill | `periódico, intervalo medido (~15 s)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · company-agent | `periódico, intervalo medido (~30 s)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · company-options-applier | `periódico, intervalo medido (~2 min)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · company-freno-alibaba | `periódico, intervalo medido (~30 min)` hora local del host (Europe/Madrid) | no cambia |
| x86 · timer user · claude-rc-keepalive | `periódico, intervalo medido (~1 h)` hora local del host (Europe/Madrid) | no cambia |
| informe del VP 08:00 | `antes `08:00` (`libexec/vp-daily-report.sh` de x86-host-runtime, alta el 07-09 en `1640ac4`)` hora local del host (Europe/Madrid) | no cambia (retirado (x86-host-runtime a40a329, 17-09)) |

