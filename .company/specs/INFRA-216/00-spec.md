Rol: pm · Fecha: 2026-09-23T01:47:14Z · Sesión: ecf76879-a6f4-4dd6-9c29-d27200306691 · Estado: LISTO

# INFRA-216 — Puente Jira→Telegram: borrar el topic (deleteForumTopic) al cerrar una épica

## Objetivo

Que el cierre de topics de épicas en el grupo de Telegram BORRE el topic (`deleteForumTopic`) en vez de dejarlo cerrado y visible, con una comprobación previa de que el informe de cierre ya está publicado en Jira. Ninguna otra épica abierta cubre esto: SC-240 (el tablero de épicas en Synapse) fue RETIRADO el 17-09 — ver Trabajo reciente; lo vivo es el puente del host x86.

Repo: x86-host-runtime-pocharlies

## Dónde está el código (medido el 23-09 contra `origin/main` en `3735eff`, no es un recuerdo)

El puente real NO pasa por Synapse: es `libexec/hermes_bridge.py` (habla directo contra la Bot API de Telegram) desplegado por CI en `~/.local/libexec/x86-host-runtime/` y servido por la unidad `hermes-jira-bridge.service` (usuario `dibanez`). Checkout único: `~/src/x86-host-runtime-pocharlies` (tronco `main`; el árbol local está hoy en `main` limpio de esta épica — el trabajo sale de `origin/main`).

Los cuatro caminos de cierre convergen en UNA función, `cerrar_topic(key)` (hermes_bridge.py:706), que hoy llama `closeForumTopic` (:712) y ya captura `TOPIC_CLOSED` como éxito:

1. Botón "✅ Cerrar topic" → `GET /hermes/cerrar?key&t=HMAC` en `libexec/jira-epic-trigger.py:3547` → `hb.cerrar_topic(key)` (:3553); el texto de respuesta "cerrado ✅" está en :3556.
2. Barrido automático: `limpiar_topics()` (hermes_bridge.py:691) recorre el estado del puente y cierra los topics de épicas en Done/Cancelled — se invoca por CLI `python3 ~/.local/libexec/x86-host-runtime/hermes_bridge.py limpiar [--dry-run]` y es el "cierre automático al pasar a Done" que pide la épica (el flujo `cerrar_epica` del trigger publica el informe pero no toca el topic; el barrido es el que lo cierra).
3. Dani escribe `cerrar` dentro del topic (hermes_bridge.py:891).
4. CLI `hermes_bridge.py cerrar <KEY>` (línea 962).

Cambiar `cerrar_topic` cubre los cuatro. La salvaguarda ya es estructural: `topic_de(key, crear=False)` (:209) solo devuelve topics registrados en el fichero de estado del puente y `topics()` (:116) filtra por `KEY_RE` (:48) — las entradas de servicio como `_leyenda` se excluyen; hay test de ello (`test_las_entradas_de_servicio_no_son_epicas`). La suite hermética actual: 34 tests, `OK` medido el 23-09. El guard puede apoyarse en el helper `jira_rest()` (:825) — `jira_rest.py attachments <KEY>` y `jira_rest.py comments <KEY>` ya existen (verificado en `libexec/jira_rest.py:22,28`).

## Criterios de aceptación

- [ ] C1 — `cerrar_topic` borra en vez de cerrar (camino feliz). En `~/src/x86-host-runtime-pocharlies`, la suite hermética actualizada (los tests de cierre actuales assertan `closeForumTopic` en `ci/test_hermes_bridge.py:67` y `:320` — pasan a `deleteForumTopic`) pasa, y en la rama de éxito `cerrar_topic` no invoca `closeForumTopic`.
  Comando: `cd ~/src/x86-host-runtime-pocharlies && python3 -m unittest ci/test_hermes_bridge.py 2>&1 | tail -3`
  Esperado: `Ran NN tests ... OK` (NN ≥ 36, los 34 actuales más los nuevos de C2–C4) y `grep -n '"deleteForumTopic"' libexec/hermes_bridge.py` devuelve al menos una línea dentro de `cerrar_topic`.

