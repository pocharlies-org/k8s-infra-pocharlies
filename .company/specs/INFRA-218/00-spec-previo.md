Rol: pm · Fecha: 2026-09-23T23:25:08+02:00 · Sesión: b7b72af0-e4c4-42a7-9116-81a999fb35e6 · Estado: LISTO

## Objetivo

Que el agente pueda expulsar y restringir miembros de grupos de Telegram desde la ruta `/social` del AgentGateway: ban/unban, kick sin ban, restrict/unrestrict y comprobación previa de permisos de admin, envolviendo los métodos MTProto que Telegram ya expone (`channels.editBanned`, `messages.deleteChatUser`). Hoy `tools/list` de `/social` devuelve 34 herramientas y cero de moderación destructiva (medido 22-09-2026, ver abajo), así que los baneos se siguen haciendo a mano en la app.

Relación con otras épicas abiertas: INFRA-113 (cutover de autorización por rol de rutas READ) NO se toca — fuera de alcance; el patrón de test 403 es el de su `scripts/smoke-write-role.sh`. INFRA-219 (catálogo RBAC) no es prerequisito: el rol acotado `agentgateway-write:social` ya existe y gatea hoy `social_manage_forum`. SC-705/SC-709 (identidad por cuenta) en curso: el código nuevo debe enrutar por cuenta igual que `addMembers` (`tgUrl(account)`), sin esperar su cutover. INFRA-216 envuelve otro método MTProto (`deleteForumTopic`) en otro flujo — no duplica nada de esto.

Repo: k8s-socialmedia-pocharlies (la publicación en gateway abre un PR menor en k8s-agentgateway-pocharlies contra `main` — rama leída por ArgoCD, verificado en `agentgateway-mcp.spec.source.targetRevision = main`)

## Terreno verificado (22-09-2026, medido en vivo)

- Cadena de una mutación Telegram (patrón exacto a replicar, verificado en `addMembers` / `setAdminPermissions`):
  1. `mcp-server/src/mcp/tool-registry.ts` — schema de la herramienta (`social_manage_forum`, actions enum, `effect: 'destructive'`, `authScope: 'social.write'`).
  2. `mcp-server/src/mcp/server.ts` — handler canónico (`canonicalManageForum`, l.2117) → `connectorCall(tgUrl(account), ...)`.
  3. `connectors/telegram/src/api/controller.ts` — rutas HTTP del conector (`POST /chats/:id/members` l.177, `PUT /chats/:id/admins/:userId` l.210) sobre `connectors/telegram/src/telegram-client.ts` (mtcute; `editAdminRights` l.822 ya envuelto).
  4. Gateway `k8s-agentgateway-pocharlies` rama `main`: allowlist por herramienta; `social_manage_forum` ya gated por `$SOCIAL_WRITE_RULE` + rol `agentgateway-write` o `agentgateway-write:social` (origin/main l.1160). El checkout local está en rama rancia (`o3b-toolsmcp`) — trabajar desde `origin/main`.
- `contracts/socialmedia-tools.json` en el repo socialmedia = registro de superficie de herramientas (additivo al añadir).
- `scripts/check-mcp-coverage.py` del gateway (rama main) exige que toda herramienta upstream aparezca en la allowlist y en su EXPECTED — CI falla si se publica sin actualizarlo.
- NO existe plumbing de auditoría de mutaciones en el repo (grep `audit` = 0 en connectors/workers/shared). El audit es trabajo nuevo; hay Postgres de referencia en `shared/src/session-store/credential-store.ts` (SC-705).
- tools/list live (vía proxy local 127.0.0.1:8790/social): 34 herramientas, `grep -ciE "ban|kick|remove|restrict|mute"` = 0. Premisa de la épica confirmada hoy.

## Decisión del CTO obligatoria antes de construir (se registra en la historia 1)

