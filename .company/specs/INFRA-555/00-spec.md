Rol: pm · Fecha: 2026-10-04T23:07:00Z · Sesión: 0f69fc74-559f-4899-b85e-42d51895ff90 · Estado: LISTO

# INFRA-555 — Open WebUI de Dani y Leila indexado en su vault (hija C de INFRA-546)

## Objetivo
Las conversaciones de Open WebUI (chat.e-dani.com) se indexan por usuario: Dani (me@e-dani.com) en `personal`, Leila en `leila`, con delta sin reescanear y una conversación de hoy buscable en menos de 24 h. Usa la puerta y el vault de INFRA-553; no toca el modelo de espacios de INFRA-487.
Repo: skirmshop-brain-v2 (adaptador y job); el CronJob se despliega por skirmshop-brain-k8s (tronco main). Open WebUI vive en dgx-infra (`k8s/apps/chat`, tronco master) y no se modifica salvo que el architect lo decida.
Bloqueada por INFRA-553.

## Criterios de aceptación
Medido hoy: Open WebUI es el deployment `chat/chat` (imagen `dgx-infra/chat`), `WEBUI_AUTH_TRUSTED_EMAIL_HEADER=X-Auth-Request-Email`, base `DATABASE_TYPE=postgresql` en `postgres-shared-rw.databases.svc` base `chat`. En skirmshop-brain-v2 y en skirmshop-brain-prod no existe adaptador ni cronjob de Open WebUI (`/usr/bin/grep -rIn -i 'open-\?webui' --exclude-dir=.git --exclude-dir=.venv .` en el repo → sin resultados).
- [ ] Plan previo del architect (`nota-architect-plan.md`): lectura directa de Postgres frente a la API de Open WebUI, una credencial de solo lectura y por qué.
- [ ] Origen por usuario. El adaptador asigna el vault por el email del propietario del chat: `me@e-dani.com` → `personal`, el email de Leila → `leila`, cualquier otro usuario → no se indexa. Comando: consulta de solo lectura a la tabla `chat` agrupada por `user_id` (esquema real fijado en la primera historia) y conteo de documentos indexados por vault.
- [ ] Conteos reales. `curl` de conteo Qdrant por filtro `source=open-webui` en `personal_documents` y `leila_documents` → cada uno igual al número de chats no vacíos de su usuario en Postgres (los dos números, pegados).
- [ ] Delta. Una segunda pasada sin chats nuevos indexa 0 documentos (log del job) y el job no relee los chats sin cambios (cursor por `updated_at`).
- [ ] Frescura. Una conversación nueva de Dani aparece en `personal` y una de Leila en `leila` en menos de 24 h (búsqueda por una frase única de cada una, instancia correcta → 1 resultado; instancia cruzada → 0).
- [ ] Sin fuga. Con el email de Leila, buscar en `instance=personal` → 403 (puerta de INFRA-553); chats de Leila no aparecen en `personal`.
- [ ] Credencial. La contraseña de Postgres de solo lectura llega por ExternalSecret (formato Connect); ningún secreto en git.

## Restricciones
- Sin servidor nuevo; el adaptador es un CronJob en `skirmshop-brain-prod`.
- Los chats borrados en Open WebUI no se reindexan; el tratamiento de borrados lo fija el plan del architect.
- Los datos privados no se loguean en claro.
- PARA SECURITY: ¿qué rol de Postgres de solo lectura sobre la base `chat` es aceptable (tablas `chat` y `user` únicamente)?

## Trabajo reciente (24 h)
- Nada nuevo de Open WebUI en 24 h; `chat` desplegado 39 d, PVC `chat-data` 26 d.

## Diseño
Diseñador: no — es ingesta, sin interfaz.

## Historias previstas
- Plan de lectura (Postgres o API) y mapeo usuario→vault (dueño: architect).
- Adaptador open-webui con cursor y delta (dueño: developer).
- CronJob, rol de solo lectura y ExternalSecret (dueño: devops).
- Verificación de conteos y no-fuga (dueño: qa).

## Tamaño
M

## Dificultad
Dificultad: media — datos privados de dos personas y una credencial nueva sobre la base de Open WebUI.
