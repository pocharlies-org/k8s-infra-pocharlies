Rol: pm · Fecha: 2026-10-04T23:07:00Z · Sesión: 0f69fc74-559f-4899-b85e-42d51895ff90 · Estado: LISTO

# INFRA-554 — Mensajes de Leila entran a su vault (hija B de INFRA-546)

## Objetivo
WhatsApp, Telegram y Gmail de Leila se indexan en `leila` y no en `personal`, con backfill de lo ya indexado. Se apoya en la ingesta por ventanas de INFRA-364 (ya en prod, no se rediseña), en el filtro por cuenta de INFRA-487 (no se rehace) y en el pipeline de buzones de INFRA-473/INFRA-478 (se reutiliza).
Repo: whatsappmcp (job brain-windows, `social-accounts`); el despliegue vive en k8s-socialmedia-pocharlies (tronco deploy/prod). Para correo, synapse si INFRA-478 aún no cubre `lays84.mv@gmail.com`.
Bloqueada por INFRA-553 (el vault y su puerta deben existir).

## Criterios de aceptación
Medido hoy: `social-accounts` (ConfigMap `whatsapp-mcp/social-accounts`) manda la cuenta WhatsApp `leila` a `brainInstance: personal` (también las de Telegram personal); `brain-windows-config` ya trae `outboundNames.leila: Leila`; `personal_documents` tiene 43 puntos `account=leila`; el correo de `lays84.mv@gmail.com` entra hoy en `personal_documents` (21 de 300 puntos muestreados).
- [ ] Enrutado. `kubectl get cm social-accounts -n whatsapp-mcp -o jsonpath='{.data.social-accounts\.json}' | python3 -c "import json,sys;print([a['brainInstance'] for a in json.load(sys.stdin) if a['accountId']=='leila'])"` → `['leila']` (hoy `['personal']`).
- [ ] Cuenta verificable. Cada documento de `leila_documents` lleva `account` verificada por el conector (nunca inferida por nombre de chat): conteo Qdrant de `leila_documents` con `account` distinto de `leila` o de `lays84.mv@gmail.com` → 0.
- [ ] Backfill. Conteo real por fuente en `leila_documents` (WhatsApp, Telegram, Gmail) pegado en `50-entrega.md`, y cada conteo ≥ el de `personal_documents` con `account=leila` antes de empezar (43 + Gmail de `lays84.mv@gmail.com`; se fija el número exacto en la primera historia).
- [ ] Sin duplicado en terreno de Dani. Tras el backfill, conteo de `personal_documents` con `account=leila` → 0 y con `account=lays84.mv@gmail.com` → 0.
- [ ] Ventanas en marcha. `kubectl get cronjob brain-windows -n whatsapp-mcp -o jsonpath='{.spec.suspend}'` → `false` y un mensaje nuevo de Leila aparece en `leila_documents` en menos de 2 h.
- [ ] Telegram de Leila. Si existe conector de Telegram de Leila, sus mensajes entran con `source=telegram` en `leila`. Medido hoy: en `whatsapp-mcp` solo hay `telegram-connector` y `telegram-connector-professional`, ningún conector de Telegram de Leila. Si no hay cuenta, la historia lo documenta y el criterio queda cerrado como «no hay cuenta de Telegram de Leila que indexar», con `PARA IT:` si hace falta emparejar una (pairing humano).
- [ ] Sin fuga. Una búsqueda en `instance=personal` de una frase presente solo en un mensaje de Leila → 0 resultados.

## Restricciones
- Nada de reindexado desde cero ni cambios de ventana (INFRA-364); sin servidores nuevos.
- NUNCA filtrar el correo por remitente (restricción de INFRA-473). El correo se filtra por buzón de destino (`lays84.mv@gmail.com`).
- Movimiento de datos entre colecciones: copiar, verificar conteo y solo entonces borrar de `personal`; el borrado se anota en la Request semanal si security lo exige.
- Si INFRA-478 llega antes, el correo de Leila reutiliza su pipeline de buzones.

## Trabajo reciente (24 h)
- brain-windows activo en prod; INFRA-478 en In Progress; `social-identity-bindings` (13 d) liga a Leila a la cuenta WhatsApp `leila`.

## Diseño
Diseñador: no — es ingesta, sin interfaz.

## Historias previstas
- Enrutar cuentas de Leila a `leila` en `social-accounts` y en el job (dueño: developer).
- Backfill desde el índice del conector y limpieza de `personal` (dueño: developer; despliegue: devops).
- Correo `lays84.mv@gmail.com` hacia `leila`, coordinado con INFRA-478 (dueño: developer).
- Verificación de conteos por fuente y no-fuga (dueño: qa).

## Tamaño
M

## Dificultad
Dificultad: media — mueve datos privados entre vaults y el borrado en `personal` no se deshace sin backfill.
