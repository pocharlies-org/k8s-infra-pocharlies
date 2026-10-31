Rol: pm · Fecha: 2026-10-02T08:13:06Z · Sesión: cef57743-0b5c-4dc8-8f29-61930e17b255 · Estado: LISTO

## Objetivo

Entregar a Dani un informe con datos —qué satura md3 de sauvage, cuánto, qué rompe y 3–5 opciones con coste en euros, riesgo y esfuerzo— más una recomendación, para que él decida; la ejecución de la opción elegida va en otra épica. Nada se cambia en el nodo ni en el cluster hasta la decisión: esta épica es 100 % medición y documentación.

Solapes con épicas abiertas (no duplicar): **INFRA-283** (To Do, plan entregado, historias INFRA-336/337/338) ya está escalonando los CronJobs del cluster — si la recomendación saliera "cambiar horarios", su ejecución es de INFRA-283, no de aquí. **SC-1342** (To Do, decisión del CTO del 29-09: excluir md3 de NodeDiskIOSaturation y bajar la carga de fondo) sigue sin ejecutar y su silencio NO está desplegado (verificado hoy: `rules.yaml` no excluye md3); esta épica la sustituye con datos y SC-1342 queda a la espera de la decisión de Dani.

Repo: k8s-infra-pocharlies

Contexto: backup-hub y k8s-observability-pocharlies como repos de referencia (se leen, no se tocan).

## Criterios de aceptación

El entregable es un informe en `.company/specs/INFRA-401/20-informe.md` (rama de la épica, k8s-infra-pocharlies), adjuntado a INFRA-401 como `nota-tech-lead-informe.md`. Todos los comandos de verificación parten de descargarlo:

```
python3 ~/.local/libexec/x86-host-runtime/jira_rest.py get INFRA-401 nota-tech-lead-informe.md /tmp/i401.md
```

- [ ] **C1 — Medición de md3 durante 24 h** (iostat/PSI/node_exporter): %util, await, IOPS y quién los pone (proceso/pod), con y sin pasadas de backup. El informe contiene la serie y la tabla de atribución, y la métrica existe en VictoriaMetrics para esa ventana.
  ```
  grep -cE '%util|await|IOPS' /tmp/i401.md          # esperado: >= 3
  export KUBECONFIG=~/.kube/config
  curl -s http://10.43.33.43:8428/api/v1/query_range \
    --data-urlencode 'query=rate(node_disk_io_time_seconds_total{instance="10.42.4.70:9100",device="md3"}[5m])' \
    --data-urlencode "start=$(date -u -d '24 hours ago' +%s)" --data-urlencode "end=$(date -u +%s)" \
    --data-urlencode step=300 | python3 -c "import json,sys;d=json.load(sys.stdin)['data']['result'];print(sum(len(r['values']) for r in d))"
  # esperado: >= 200 puntos (24 h a paso 5 min); la ventana debe solapar al menos una pasada de
  # backup (backup-hub/recovery-kit-to-drive a las 21:30Z y el barrido s3-drive cada 6 h)
  ```
  (10.42.4.70:9100 es el node-exporter de sauvage: `kube_pod_info{pod=~"vm-prometheus-node-exporter.*"}` → node=sauvage.)

- [ ] **C2 — Inventario de todo lo que vive en md3 o le escribe**, con tamaño y patrón de I/O. Ojo al hecho medido hoy: **md3 es el `/` de sauvage** (RAID1 de 2 HDDs HGST, 3.6 T, 2.5 T usados) — el SO, containerd y kubelet están en los HDDs, no solo backup-minio. El informe lista al menos backup-minio, réplicas de Longhorn, BD de skirmshop, backups y logs con su tamaño en GB y su patrón.
  ```
  grep -E 'backup-minio|longhorn' /tmp/i401.md      # esperado: ambas, con cifras de GB
  timeout 30 ssh sauvage 'df -h / | tail -1'         # esperado: /dev/md3 …  /  (ancla viva del inventario)
  ```

- [ ] **C3 — Qué rompe hoy la saturación**, con evidencia: jobs que fallan por DeadlineExceeded (kube-system/sauvage-pod-reaper y sauvage-zombie-watchdog, skirmbooks accounting/reconcile-sweep, back-in-stock coverage-reconcile, backup-hub/recovery-kit-to-drive), alertas firing y apps Degraded. El informe los lista con su evidencia (evento/serie) y al menos una sigue visible al verificar.
  ```
  export KUBECONFIG=~/.kube/config
  kubectl get application -n argocd k8s-infra -o jsonpath='{.status.health.status}'   # esperado hoy: Degraded
  grep -c 'DeadlineExceeded' /tmp/i401.md           # esperado: >= 1
  ```
  (Si al verificar k8s-infra ya estuviera Synced por un reintento, la evidencia válida son los eventos/jobs fallados citados en el informe.)

- [ ] **C4 — De 3 a 5 opciones**, cada una con coste en euros, riesgo, esfuerzo y qué arregla. Candidatas mínimo: mover backup-minio a otro disco/nodo, SSD/NVMe en sauvage, cambiar horarios/frecuencia de los barridos (→ ejecución en INFRA-283), sacar Longhorn de md3.
  ```
  grep -c '^## Opción' /tmp/i401.md                 # esperado: entre 3 y 5
  grep -c 'Coste' /tmp/i401.md                      # esperado: >= nº de opciones
  ```