- [ ] C2 — Idempotencia: borrar un topic ya inexistente no peta. Test hermético nuevo: con `deleteForumTopic` lanzando `RuntimeError("... 400: THREAD_ID_INVALID ...")` (y variantes `TOPIC_ID_INVALID` / `TOPIC_DELETED`), `cerrar_topic(key)` devuelve `True`, no relanza, y deja la marca `cerrado` en el estado.
  Comando: `cd ~/src/x86-host-runtime-pocharlies && python3 -m unittest ci/test_hermes_bridge.py -v 2>&1 | grep -i "borra\|delete\|invalid"`
  Esperado: al menos un test con ese tema listado `ok`.

- [ ] C3 — Guard de informe antes de borrar: `cerrar_topic` comprueba en Jira (vía `jira_rest("attachments", key)` / `jira_rest("comments", key)`) que `90-informe-cierre.html` está adjunto Y hay comentario de cierre con `Informe completo: <url>`. Con ambos → borra. Sin ellos → NO borra: hace `closeForumTopic` y manda al topic un aviso de por qué (el informe no está publicado). Dos tests herméticos, uno por rama.
  Comando: `cd ~/src/x86-host-runtime-pocharlies && python3 -m unittest ci/test_hermes_bridge.py 2>&1 | tail -3`
  Esperado: `OK`, y los dos tests nuevos del guard listados `ok` en `-v`.

- [ ] C4 — Salvaguardia: ni una sola llamada a la Bot API para claves no registradas. Test: `cerrar_topic("SC-9999")` (no está en el estado) devuelve `False` con cero llamadas api; el filtro de `topics()` sigue excluyendo `_leyenda` (test existente `test_las_entradas_de_servicio_no_son_epicas` intacto).
  Comando: `cd ~/src/x86-host-runtime-pocharlies && python3 -m unittest ci/test_hermes_bridge.py -v 2>&1 | grep -E "entradas_de_servicio|no_existe|9999"`
  Esperado: `ok` en ambos.

- [ ] C5 — Desplegado y visible en producción (no el semáforo de GitOps: el fichero vivo). Tras merge a `main` y paso del CI:
  Comando: `grep -c '"deleteForumTopic"' ~/.local/libexec/x86-host-runtime/hermes_bridge.py && systemctl --user is-active hermes-jira-bridge`
  Esperado: `≥1` y `active`.

- [ ] C6 — E2E con una épica de prueba creada a propósito, cerrada de punta a punta: se crea una épica de prueba en INFRA (título `PRUEBA INFRA-216`), el puente le registra topic (un aviso la crea), se le adjunta `90-informe-cierre.html` y comentario de cierre con `Informe completo:`, se pasa a Done y se ejecuta el barrido real: `python3 ~/.local/libexec/x86-host-runtime/hermes_bridge.py limpiar --dry-run` (debe listarla) y `... limpiar`. Prueba del botón: invocar `GET /hermes/cerrar?key=<K>&t=<firma>` (la firma la da `hb.url_cerrar(K)` o `hb.firma`) antes del barrido, o documentar ambos caminos. Evidencia de borrado (Telegram no da una API para enumerar topics — medido 19-09): una sonda `sendMessage` al `message_thread_id` viejo falla con `400 THREAD_ID_INVALID`, y captura visual del topic ausente. La épica de prueba se cancela al acabar y su topic queda borrado.
  Comando (sonda, con el tid del estado del puente — la ruta real del `topics.json` la documenta la entrega): `python3 -c 'import sys; sys.path.insert(0,"/home/dibanez/.local/libexec/x86-host-runtime"); import hermes_bridge as hb; hb.api("sendMessage", chat_id=hb.CHAT, message_thread_id=<TID>, text="sonda")'`
  Esperado: `RuntimeError` cuyo texto contenga `THREAD_ID_INVALID`.

- [ ] C7 — Sin regresión: épicas abiertas y topics normales intactos. Tras el despliegue y el E2E, el barrido en seco solo lista épicas Done/Cancelled con topic abierto, y el log de la unidad no muestra errores nuevos de topic para épicas vivas.
  Comando: `python3 ~/.local/libexec/x86-host-runtime/hermes_bridge.py limpiar --dry-run` y `journalctl --user -u hermes-jira-bridge --since "<hora del merge>" -p warning --no-pager | grep -c THREAD_ID_INVALID`
  Esperado: el dry-run lista solo épicas cerradas (o `{}`); el grep da `0`.

