Rol: pm · Fecha: 2026-10-04T23:37:41+02:00 · Sesión: plan-pm-INFRA-485 · Estado: CERRADA

## Objetivo
Un solo índice vectorial para mensajes (Qdrant/brain) y retirada de pgvector en socialmedia. Este alcance ya está partido y en marcha en INFRA-487 (brain) e INFRA-486 (socialmedia).

Repo: k8s-socialmedia-pocharlies

## Cierre
INFRA-485 es DUPLICADA de INFRA-486 + INFRA-487 (Cancelled). Evidencia medida hoy (2026-10-04):
- `jira_get_issue INFRA-486` / `INFRA-487`: ambas en Backlog, enlazadas con Blocks (487 bloquea a 486), con criterios que cubren uno a uno los de 485 (filtros en /search, mapa cuenta→instancia, resolución message_ids, corte calibrado, cobertura, retirada de pgvector, prueba de la paráfrasis, qa+pm).
- `git log origin/main --since='24 hours ago'` en skirmshop-brain-v2: `39c0788 search: filtros por cuenta, plataforma, chats, fechas y tipo; instancia leila (INFRA-487) (#72)` — ya fusionado y en producción.
- `gh pr list -R pocharlies-org/k8s-socialmedia-pocharlies`: PR #206 «la búsqueda semántica sale del brain (INFRA-486)» OPEN (CI verde, qa PASA, architect APROBADA según el brain, 04-10).
Crear hijas o un spec propio duplicaría trabajo en curso. Todo el trabajo sigue en INFRA-486/487.

## Criterios de aceptación
- [ ] No aplica (cerrada como duplicada). Comprobación: `jira_get_issue INFRA-486` → criterios equivalentes presentes.

## Restricciones
Ninguna: no se ejecuta.

## Trabajo reciente (24 h)
- 04-10 · sesión e96257d2: partió esta épica en INFRA-487 (brain) e INFRA-486 (socialmedia) y las dejó en Backlog; lo que hace a este plan: INFRA-485 queda duplicada.
- 04-10 · sesiones 53363ff6/08ad183b (qa/architect, worktree .wt-sm-486b): PR #206 con qa PASA y architect APROBADA; falta la clave BRAIN_MESSAGING_SEARCH_KEY en 1Password (bloqueo por cupo diario) — pertenece a INFRA-486.
- 04-10 · skirmshop-brain-v2#72 (INFRA-487) en producción (brain-39c0788).

## Diseño
Diseñador: no — backend/búsqueda, sin interfaz de usuario.

## Dificultad
Dificultad: alta — datos: borrado de message_embeddings (irreversible por revert) y cambio de interfaz consumida (/search); se trata en INFRA-486/487.

## Historias previstas
Ninguna aquí; viven en INFRA-487 (brain) e INFRA-486 (socialmedia).

## Tamaño
S — solo cierre administrativo.
