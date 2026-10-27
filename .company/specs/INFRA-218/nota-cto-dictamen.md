Rol: cto · Fecha: 2026-09-25T00:05:00+02:00 · Sesión: 13c6a43c-1d42-409d-88d2-6c33ea293c72 · Estado: LISTO

# INFRA-218 — Dictamen del CTO (historia 1 del spec: C10a)

Estándar antes que custom: Telegram ya tiene los métodos (MTProto) y la librería que ya usamos (mtcute `^0.29.7`, `@mtcute/node`) ya los envuelve en alto nivel. No se escribe ningún envoltorio TL propio salvo que el método de alto nivel no exista en la versión instalada.

## 1. Forma de la superficie — opción (b): herramienta nueva

`social_moderate_members` (herramienta nueva, NO actions dentro de `social_manage_forum`).
Motivo: la skill `agentgateway-publishing` pide gatear mutaciones de forma individual; una herramienta propia permite en el futuro un rol dedicado de moderación sin tocar foros.

- `actions`: `ban`, `unban`, `kick`, `restrict`, `unrestrict`, `get_admin_rights`.
- `effect: 'destructive'`, `authScope: 'social.write'`; `platform` solo `telegram` (otro valor → error `unsupported_platform`).
- Parámetros: `account_id` (ADR 0001, PR #71: la cuenta sale de `account_id`, nunca del prefijo de un id; se enruta con `tgUrl(accountIdValue)` como las herramientas de diálogos Telegram), `chat_id` (numérico), `user_id` (numérico; no aplica en `get_admin_rights`), `reason` (texto, obligatorio en ban/kick/restrict), `until` (ISO-8601 opcional, solo ban y restrict), `restriction` (solo restrict), `confirm` (booleano, obligatorio y `true` en `ban`, `kick`, `restrict`; si falta o es false → error `confirmation_required` sin llamar a Telegram).
- Gateway: regla propia para `social_moderate_members` con el mismo gate que `social_manage_forum` hoy (rol `agentgateway-write` o `agentgateway-write:social`). No se crea rol nuevo en Keycloak: el catálogo RBAC es INFRA-219. La herramienta entera queda gated, `get_admin_rights` incluida (no vale la pena partirla por una lectura).

## 2. Métodos exactos y granularidad

| acción | mtcute (alto nivel) | MTProto por debajo |
|---|---|---|
| ban | `banChatMember({ chatId, participantId, untilDate })` | `channels.editBanned` con `view_messages` (supergrupo) / `messages.deleteChatUser` (grupo básico) |
| unban | `unbanChatMember({ chatId, participantId })` | `channels.editBanned` con derechos vacíos |
| kick | `kickChatMember({ chatId, userId })` | grupo básico: `messages.deleteChatUser`; supergrupo: ban + unban inmediato (MTProto no tiene kick sin ban en canales; es el mismo comportamiento que el Bot API) |
| restrict | `restrictChatMember({ chatId, userId, restrictions, until })` | `channels.editBanned` con `ChatBannedRights` granulares |
| unrestrict | `unrestrictChatMember({ chatId, userId })` | `channels.editBanned` con derechos vacíos |
| get_admin_rights | `getChatMember({ chatId, userId: 'me' })` | `channels.getParticipant` |

Si en la 0.29.x instalada cambia el nombre o la firma de alguno, manda el `.d.ts` instalado; el developer lo dice en `50-entrega.md`. Restrict/unrestrict/ban solo existen en supergrupos: en un grupo básico, restrict devuelve `unsupported_chat_type`.

`restriction`: un enum cerrado de valores ya definidos (no se expone el mapa completo de `ChatBannedRights`):
- `mute` → `sendMessages`, `sendMedia`, `sendStickers`, `sendGifs`, `sendGames`, `sendInline`, `sendPolls`, `embedLinks` = prohibidos
- `no_media` → todo lo de `mute` menos `sendMessages`
- `no_invite` → `inviteUsers` prohibido
- `read_only` = `mute` + `inviteUsers`, `pinMessages`, `changeInfo` prohibidos

`get_admin_rights` devuelve `{ is_admin, is_creator, rights: { banUsers, deleteMessages, inviteUsers, ... } }` leído del participante real.

## 3. Errores canónicos (sin 500 opacos)

- `invalid_target`: `chat_id`/`user_id` no numérico (p. ej. `@nombre`). Mensaje: «target debe ser id numérico de Telegram». Se valida en el MCP antes de llamar al conector.
- `not_admin`: `CHAT_ADMIN_REQUIRED`, `RIGHT_FORBIDDEN`, `USER_ADMIN_INVALID` o falta de `banUsers`. El mensaje dice qué derecho falta.
- `rate_limited`: `FLOOD_WAIT_n` con `retry_after_s`.
- `user_not_participant`, `unsupported_chat_type`, `confirmation_required`, `unsupported_platform`.
- Cualquier otro error de RPC: `telegram_error` con el código TL original, nunca `outcome_unknown`.

## 4. Almacén de auditoría — Postgres propio del MCP server, migración nueva

Tabla `moderation_audit` en la base de datos que el MCP server ya usa. La migración es el siguiente número libre en `mcp-server/src/infrastructure/database/migrations/`: hoy `009_moderation_audit.sql`, porque `008_multiaccount_first_class.sql` ya existe desde el PR #71. Se descarta `session-store`: guarda credenciales, no eventos.

Columnas: `id`, `ts`, `actor` (principal que manda el gateway: sub/preferred_username), `account_id` (FK a `social_accounts`, ADR 0001), `platform`, `chat_id`, `target_user_id`, `action`, `restriction`, `until`, `reason`, `outcome` (`ok` | código canónico de error), `telegram_error`.

- La fila se escribe en el handler del MCP (`server.ts`), que es quien sabe qué principal llama. Se escribe una fila por intento de mutación, también cuando falla.
- Si no se puede escribir la fila, se deniega: la mutación no se ejecuta y devuelve `audit_unavailable`. `get_admin_rights` no se audita.
- Límite conocido: el `actor` es el que afirma el gateway. Hay un gotcha abierto: `x-user-sub` de /social se puede falsificar con el bearer compartido. Arreglarlo no entra en esta épica; se anota en la entrega.

## 5. Contrato y despliegue

- Entrada nueva en `contracts/socialmedia-tools.json`, solo añadida; las entradas existentes no se tocan. El commit lleva el trailer `Contract-Change: add social_moderate_members`.
- Tronco de socialmedia: `deploy/prod` (ArgoCD). El tronco del gateway es `main`. El PR del gateway se mergea después de que la imagen con la herramienta esté desplegada (gotcha «allowlist + imagen van juntas»: CI de coverage exige la tool upstream).
- El checkout local `~/k8s/k8s-socialmedia-pocharlies` está sucio con trabajo de otra sesión (rama `sc705-credstore-pr2`, ficheros modificados). Los makers trabajan en rama nueva desde `origin/deploy/prod` sin `git add -A`.