1. **Forma de la superficie**: (a) actions nuevos dentro de `social_manage_forum` — hereda el gating existente, cero cambio de gateway, pero granularidad de rol tan fina como "foros"; o (b) herramienta nueva `social_moderate_members` — gating individual conforme a la skill `agentgateway-publishing` ("las mutaciones se gatean individualmente"), permite rol de moderación dedicado futuro, exige regla nueva en gateway + actualizar `check-mcp-coverage.py`. La PM recomienda (b); decide el CTO y queda escrito.
2. **Métodos exactos y granularidad de `BannedRights`** que se publican (ban, unban, kick sin ban vía `messages.deleteChatUser`, mute/read-only/sin-media/sin-invitar vía derechos granulares), contra la documentación oficial de mtcute/MTProto.
3. **Almacén del registro de auditoría** (persistente a redeploy): tabla Postgres propia vs reutilizar el patrón de `session-store`. Solo lectura del registro para el criterio C8.

## Criterios de aceptación

Todos los comandos live van contra `GW=https://agentgateway-mcp.lan.e-dani.com` con dos JWT de corta vida: `ADMIN_TOKEN` (rol `agentgateway-write` o `agentgateway-write:social`) y `OPERATOR_TOKEN` (sin rol), siguiendo el patrón de `k8s-agentgateway-pocharlies/scripts/smoke-write-role.sh` (initialize → capturar `mcp-session-id` → tools/list o tools/call). El grupo de prueba se crea con `social_manage_forum action=createGroup` por la propia cuenta de servicio y un miembro de prueba se invita con `addMembers` (id numérico).

- [ ] C1 — `tools/list` de `/social` expone las acciones de moderación para Telegram.
  Comando: `tools/list` con `ADMIN_TOKEN` sobre `/social` (patrón smoke-write-role.sh) | jq -r '.result.tools[] | select(.name | test("moderate|ban|kick|restrict"; "i")) | .name' (o, si la decisión fue (a), volcar el inputSchema de `social_manage_forum` y extraer su enum `action`).
  Esperado: aparecen ban, unban, kick/remove-member, restrict, unrestrict (como herramienta o actions del enum); cero coincidencias con `OPERATOR_TOKEN` para la parte destructiva (véase C7).

- [ ] C2 — Ban real y reverso: un miembro de prueba baneado deja de poder escribir/ver según el derecho pedido; `unban` lo revierte.
  Comando: `tools/call` ban (target numérico, motivo, duración opcional) → `social_list_participants` muestra al usuario fuera/banned → `tools/call` unban → `social_list_participants` lo devuelve a `present`.
  Esperado: `ok:true` en ambas llamadas y el estado del participante cambia en los dos sentidos, verificado por lectura, no por la respuesta de la escritura.

- [ ] C3 — Kick sin ban: el miembro sale del grupo pero NO queda banned.
  Comando: `tools/call` kick sobre un miembro de prueba → `social_list_participants` ya no lo incluye → `social_manage_forum action=addMembers` con ese mismo id vuelve a añadirlo.
  Esperado: la re-invitación devuelve `ok:true, missing:[]` (si hubiera quedado banned, Telegram lo rechazaría — eso es la prueba de que el kick no baneó).

- [ ] C4 — Restrict (mute) y unrestrict: silenciado le quita el derecho de escribir; unrestrict lo devuelve.
  Comando: `tools/call` restrict con derechos `{sendMessages:false}` → lectura del participante (o mensaje de servicio del chat) refleja el derecho aplicado → `tools/call` unrestrict → lectura lo revierte.
  Esperado: derechos efectivos cambian en los dos sentidos, verificados por lectura.

- [ ] C5 — `get-admin-rights` devuelve el estado real y las mutaciones devuelven error accionable (no 500 opaco) cuando la cuenta de servicio no es admin.
  Comando: `tools/call` get-admin-rights sobre un grupo donde la cuenta NO es admin → luego `tools/call` ban en ese mismo grupo.
  Esperado: get-admin-rights devuelve `is_admin:false` con los derechos reales; el ban devuelve un error JSON-RPC con código canónico explícito (p. ej. `not_admin`) y mensaje que dice qué falta — nunca `outcome_unknown` ni 500 vacío.