## Restricciones

- Todo el cambio vive en `libexec/hermes_bridge.py` (+ `ci/test_hermes_bridge.py`, y como mucho el texto de respuesta del endpoint en `jira-epic-trigger.py:3556` "cerrado ✅" → "borrado ✅"). Nada en Synapse: el adapter ya tiene una acción `delete_topic` que este puente NO usa, y su docstring "no flow may use deleteForumTopic" refería al tablero SC-240, retirado — no resucitarlo ni tocarlo.
- Borrar es irreversible: el guard C3 SIEMPRE corre antes de `deleteForumTopic`. Si la comprobación en Jira falla por error de red/transitorio, se trata como "no verificado" → cerrar + aviso, no borrar a ciegas.
- La marca de estado `cerrado` se sigue escribiendo igual que hoy (hermes_bridge.py:716-718): es lo que usa el latido para no volver a tocar el topic (icono, `editMessage` — PRs #226/#227, y el test `test_un_topic_cerrado_no_vuelve_a_tocar_el_icono`). Borrar sin marcar deja al heartbeat petando contra un topic muerto.
- Nunca borrar topics no registrados por el puente (Telegram no permite enumerar topics: el estado del puente es la única lista; no inventar un escaneo del canal).
- DECISIÓN TOMADA (pm, mantenida del plan anterior): el guard verifica Jira (adjunto + comentario de cierre), no Confluence. La épica menciona la página GOB, pero el puente no tiene cliente de Confluence y Jira es el disco de verdad del informe; hacer la limpieza dependiente de un espejo secundario sería bloquearla. Si Dani quiere también Confluence, es un criterio nuevo, no una reinterpretación.
- Rama desde `origin/main`, PR contra `main`, merge automático con CI verde (regla del repo).
- Los comandos E2E tocan el grupo real de Telegram: usar SOLO la épica de prueba propia; nada de cerrar topics de épicas ajenas.

## Trabajo reciente (24 h)

- Nada en las últimas 24 h que cambie este plan. Medido el 23-09: ningún commit en el repo toca `hermes_bridge.py` ni `test_hermes_bridge.py` en 24 h (sí `jira-epic-trigger.py`, por el prefijo del id de la épica en el nombre de sesión — 88f1eab, no toca `/hermes/cerrar`). Única sesión VIVA en el área: esta misma sesión de plan.
- Contexto que pisa este terreno (fuera de 24 h, sigue vigente):
  - 17-09, synapse `a4bcfa36` (#204): el tablero Telegram de épicas (SC-240) fue RETIRADO — `jira_board/` borrado. La premisa de la épica "webhook Jira → Synapse → bot" está muerta; el puente vivo es `hermes_bridge.py` en x86-host-runtime hablando directo con la Bot API. Este spec está escrito contra el código vivo.
  - 20-09, sesión `33283bc9`, PRs #226/#227 (desplegadas): los topics con marca `cerrado` no vuelven a tocar icono ni `editForumTopic` — de ahí la restricción de mantener la marca al borrar.
  - 19-09, misma sesión: `limpiar [--dry-run]` es el barrido que cierra topics de épicas Done/Cancelled, y Telegram no expone una API para enumerar topics (solo se alcanza lo que el puente conoce) — de ahí la evidencia por sonda de C6.
- Nota de re-plan: este spec reemplaza al de la sesión `7c7081f7` (21-09, también LISTO). Los números de línea han cambiado con los merges de la semana (`cerrar_topic` pasó de :623 a :706, el endpoint de :2976 a :3547); el contenido de los criterios no cambia.

## Historias previstas

1. Borrar el topic en `cerrar_topic`: guard de informe + idempotencia + salvaguardia, con tests herméticos (C1–C4) — dueño: developer.
2. Despliegue y prueba E2E con épica de prueba, sin regresión (C5–C7), evidencia en `50-entrega.md` — dueño: devops (la parte de merge/CI) con el E2E documentado por developer o qa.

## Tamaño

S — un fichero de lógica + su suite hermética + un E2E contra Telegram; dos historias, un repo, menos de un día de CTO.
