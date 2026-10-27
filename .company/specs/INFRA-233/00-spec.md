Rol: pm · Fecha: 2026-09-23T16:16:02Z · Sesión: 8a6e7cc0-2a9d-4c88-bfe5-0534b7327586 · Estado: LISTO

# INFRA-233 — PRUEBA INFRA-216b: el CLI `cerrar <KEY>` BORRA el topic con el informe publicado

## Objetivo

Verificar ejecutando, sobre esta misma épica, que `cerrar_topic` BORRA el topic de Telegram (`deleteForumTopic`) cuando el informe de cierre está publicado en Jira, por el **camino del CLI** `hermes_bridge.py cerrar INFRA-233`; acabada la prueba la épica se cancela. No hay trabajo de código: el cambio ya está fusionado y desplegado (INFRA-216 Done, PR 273 en `main` de x86-host-runtime, medido hoy); la épica hermana INFRA-232 prueba el camino del botón y NO se toca aquí.

Repo: x86-host-runtime-pocharlies

## Estado medido por pm (23-09 16:05–16:16Z, contra el sistema vivo — el CTO arranca de aquí, no lo repita)

- El código desplegado YA borra: `~/.local/libexec/x86-host-runtime/hermes_bridge.py:752` contiene `deleteForumTopic` dentro de `cerrar_topic` (guard `informe_publicado` :725, `TOPIC_IDA` :722); unidad `hermes-jira-bridge` `active`.
- Esta épica ya vivió un intento del test esta mañana (DevOps agent-aec20bca, sesión 419d188f): CLI `cerrar INFRA-233` devolvió `True`, topic 2870 borrado (sonda: `message thread not found`), marca `cerrado` escrita. Lo que aún debe esta épica: **un ciclo limpio con el discriminador medido y la cancelación** ("Al acabar la prueba se cancela" — sigue en Backlog).
- El estado del puente fija el tid muerto: `~/.company/jira-trigger/hermes-topics.json` tiene `INFRA-233 → {topic: 2870, ..., cerrado: 1790152054}` — `topic_de` devuelve el tid viejo y NO lo recrea; hay que retirar la entrada (CA1).
- **El guard de esta épica ya está en True** (medido por pm, lectura sola): `informe_publicado("INFRA-233") = True` — adjunto 11692 `90-informe-cierre.html` (10:23Z) + comentario 13537 con `Informe completo: <url>`. Es la rama positiva (borrar) la que dispara.
- **Discriminador borrado-vs-cerrado, medido por pm esta mañana sobre 2870**: un topic vivo (aunque esté cerrado) ACEPTA `sendMessage`; un topic borrado falla con `RuntimeError: sendMessage: Bad Request: message thread not found`. `getForumTopicInfo` NO sirve (devuelve `Not Found` incluso para topics vivos).
- El camino CLI: `python3 ~/.local/libexec/x86-host-runtime/hermes_bridge.py cerrar INFRA-233` → `print(cerrar_topic("INFRA-233"))` (líneas 1014-1015), imprime `True`. No necesita la firma HMAC (eso es del botón); es una llamada directa a la función de producción.
- **La transición a `Cancelled` está denegada para TODOS los roles** (medido por pm 10:51Z en INFRA-216: el guard responde "no role owns the transition to Cancel: pm may not make it"). Por eso CA6 es reportar a Dani, no forzar el estado.

## Criterios de aceptación

- [ ] CA1 — Topic fresco para INFRA-233 (se retira la entrada rancia del estado y se recrea, en UN solo proceso: `guardar_topics` escribe el fichero entero y el servicio `hermes-jira-bridge` corre en paralelo).
  Comando:
  ```
  python3 - <<'EOF'
  import sys; sys.path.insert(0, "/home/dibanez/.local/libexec/x86-host-runtime")
  import hermes_bridge as hb
  t = hb.topics(); t.pop("INFRA-233", None); hb.guardar_topics(t)
  print("TID", hb.topic_de("INFRA-233", titulo="PRUEBA INFRA-216b", crear=True))
  EOF
  ```
  Esperado: `TID <n>` con n ≠ 2870; el topic `INFRA-233 · PRUEBA INFRA-216b` aparece en el grupo de Telegram.

- [ ] CA2 — Entrada del guard verificada: el informe de cierre está publicado en Jira (adjunto `90-informe-cierre.html` + comentario con `Informe completo: <url>` — ya medido True; re-medir como evidencia del ciclo).
  Comando: `python3 -c 'import sys; sys.path.insert(0,"/home/dibanez/.local/libexec/x86-host-runtime"); import hermes_bridge as hb; print(hb.informe_publicado("INFRA-233"))'`
  Esperado: `True` (con `False`, NO seguir: la rama positiva requiere el informe; publicar adjunto+comentario y re-medir).

- [ ] CA3 — Ejecutado el camino CLI (la misma función `cerrar_topic` que invocan botón, barrido y «/cerrar»).
  Comando: `python3 ~/.local/libexec/x86-host-runtime/hermes_bridge.py cerrar INFRA-233`
  Esperado: `True` (un `False` significaría tid ausente: volver a CA1; un reintento por red transitoria de Telegram es válido, repetir el comando).