- [ ] **C5 — Recomendación entregada a Dani con PREGUNTA:** el informe cierra con `## Recomendación` y la épica lleva UN comentario mencionándole con `PREGUNTA:` y las opciones. Nada se ha cambiado en el nodo (ver C6).
  ```
  grep -c '^## Recomendación' /tmp/i401.md          # esperado: 1
  ```
  El comentario con `PREGUNTA:` lo verifica el pm leyendo los comentarios de INFRA-401 (jira_get_issue, include=comments): debe existir, firmado por un rol de la compañía, mencionando a Dani (accountId 5b756d727cefaf05bcc36fbe).

- [ ] **C6 — Cero cambios en el nodo y el cluster**: la épica no toca sauvage, ni rules.yaml, ni CronJobs, ni activeDeadlineSeconds. Verificable porque ninguna PR de esta épica toca manifiestos:
  ```
  cd /home/dibanez/k8s/k8s-infra-pocharlies && git log origin/deploy/prod --oneline --since=2026-10-01 -- kubernetes/ ansible/ | grep -i 'INFRA-401' ; echo rc=$?   # esperado: sin resultados, rc=1
  ```

## Restricciones

- Solo lectura en sauvage y en el cluster: `iostat`, `pidstat -d`, `iotop -b`, `blktrace` puntual, PSI, node_exporter. Nada de `systemctl`, cambios de cron, ni mover ficheros.
- Fuera de alcance (lo dice la épica): ejecutar la opción elegida; silenciar o subir el umbral de NodeDiskIOSaturation (eso era SC-1342); subir activeDeadlineSeconds para tapar el síntoma.
- Los comandos sobre sauvage pueden colgarse por la propia saturación (medido: un `du` de /var/lib/backup-minio no terminó en 2 min): envolver siempre en `timeout` y priorizar métricas sobre lecturas del disco.
- No crear cargas en los Sparks (perfil `llm-tp`); la medición es en sauvage y en VictoriaMetrics.
- El informe se adjunta a INFRA-401 como `nota-tech-lead-informe.md` (nombre del catálogo), sin duplicados `-v2`.

## Trabajo reciente (24 h)

- **2026-10-02 08:00Z (esta sesión de plan, medición en vivo):** md3 de sauvage al **96,7 % de %util** ahora mismo (`rate(node_disk_io_time_seconds_total{instance="10.42.4.70:9100",device="md3"}[5m])` = 0.967) y **`/` de sauvage es /dev/md3** (`df -h`: 3.6T, 2.5T usados) — la saturación no es solo del backup: el SO, containerd y kubelet están sobre los HDDs. Premisa viva y el criterio C2 gana relevancia.
- **2026-10-02 08:05Z:** `kubectl get application k8s-infra` → **Degraded** hoy; los CronJobs citados por la épica están vivos con sus schedules (pod-reaper */15, zombie-watchdog */5, accounting-sweep 7,22,37,52, reconcile-sweep */15, coverage-reconcile 3-59/10, recovery-kit-to-drive 30 21).
- **SC-1342 (29-09, decisión del CTO vía Hermes):** eligió excluir md3 de NodeDiskIOSaturation + bajar carga de fondo (señalaba skirmbooks-accounting-sweep); descartó SSD por el coste de Longhorn×3 sobre los NVMe de los control-plane. Sigue **To Do** y el silencio no está desplegado (rules.yaml verificado hoy). INFRA-401 la sustituye con datos — no reejecutar SC-1342.
- **INFRA-283 (To Do, plan entregado 30-09, historias INFRA-336/337/338):** inventario y escalonamiento de los ~96 CronJobs del cluster. Cubre la opción "cambiar horarios": se cita, no se duplica.
- **Nada en vivo:** sin sesión activa trabajando en md3/sauvage en el radar de sesiones.

## Diseño

Diseñador: no — el entregable es un informe de decisión en Markdown adjunto a la épica; no hay interfaz, pantalla ni documento con diseño de producto.

## Historias previstas

1. Medición 24 h de md3 y atribución de la carga por proceso/pod, con y sin backup (dueño: sre) — C1.
2. Inventario de lo que vive en md3 o le escribe, tamaños y patrones de I/O, incluido que `/` está en md3 (dueño: devops) — C2.
3. Cuadro de lo que rompe hoy: jobs DeadlineExceeded, apps Degraded, alertas, con evidencia (dueño: sre) — C3.
4. Opciones 3–5 con coste/riesgo/esfuerzo + recomendación + PREGUNTA a Dani, redactadas por tech-lead y entregadas por pm/CTO (dueños: tech-lead, pm) — C4, C5, C6.

## Tamaño

S — 4 historias, un repo, todo lectura y documentación; el esfuerzo es pequeño y lo único largo es la ventana de 24 h de medición, que corre en segundo plano.

## Dificultad

Dificultad: baja — medición y documentación sin ningún cambio en nodo, cluster ni contratos; un solo repo; se deshace con un revert (solo documentos); no toca secretos, arquitectura, datos ni despliegues.
