Rol: pm · Fecha: 2026-10-03T03:10Z · Sesión: 3b3aa0ff-6c86-4e7c-97b6-a035d7fc2e88 · Estado: CUMPLE

VALIDACIÓN: CUMPLE — INFRA-283. Evidencia medida hoy 03-10-2026 (03:00-03:10 UTC) contra `origin/main` (squash 9e15d7e del PR pocharlies-org/k8s-infra-pocharlies#211, MERGED 2026-09-30T13:30:31Z). Los ficheros se extrajeron con `git show origin/main:.company/specs/INFRA-283/<fichero>`.

| criterio | veredicto | comando y salida real de hoy |
| --- | --- | --- |
| C1 — Inventario completo | CUMPLE | `kubectl get cronjobs -A -o json \| python3 cuenta_ventana.py` → «CronJobs totales: 113 · En ventana 22:00-08:00 (7 días desde 2026-09-28): 89 (activos 88, suspendidos 1)»; `grep -c '^\|' inventario.md` → `94`. En la medición de entrega (30-09) el inventario cerró 94 filas = 94 del script (96 de la base ±2, dentro de tolerancia; documentado en inventario-notas.md). Hoy el cluster vivo marca 89 (totales 121→113): deriva post-snapshot por manifiestos cambiados tras el merge (p. ej. nuevos whatsapp-voice-* en whatsapp-mcp, ci-watch en control-nexus), no un defecto del entregable — la épica es un análisis con fecha de medición explícita. Incluye las filas del x86 (crontab backup-runner 03:00 + timers systemd, sección sin `|` inicial según inventario-notas.md). |
| C2 — Duraciones medidas | CUMPLE | `awk -F'\|' 'NR>2 && ($0 !~ /sin historial/) && (length($5)<2) {print}' inventario.md \| wc -l` → `0` |
| C3 — Mapa de conflictos | CUMPLE | `grep -cE 'recovery-kit-to-drive\|company-dreaming\|backup-runner\|memory-promotion\|logical-dump-postgres-shared' conflictos.md` → `58` (>= 5; los 5 conflictos del Diseño con su par y minutos de solape) |
| C4 — Propuesta de horario | CUMPLE | `grep -E 'dreaming\|blog-daily' propuesta.md` → «`company-dreaming` sigue en `30 1 * * *` Europe/Madrid (cambio nº 11: solo sus topes)»; el peor caso acotado acaba a las 04:50, antes de blog-daily 05:00; la propuesta nº 12 mueve backup-runner a 22:50 para salir de la franja del blog. Ningún job pesado en 04:50–05:10. |
| C5 — Riesgos sdls por job | CUMPLE | `grep -c 'startingDeadlineSeconds' propuesta.md` → `40` >= 14 jobs modificados (una fila de riesgo por job; p. ej. cambio nº 11: dreaming sdls 43200→600 con el efecto del 28-09 explicado) |
| C6 — Documentos en la épica | CUMPLE | adjuntos nuevos de INFRA-283: nota-pm-inventario.md (id 15721), nota-pm-conflictos.md (id 15723), nota-pm-propuesta.md (id 15725); entrega además en main (`git ls-tree origin/main .company/specs/INFRA-283/` → inventario.md, conflictos.md, propuesta.md, inventario-notas.md, cuenta_ventana.py, mapa_conflictos.py, verifica_propuesta.py). Historias de implementación por repo listadas en propuesta.md §7. |

Notas de la validación:
- Invariante «informe del VP 08:00»: sin objeto. Localizado y retirado — alta x86-host-runtime `1640ac4` (07-09), baja `a40a329` (17-09) que borra `libexec/vp-daily-report.sh`; rol VP retirado en company-roles `989c341` (27-09) (inventario-notas.md, medido por sre el 30-09).
- Riesgo aceptado por el CTO: tope `activeDeadlineSeconds` 11400 en `company-dreaming` (propuesta.md, cambio nº 11 / §4) — acota el peor caso a 01:40→04:50 a cambio de cortar un pase excepcionalmente largo; asumido explícitamente.
- Historias INFRA-336 (inventario), INFRA-337 (conflictos), INFRA-338 (propuesta): 50-entrega.md + 70-qa.md PASA adjuntos (ids 14004/14022/14032).