- [ ] CA4 — Evidencia del BORRADO (no del cierre): sonda `sendMessage` al TID de CA1 falla con el error medido para topics inexistentes.
  Comando (con el TID real de CA1):
  ```
  python3 - <<'EOF'
  import sys; sys.path.insert(0, "/home/dibanez/.local/libexec/x86-host-runtime")
  import hermes_bridge as hb
  try:
      hb.api("sendMessage", chat_id=hb.CHAT, message_thread_id=<TID>, text="sonda post-cierre")
      print("VIVO: el topic NO fue borrado (solo cerrado) → la prueba FALLA")
  except Exception as e:
      print("BORRADO:", str(e))
  EOF
  ```
  Esperado: `BORRADO: sendMessage: Bad Request: message thread not found`. El topic `INFRA-233 · PRUEBA INFRA-216b` ya no aparece en el grupo (captura visual opcional como evidencia secundaria).

- [ ] CA5 — Sin regresión: la marca `cerrado` queda escrita (el heartbeat no volverá a tocar el topic muerto) y el barrido en seco no propone tocar nada de esta épica.
  Comando: `python3 -c 'import sys,json; sys.path.insert(0,"/home/dibanez/.local/libexec/x86-host-runtime"); import hermes_bridge as hb; print(json.dumps(hb.topics().get("INFRA-233", {})))' && python3 ~/.local/libexec/x86-host-runtime/hermes_bridge.py limpiar --dry-run`
  Esperado: el JSON contiene la clave `"cerrado"`; el dry-run no lista `INFRA-233` (y solo lista épicas Done/Cancelled con topic vivo — DGX-182, SC-1177, SC-702, SC-710, ajenas e intactas).

- [ ] CA6 — La épica de prueba queda CANCELADA ("Al acabar la prueba se cancela") con un comentario final que enlace la evidencia (TID creado, salida del CLI `True`, sonda).
  Comando: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py gate INFRA-233 Cancelled` y luego la transición; verificación: `jira_get_issue INFRA-233 fields=status` → `Cancelled`.
  Esperado: status `Cancelled`. **Si el guard lo deniega (medido: lo deniega para todos los roles), NO se fuerza**: dejar la épica en Backlog con el topic borrado y la marca `cerrado` (el barrido la respeta igual) y reportar a Dani que la cancelación es su flecha. El criterio se cumple con la épica de prueba cerrada por Dani o con el bloqueo documentado; lo que NO vale es dejarla abierta sin decirlo.

## Restricciones

- Cero cambios de código ni de despliegue. Si la prueba descubre un defecto en el puente, NO se arregla aquí: Request/épica nueva con la evidencia, y se reporta.
- **Coordinar con la épica hermana INFRA-232** (camino del botón): las dos reescriben `hermes-topics.json` vía `guardar_topics` (fichero entero, y el servicio `hermes-jira-bridge` escribe en paralelo). NO ejecutar los dos ciclos a la vez; retirar y recrear SOLO la entrada de INFRA-233, nunca la de INFRA-232.
- Solo se toca el topic de INFRA-233. No sondear ni cerrar topics de otras épicas.
- La edición de `hermes-topics.json` es SOLO retirar la entrada de INFRA-233 y en el mismo proceso (CA1); no reescribir el fichero a mano con otro editor.
- La rama negativa (sin informe → cierra sin borrar) NO se prueba aquí — la cubre su propio test; esta épica es la rama positiva por el CLI.

## Trabajo reciente (24 h)

- 23-09 07:47Z — PR x86-host-runtime #273 fusionada a `main` (squash `3ecce40`), CI desplegado al x86; `cerrar_topic` con `deleteForumTopic` + guard, verificado por QA en el fichero vivo. Sesión CTO 419d188f: INFRA-216 Done, historias INFRA-227/228 Done. → El trabajo de esta épica es solo la verificación E2E por el CLI y su cancelación.
- 23-09 ~08:23–08:25Z — DevOps (agent-aec20bca) usó INFRA-232 (botón) e INFRA-233 (CLI) como vehículos: topics 2868/2870 creados, informe publicado, ambos borrados (sondas: `message thread not found`). Las épicas NO se cancelaron → eso y el ciclo con discriminador medido es lo que queda.
- 23-09 10:51Z — comentario de cierre del PM en INFRA-216: la transición a `Cancelled` está denegada para todos los roles; 232/233 quedan en Backlog con topic borrado y marca `cerrado`; cancelación pendiente de Dani.
- 23-09 15:47Z — sesión de plan hermana (pm 193f13ac) dejó INFRA-232 en LISTO (camino del botón). Esta sesión (pm 8a6e7cc0) deja INFRA-233 (camino del CLI).
- Radar 16:10Z: ninguna sesión viva trabaja en INFRA-233 salvo esta de plan.

## Diseño

Diseñador: no — no hay interfaz nueva ni cambiada: se ejecuta un comando CLI existente (`hermes_bridge.py cerrar`) y se verifica su efecto en Telegram con sondas a la Bot API.

## Historias previstas

- H1 — E2E del CLI sobre INFRA-233: topic fresco, guard verificado, `cerrar` ejecutado, sonda de borrado, sin regresión y épica cancelada (CA1–CA6). Dueño: **devops** (es un ciclo sobre el sistema vivo, sin código). Una sola historia.

## Tamaño

S — sin código: cinco comandos contra el puente desplegado y una transición de Jira (que el guard puede denegar → reportar a Dani); ~15 min de ejecución.
