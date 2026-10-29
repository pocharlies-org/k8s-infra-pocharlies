Rol: pm · Fecha: 2026-10-09T03:54:08+02:00 · Sesión: d668545d-bee8-42dd-bc25-61ffb6a4e89b · Estado: LISTO

## Objetivo

Que el agente pueda expulsar y restringir miembros de grupos de Telegram desde la ruta `/social` del AgentGateway — ban/unban, kick sin ban, restrict/unrestrict y comprobación previa de permisos de admin — envolviendo los métodos MTProto que Telegram ya expone. La premisa sigue viva hoy (09-10): `contracts/socialmedia-tools.json` tiene 73 herramientas y cero coincidencias `moderate|ban|kick|restrict`, medido tanto en el trunk del repo como en el contrato vendorizado del gateway; los baneos se siguen haciendo a mano en la app.

El diseño YA está decidido y es vinculante (dictamen del CTO, `nota-cto-dictamen.md`, adjunto a la épica, sesión 13c6a43c, 25-09). La épica NO está en cero: la P1 está escrita (PR #127, ~90% hecha) y el CTO que arranque RETOMA las historias existentes (INFRA-344/345/346), no crea nuevas. Relación con INFRA-278 (To Do, spec LISTO, mismo repo): su `kickMember` y `mute`/`unmute` deben REUTILIZAR `social_moderate_members` cuando esta épica la publique; lo que NO es de aquí (deleteChat, leaveChat, listMembers, listTopics) queda en INFRA-278.

Relación con otras épicas: INFRA-113 (cutover de autorización de rutas READ) NO se toca; el patrón de test 403 es el de `scripts/smoke-write-role.sh`. INFRA-219 (catálogo RBAC) no es prerequisito: el rol acotado `agentgateway-write:social` ya existe. SC-705/SC-709/SC-1197 (identidad por cuenta) en el mismo repo: el código nuevo enruta por `account_id` (ADR 0001) sin esperar sus cutover. INFRA-216 envuelve otro método MTProto en otro flujo — no duplica.

Repo: k8s-socialmedia-pocharlies (tronco `deploy/prod`, lo que lee ArgoCD; la publicación en gateway abre un PR en k8s-agentgateway-pocharlies contra `main`)

## Desatasco

Causa medida (09-10): el 30-09 el CTO despachó P1 y la PR #127 (k8s-socialmedia-pocharlies, rama `INFRA-344-telegram-moderation` → `deploy/prod`) se quedó con 2 checks rojos (`standard/Contract surface` y `standard/Lint,test,build`, run 36695283165); la sesión developer murió al reanudar y la cadena CTO→tech-lead→developer se rompió. La épica rebotó To Do↔Backlog y el supervisor soltó las sesiones: hoy la clave NO tiene sesiones de CTO. INFRA-344 lleva desde el 30-09 en Review sin dueño; el 07-10 el supervisor le pidió corrección (progreso 26187) y nadie la ejecutó. La rama se pudre: sin commits desde 30-09 11:18 y HOY 111 commits DETRÁS de `origin/deploy/prod` (medido: `git rev-list --count origin/INFRA-344-telegram-moderation..origin/deploy/prod` = 111; eran 76 el 03-10).

Qué cambia para que no vuelva a pasar: (1) el PRIMER trabajo del CTO es concreto y pequeño: rebasear la rama sobre `origin/deploy/prod` y verdear los 2 checks de #127 — no hay que re-analizar ni re-escribir P1, el código del conector ya está ahí; (2) el plan se consolida en 3 historias de construcción (guard SC-2184: el rol no puede crear una 4.ª) — ver «Historias previstas»; (3) los criterios destructivos C2-C4 llevan FIXTURE FIJO (ver preámbulo de Criterios) para que QA no pare por faltarle una cuenta de prueba: nada depende de una mano humana.

## Dictamen del CTO (historia de diseño CERRADA — vinculante, no se reabre)

Resumen de `nota-cto-dictamen.md` (leerlo entero antes de despachar):

- Herramienta nueva `social_moderate_members`, NO actions en `social_manage_forum`. Actions: `ban`, `unban`, `kick`, `restrict`, `unrestrict`, `get_admin_rights`. `effect: 'destructive'`, `authScope: 'social.write'`, platform solo `telegram`. Parámetros: `account_id` (nunca prefijo de id), `chat_id` y `user_id` numéricos, `reason` obligatorio en ban/kick/restrict, `until` ISO opcional, `restriction` enum cerrado (`mute` | `no_media` | `no_invite` | `read_only`), `confirm: true` obligatorio en las destructivas (falta o false → `confirmation_required` sin llamar a Telegram).
- Métodos: alto nivel de mtcute `^0.29.7`: `banChatMember` / `unbanChatMember` / `kickChatMember` / `restrictChatMember` / `unrestrictChatMember` / `getChatMember('me')`. Kick sin ban en supergrupo = ban+unban inmediato (MTProto no tiene kick sin ban en canales); C3 se mide por re-invitación exitosa. Restrict/ban solo en supergrupos; en grupo básico → `unsupported_chat_type`.
- Errores canónicos sin 500 opacos: `invalid_target`, `not_admin`, `rate_limited` (con `retry_after_s`), `user_not_participant`, `unsupported_chat_type`, `confirmation_required`, `unsupported_platform`, `telegram_error` (con código TL original, nunca `outcome_unknown`).
- Auditoría: tabla `moderation_audit` en la base del MCP server, una fila por intento (también los fallos), `actor` = principal del gateway; si no se puede escribir la fila se deniega la mutación (`audit_unavailable`); `get_admin_rights` no se audita. **Corrección (medida 03-10, revalidada 09-10 en origin/deploy/prod):** el dictamen decía migración 009; existen migraciones hasta `020_whatsapp_direct_chat_self_links.sql` (014 = whatsapp_disappearing_timer, 016 = brain_windows, 020 = auditoría QA del 02-10). La migración de auditoría es **`021_moderation_audit.sql`**. Revalidar el número libre justo antes del PR.
- **Corrección de mecánica del gateway (03-10):** el gateway YA NO mantiene reglas CEL a mano para `/social`: las DERIVA del contrato vendorizado `backends/social/socialmedia-tools.json` (73 tools, igual que el repo) con `scripts/generate-social-authorization.py` (`--write` tras actualizar el contrato; CI usa `--check`). El fragmento generado vive entre los marcadores `BEGIN GENERATED SOCIAL AUTHORIZATION` / `END GENERATED SOCIAL AUTHORIZATION` en `k8s/base/agentgateway-config.yaml`; `check-mcp-coverage.py` carga las tools de ese contrato vendorizado. El gate de rol sigue siendo `agentgateway-write` o `agentgateway-write:social` (main, líneas 1149-1154 para las write de `/social`). No se crea rol Keycloak nuevo (INFRA-219). La herramienta entera queda gated, `get_admin_rights` incluida.
- Gotcha fuera de alcance: `x-user-sub` de /social es forjable con el bearer compartido — el `actor` auditado es lo que afirma el gateway; se menciona en `50-entrega.md`, no se arregla aquí.

## Terreno verificado (medido 09-10-2026)

- Cadena de una mutación Telegram (patrón a replicar, `addMembers` / `setAdminPermissions`): (1) `mcp-server/src/mcp/tool-registry.ts` schema; (2) `mcp-server/src/mcp/server.ts` handler canónico → `connectorCall(tgUrl(accountId), ...)`; (3) `connectors/telegram/src/api/controller.ts` + `telegram-client.ts` (mtcute; `editAdminRights` como referencia); (4) gateway: contrato vendorizado → generator → fragmento autogenerado. La P1 ya escribió (2)-(3) en la rama `INFRA-344-telegram-moderation`.
- `contracts/socialmedia-tools.json` (repo socialmedia, trunk): 73 herramientas, dict con clave `tools`; cero coincidencias moderate|ban|kick|restrict. Mismo número y cero coincidencias en el contrato vendorizado del gateway (`backends/social/socialmedia-tools.json`), medido hoy. Registro aditivo.
- `tool-registry.ts` en trunk: cero coincidencias moderate|ban|kick|restrict; `git grep social_moderate|moderation_audit` sobre origin/deploy/prod = 0.
- `scripts/smoke-write-role.sh` en main del gateway (solo `tools/list`, nunca muta): GW por defecto `https://agentgateway-mcp.e-dani.com`; patrón de los criterios C1-C7. `scripts/test-gateway-authz.py` (main) ya firma JWT de corta vida para sus pruebas.
- Cuentas de prueba: `k8s/base/social-accounts.json` del repo tiene `telegram/personal` y `telegram/professional` emparejadas; no hay herramienta `get_me` — los ids numéricos se leen con `social_list_accounts` o `social_list_participants`.
- Despliegue del MCP: `k8s/base/manifest.yaml` — namespace `whatsapp-mcp`, deployment `mcp-server`, base de datos `postgres-shared-rw.databases.svc.cluster.local:5432/whatsappmcp` (`DATABASE_URL` ya está en el env del pod).
- El checkout local puede estar sucio por sesiones paralelas: ramas nuevas desde origin/deploy/prod y NUNCA `git add -A`.

## Criterios de aceptación

Comandos live contra `GW=https://agentgateway-mcp.e-dani.com` (default medido en `scripts/smoke-write-role.sh`) con dos JWT de corta vida: `ADMIN_TOKEN` (rol `agentgateway-write` o `agentgateway-write:social`) y `OPERATOR_TOKEN` (sin rol). Los labra la propia compañía — `scripts/test-gateway-authz.py` de main del gateway YA firma tokens para sus pruebas (ese patrón); son de corta vida y NO es algo que pedir a Dani (no hay ninguna pregunta a Dani en esta épica). Patrón: initialize → capturar `mcp-session-id` → tools/list o tools/call.

FIXTURE FIJO para los criterios destructivos (C2-C4): el grupo de prueba se crea con `social_manage_forum action=createGroup` con `account_id=professional` (supergrupo); el miembro de prueba es la CUENTA HERMANA ya emparejada: el id numérico de la cuenta telegram `personal` (ambas existen en `k8s/base/social-accounts.json`; no hay `get_me` — QA lee el id propio de `social_list_accounts` o de `social_list_participants` del grupo recién creado, ahí aparecen ambos ids). QA bannea/kickea/restringe a la cuenta personal DESDE la professional y lo revierte; nunca miembros reales del club Sauvage, nunca cuentas de terceros.

- [ ] C1 — `tools/list` de `/social` expone la moderación para Telegram.
  Comando: `tools/list` con `ADMIN_TOKEN` sobre `/social` | `jq -r '.result.tools[] | select(.name | test("moderate|ban|kick|restrict"; "i")) | .name'`.
  Esperado: aparece `social_moderate_members`; su `inputSchema` enumera `ban`, `unban`, `kick`, `restrict`, `unrestrict`, `get_admin_rights`.

- [ ] C2 — Ban real y reverso sobre la cuenta hermana.
  Comando: `tools/call social_moderate_members` ban (id numérico de la cuenta personal, `account_id=professional`, `reason`, `confirm:true`) → `social_list_participants` muestra a la personal fuera/banned → `tools/call` unban → `social_list_participants` la devuelve a present.
  Esperado: `ok:true` en ambas y el estado cambia en los dos sentidos, verificado por lectura, no por la respuesta de la escritura.

- [ ] C3 — Kick sin ban: la cuenta hermana sale pero NO queda banned.
  Comando: `tools/call` kick sobre la cuenta personal → `social_list_participants` ya no la incluye → `social_manage_forum action=addMembers` con ese id.
  Esperado: la re-invitación devuelve `ok:true, missing:[]`.

- [ ] C4 — Restrict (mute) y unrestrict sobre la cuenta hermana.
  Comando: `tools/call` restrict con `restriction:"mute"` → lectura del participante refleja `can_send_messages:false` → `tools/call` unrestrict → lectura lo revierte.
  Esperado: derechos efectivos cambian en ambos sentidos, verificados por lectura.

- [ ] C5 — `get_admin_rights` real y error accionable cuando la cuenta no es admin.
  Comando: grupo donde `professional` NO es admin (crear un supergrupo con `personal` y salirse la professional, o grupo existente de terceros): `tools/call get_admin_rights` → `tools/call` ban en ese grupo.
  Esperado: `is_admin:false` con derechos reales; el ban devuelve error JSON-RPC `not_admin` con mensaje de qué falta — nunca `outcome_unknown` ni 500 vacío.

- [ ] C6 — Target solo por id numérico.
  Comando: `tools/call` ban con `user_id: "@nombre-que-no-existe"`.
  Esperado: error canónico `invalid_target`, validado en el MCP antes de llamar al conector; no 500 ni FLOOD_WAIT crudo.

- [ ] C7 — Aislamiento por rol.
  Comando: extensión de `scripts/smoke-write-role.sh` con `social_moderate_members`: `tools/list` y `tools/call` ban con `OPERATOR_TOKEN`, y `tools/list` con `ADMIN_TOKEN`.
  Esperado: sin rol no aparece y el call sale rechazado por el gateway (403/denied); con `ADMIN_TOKEN` aparece. Salida PASS/FAIL como el smoke de INFRA-113.

- [ ] C8 — Cada mutación queda auditada y sobrevive a redeploy.
  Comando: tras un ban de prueba, `kubectl -n whatsapp-mcp exec deploy/mcp-server -- sh -c 'psql "$DATABASE_URL" -c "SELECT actor, target_user_id, chat_id, action, restriction, reason, ts FROM moderation_audit ORDER BY ts DESC LIMIT 1"'` → `kubectl -n whatsapp-mcp rollout restart deploy/mcp-server`, esperar Ready → repetir la consulta.
  Esperado: la fila contiene quién (principal JWT), a quién, chat, acción/derecho y motivo, antes y después del redeploy. La migración aplicada es `021_moderation_audit.sql` (revalidado 09-10: la última existente en origin/deploy/prod sigue siendo `020_whatsapp_direct_chat_self_links.sql`).

- [ ] C9 — Publicación conforme a `agentgateway-publishing`: contrato vendorizado + generator + coverage.
  Comando (en k8s-agentgateway-pocharlies, tras el merge): `python3 scripts/generate-social-authorization.py --check` y `python3 scripts/check-mcp-coverage.py`, ambos exit 0; `backends/social/socialmedia-tools.json` contiene `social_moderate_members` y 74 herramientas (las 73 existentes intactas); en el repo socialmedia el commit del registry lleva trailer `Contract-Change: add social_moderate_members` y la entrada en `contracts/socialmedia-tools.json` es aditiva.
  Esperado: exit 0 de ambos, CI verde; PR de gateway contra `main` mergeado y fragmento visible en el ConfigMap vivo (`kubectl get cm -n agentgateway agentgateway-config`). Orden: primero la imagen con la herramienta desplegada, después el merge del PR de gateway.

## Restricciones

- No tocar la autenticación de rutas READ ni INFRA-113. No WhatsApp/Instagram. No tocar el flujo de identidad de SC-705/SC-709/SC-1197 — solo enrutar por `account_id` (ADR 0001).
- Mutaciones solo detrás de `agentgateway-write` o `agentgateway-write:social`; no ensanchar el agujero de autorización existente. No crear rol Keycloak (INFRA-219).
- Pruebas destructivas SOBRE EL FIXTURE FIJO (cuentas personal/professional emparejadas): nunca miembros reales del club Sauvage ni cuentas de terceros.
- El registro de contratos (`contracts/socialmedia-tools.json`, contrato vendorizado del gateway) es superficie que no se renombra: cambios aditivos. No editar a mano el fragmento generado del gateway: se regenera con `generate-social-authorization.py --write`.
- Ramas nuevas desde origin/deploy/prod (socialmedia) y origin/main (gateway), rebase justo antes del PR, nunca `git add -A`.
- `confirm: true` obligatorio en ban/kick/restrict en la firma de la herramienta.
- Máximo 3 historias de construcción (guard SC-2184): no crear una 4.ª; INFRA-347 se absorbe en INFRA-345 e INFRA-348 es validación QA.

## Trabajo reciente (24 h)

- 09-10 (hoy): HEAD de `deploy/prod` f020212 (08-10, SKIRM-118 pin mcp-server v1.3.107) — el repo sigue muy activo y NADA de eso toca moderación: contrato 73 herramientas con cero coincidencias moderate|ban|kick|restrict, medido hoy tanto en origin/deploy/prod como en el contrato vendorizado del gateway. Cero sesiones vivas en la clave INFRA-218.
- 09-10 (hoy): PR #127 sigue OPEN con los mismos 2 checks rojos del 30-09 (run 36695283165), sin re-ejecuciones nuevas; rama sin commits desde 30-09 11:18 y 111 commits detrás de origin/deploy/prod. INFRA-344 en Review desde el 30-09; la corrección pedida el 07-10 (progreso 26187) no se ejecutó.
- 09-10 (hoy): las cinco historias del 30-09 existen en Jira, pero el plan nuevo consolida INFRA-347 (auditoría + migración) dentro de INFRA-345 (mismo `server.ts`, mismo PR) e INFRA-348 queda como validación QA de la épica, no como historia de construcción — cumple el guard de máximo 3 sin borrar nada. INFRA-278 (To Do, spec LISTO, mismo repo) solapa en kick/mute: reutilizará `social_moderate_members` cuando esta épica la publique.
- 03-10: re-plan anterior (spec id 16049): la rama estaba 76 commits detrás; hoy 111. El atasco fue de cadena de sesiones (harness), no de diseño.

## Diseño

Diseñador: no — la superficie es el schema JSON de la herramienta MCP, las rutas HTTP del conector, la config del gateway y un registro de auditoría en Postgres; no hay interfaz humana. Todos los criterios se verifican con comandos y respuestas de API.

## Historias previstas

Máximo 3 historias de construcción (guard SC-2184). Las claves ya existen en Jira; el CTO que arranque las RETOMA, no crea historias nuevas. Orden: 344 → 345 → 346 → 348.

1. **INFRA-344 — Story (developer)** — P1 conector Telegram: rebasear la rama `INFRA-344-telegram-moderation` sobre `origin/deploy/prod`, verdear los 2 checks rojos de la PR #127, merge (lo decide el CTO). ~90% hecha: el código del conector ya está escrito.
2. **INFRA-345 — Story (developer)** — P2 herramienta MCP `social_moderate_members`: schema con `confirm`, handler en `server.ts` con enrutado por `account_id`, contrato aditivo en `contracts/socialmedia-tools.json` con trailer `Contract-Change: add social_moderate_members`. ABSORBE INFRA-347 (Task: auditoría + migración `021_moderation_audit.sql`): mismo fichero `server.ts`, mismo PR; el CTO cierra INFRA-347 como absorbida al mergearse INFRA-345.
3. **INFRA-346 — Story (devops)** — P3 publicación gateway: vendorizar el contrato actualizado en `backends/social/socialmedia-tools.json`, regenerar el fragmento (`generate-social-authorization.py --write`), `--check` y `check-mcp-coverage.py` exit 0, extensión de `scripts/smoke-write-role.sh`. PR contra `main`; se mergea DESPUÉS de tener la imagen con la herramienta desplegada.

INFRA-348 (Task, qa) no es una historia de construcción: es la validación QA de la épica (ejecutar C1-C9 contra producción con el fixture fijo, salidas en `70-qa.md`); el CTO la ejecuta al terminar las 3 y la cierra.

## Tamaño

M — 3 historias de construcción sobre un dictamen cerrado y una PR ya escrita (~90% la P1), un repo principal con un PR menor de GitOps en el gateway, una migración nueva sin datos. El riesgo es el entorno: trunk muy activo (la rama de P1 está 111 commits detrás) y despliegue acoplado imagen → gateway.

## Dificultad

Dificultad: media — trabaja sobre algo que ya existe (dictamen cerrado, conector mtcute con los métodos de alto nivel, patrón `addMembers` replicado, PR #127 ya escrita); toca permisos y un servicio externo (mutaciones destructivas sobre Telegram detrás de un gate de roles), pero no es algo nuevo desde cero (criterio de Dani 06-10).