- [ ] C6 — Target solo por id numérico; username no resuelto devuelve error accionable.
  Comando: `tools/call` ban con `target: "@nombre-que-no-existe"` (o sin resolver).
  Esperado: error canónico `invalid_target` (o equivalente documentado) que indica "target debe ser id numérico de Telegram"; no un 500 ni un `FLOOD_WAIT` reenviado crudo.

- [ ] C7 — Aislamiento por rol: un principal sin rol de moderación no ve ni puede invocar estas herramientas (403).
  Comando: extensión de `scripts/smoke-write-role.sh` (o `scripts/test-gateway-authz.py`) con la herramienta/acción nueva: `tools/list` y un `tools/call` ban con `OPERATOR_TOKEN`.
  Esperado: la herramienta no aparece en el tools/list del operador sin rol, y el `tools/call` sale rechazado por el gateway (403 / denied). Con `ADMIN_TOKEN` sí aparece. Mismo patrón de salida PASS/FAIL del smoke de INFRA-113.

- [ ] C8 — Cada mutación queda auditada y el registro sobrevive a redeploy.
  Comando: tras un ban de prueba, consultar el registro elegido por el CTO (p. ej. `psql -c "SELECT actor, target, chat_id, rights, reason, ts FROM moderation_audit ORDER BY ts DESC LIMIT 1"`) → `kubectl -n whatsapp-mcp rollout restart deploy/[el conector]` y esperar Ready → repetir la consulta.
  Esperado: la fila contiene quién (principal JWT), a quién, a qué chat, qué derecho y el motivo, antes y después del redeploy.

- [ ] C9 — Publicación conforme a `agentgateway-publishing`: allowlist + coverage + contrato.
  Comando: tras el merge del PR de gateway, `python3 scripts/check-mcp-coverage.py` (rama main) sale con exit 0; el commit del registry/contrato que cambie superficie lleva trailer `Contract-Change: add socialmedia-tools` y la entrada en `contracts/socialmedia-tools.json` es aditiva (las viejas intactas).
  Esperado: exit 0 del coverage check en CI verde; PR de gateway contra `main` mergeado y visible en el ConfigMap vivo (`kubectl get cm -n agentgateway agentgateway-config`).

## Restricciones

- No tocar la autenticación de rutas READ ni el cutover de INFRA-113. No WhatsApp/Instagram. No tocar el flujo de identidad multiusuario de SC-705/SC-709 — solo respetar el enrutado por cuenta (`tgUrl(account)`) que ya usa `addMembers`.
- Mutaciones solo detrás de `agentgateway-write` (o `agentgateway-write:social` si el CTO elige rol dedicado): nunca accesibles a principals de solo lectura; no ensanchar el agujero de autorización existente.
- El registro de contratos (`contracts/socialmedia-tools.json`, allowlist del gateway) es superficie que no se renombra: cambios aditivos, nunca ediciones de entradas existentes.
- El checkout local de k8s-agentgateway-pocharlies está en rama rancia: el trabajo de gateway sale de `origin/main`.
- Confirmación explícita en la firma de la herramienta (parámetro tipo `confirm: true` obligatorio en las acciones destructivas), como pide la épica.

## Diseño

Diseñador: no — la épica no crea ni cambia ninguna interfaz humana: la superficie es el schema JSON de la herramienta MCP (`tool-registry.ts`), las rutas HTTP del conector, la allowlist del gateway y un registro de auditoría en Postgres. No hay pantalla, vista web, panel, documento ni deck que dibujar; todos los criterios (C1–C9) se verifican con comandos y respuestas de API (`tools/list`, `tools/call`, `psql`, smoke de roles), no con apariencia. La única decisión abierta de "forma" (herramienta nueva vs actions, granularidad de `BannedRights`) es de API y la dicta el CTO en la historia 1.

## Trabajo reciente (24 h)

