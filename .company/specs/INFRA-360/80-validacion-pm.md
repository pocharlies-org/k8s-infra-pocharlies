Rol: pm · Fecha: 2026-10-01T17:03:11Z · Sesión: epica-infra-360 · Estado: CUMPLE

# INFRA-360 — Validación funcional del PM

Medido el 2026-10-01 (~17:00 UTC) sobre producción. Ejecución a cargo de la compañía: tech-lead sesión b2f4d310, historias INFRA-361/362/363.

| # | Criterio de la épica | Comando | Salida | Resultado |
|---|---|---|---|---|
| 1 | Identidad del escritor documentada con evidencia | `jira_rest.py attachments INFRA-361 --rol pm` → nota adjunta; contenido: `jira_rest.py get INFRA-361 nota-sre-escritor.md` | adjunto 14126 nota-sre-escritor.md: dos escritores — (a) el seed de hermes-reseed forzaba show_reasoning true (hermes_seed.py, causa del retorno), (b) el gateway (hermes gateway run --replace) reescribe en lote ~1 s/perfil conservando el valor. Firma por mtime (ráfaga sub-segundo vs 29 s) y logs de reseed. Límite declarado: sin captura auditd/inotify (denegada al sre). | CUMPLE |
| 2 | Historia de git resumida en un comentario de INFRA-360 | `jira_rest.py comments INFRA-360 --rol pm` | comentario 30-09 21:53: commit 8ec546a (16-09) creó la política de reescribir el config entero en cada arranque; 05bc341 (28-09) añadió reasoningStyle y con él show_reasoning: true. | CUMPLE |
| 3 | El cambio de Dani sobrevive a un ciclo completo de resincronización | `kubectl exec -n hermes deploy/hermes-gateway -c hermes -- sh -c 'for f in /opt/data/profiles/*/config.yaml; do grep -m1 show_reasoning $f; done'` y `kubectl -n argocd get application hermes` | true=0 false=13 (todos los perfiles) + global false, tras el reinicio del pod de las 15:35 de hoy; ArgoCD: Synced Healthy. Prueba en vivo de qa (70-qa.md en INFRA-363): false sobrevivió a una resiembra completa forzada (mtimes 20:51:50-51, valor conservado); clave ausente se siembra; 9 tests fixture verdes. | CUMPLE |

Limitaciones aceptadas (declaradas por el tech-lead, no bloquean): sin captura en flagrancia con auditd (permiso denegado al sre; la identidad queda probada por mtime+logs+código); el lote del gateway no cayó dentro de la ventana de la prueba de qa (supervivencia a ese escritor cubierta por evidencia indirecta y por el arranque real de hoy).

Veredicto: CUMPLE — se cierra la épica (0ter, ENTREGADA).