- Revisado 2026-09-25 (CTO): socialmedia mergeó ADR 0001 multicuenta (PR #71, pins v1.3.53/54). Hay dos consecuencias. (1) La cuenta se toma de `account_id`, no de `account` ni del prefijo de un id: el enrutado sigue siendo `tgUrl(...)`, pero con `account_id`. (2) La migración 008 ya está ocupada (`008_multiaccount_first_class.sql`); la de auditoría va en el siguiente número libre (009). Los criterios C1–C9 no cambian: el target sigue siendo el id numérico de Telegram.

- 21-09-2026 sesión opencode `ses_f3d4fee8cffejaeWSdwKKhqwyT` (club Sauvage): `addMembers` numérico funciona (Wanda y Menduca PRESENT), cero herramientas de ban/kick/restrict en los 34 tools — es el disparador; `[FINDING]` registrado en brain. La misma sesión creó INFRA-218 (22-09 00:30). No hay trabajo de implementación en marcha: ninguna sesión viva toca estos dos repos (radar 22-09: solo sesiones PLAN de otras épicas).
- 21-09-2026 gateway `origin/main` ya gatea `social_manage_forum` con `agentgateway-write` o `agentgateway-write:social` (trabajo de roles de SC-709/SC-1144): el rol acotado de escritura social EXISTE — el criterio C7 se apoya en él y no espera a INFRA-219.
- 21-09-2026 k8s-socialmedia-pocharlies: merged SC-705 fase 1.5 (credencial store cifrado, flag OFF en prod, PR #52) y fase 2 de vínculos sub→cuentas (PR #53): el enrutado por cuenta está en evolución — el código nuevo debe pasar por `tgUrl(account)` sin asumir la cuenta compartida.
- Nota de proceso: hubo un intento de sesión PLAN anterior (`392a02dd…`, hace ~10 min) sin spec adjunto; esta sesión la sustituye y sigue adelante por su cuenta porque no dejó borrador en `.company/specs/INFRA-218/` (directorio vacío, comprobado).

## Historias previstas

1. **C10a — Dictamen estándar y forma de la superficie** (cto): métodos MTProto exactos, granularidad `BannedRights`, herramienta nueva vs actions (recomendación PM: `social_moderate_members` nueva), almacén de auditoría; decisión escrita en la historia antes de In Progress de las demás.
2. **C10b — Endpoints de moderación en el conector Telegram** (developer): rutas HTTP en `controller.ts` + envoltorios mtcute en `telegram-client.ts` (ban/unban/kick/restrict/unrestrict/getAdminRights), target numérico con error accionable, tests jest contra el patrón de `server.telegram-admin.spec.ts`.
3. **C10c — Herramienta canónica v2 en el MCP** (developer): schema en `tool-registry.ts` con confirmación explícita obligatoria, handler en `server.ts`, actualización aditiva de `contracts/socialmedia-tools.json`, contract spec.
4. **C10d — Publicación en AgentGateway** (devops): regla de allowlist gated por rol en `k8s-agentgateway-pocharlies` (rama `main`), actualización de `check-mcp-coverage.py` EXPECTED, extensión del smoke de roles; PR y verificación en ConfigMap vivo.
5. **C10e — Auditoría persistente de moderación** (developer): registro quién/a quién/chat/derecho/motivo, almacenamiento que sobrevive redeploy, lectura para C8.
6. **C10f — E2E de moderación en grupo de prueba** (qa): ejecutar C1–C9 tal cual contra producción/stg con tokens, pegar salidas en `70-qa.md`.

Orden: 1 → 2 → 3 → (4 ∥ 5) → 6. La 4 no puede adelantarse a la 3 (el coverage de CI exige que la herramienta exista upstream); la 5 es paralela a 4 porque no comparte ficheros.

## Tamaño

M — seis historias, un repo principal con un PR menor de GitOps en el gateway, sin migraciones de datos ni infra nueva; lo único abierto de diseño (forma de la superficie y almacén de auditoría) cabe en el dictamen de la historia 1. Una semana holgada para un CTO.
