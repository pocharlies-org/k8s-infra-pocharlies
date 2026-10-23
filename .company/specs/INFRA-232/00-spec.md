Rol: pm · Fecha: 2026-09-23T15:47:36Z · Sesión: 193f13ac-629d-4145-88aa-7f2d297d1d8d · Estado: LISTO

# INFRA-232 — PRUEBA INFRA-216: el botón /hermes/cerrar BORRA el topic con el informe publicado

## Objetivo

Verificar ejecutando, sobre esta misma épica, que `cerrar_topic` BORRA el topic de Telegram (`deleteForumTopic`) cuando el informe de cierre está publicado en Jira, por el camino del botón `GET /hermes/cerrar`; acabada la prueba la épica se cancela. No hay trabajo de código: el cambio ya está fusionado y desplegado (INFRA-216 Done, PR 273 en `main` de x86-host-runtime, medido hoy); la épica hermana INFRA-233 prueba el camino CLI y NO se toca aquí.

Repo: x86-host-runtime-pocharlies

## Estado medido por pm (23-09 15:30–15:47Z, contra el sistema vivo — el CTO arranca de aquí, no lo repita)

- El código desplegado YA borra: `~/.local/libexec/x86-host-runtime/hermes_bridge.py:752` contiene `deleteForumTopic` dentro de `cerrar_topic` (guard `informe_publicado` :725, `TOPIC_IDA` :722); unidad `hermes-jira-bridge` `active`.
- Esta épica ya vivió un intento del test esta mañana (DevOps agent-aec20bca, sesión 419d188f): topic 2868 creado ~08:23Z, informe adjuntado (attachment 11691 `90-informe-cierre.html`, 08:23Z) y comentario de cierre con `Informe completo:` (13536), topic cerrado en el estado a las 08:25Z. La sonda de pm a 2868 devuelve `message thread not found` → el topic fue BORRADO. Pero faltó lo que esta épica aún debe: un ciclo limpio con el discriminador medido y **la cancelación de la épica** ("Al acabar la prueba se cancela" — sigue en Backlog).
- El estado del puente fija el tid muerto: `hermes-topics.json` tiene `INFRA-232 → topic 2868, cerrado` — `topic_de` devuelve el tid viejo y NO lo recrea; hay que retirar la entrada (CA1).
- **Discriminador borrado-vs-cerrado, medido por pm hoy**: un topic vivo (aunque esté cerrado) ACEPTA `sendMessage` (sonda a INFRA-98/1952, cerrado pre-deploy: OK — dejó un mensaje "sonda PM" cosmético, no repetir); un topic borrado falla con `RuntimeError: sendMessage: Bad Request: message thread not found` (sondas a 2868 y 2870). `getForumTopicInfo` NO sirve (devuelve `Not Found` incluso para topics vivos — medido).
- El guard de esta épica ya está en True (informe de esta mañana válido como entrada del test; ver CA2).
- El endpoint del botón: `jira-epic-trigger.py` (unidad `jira-epic-trigger`, escucha `100.83.56.98:19911` — tailnet del x86, medido en el `LISTEN_HOST` del código) → `/hermes/cerrar?key&t=HMAC` → `hb.cerrar_topic(key)`. Su texto de respuesta sigue diciendo "cerrado ✅" aunque borre (cosmético, no cambiarlo en esta prueba).

## Criterios de aceptación

- [ ] CA1 — Topic fresco para INFRA-232 (se retira la entrada rancia del estado y se recrea, en UN solo proceso: `guardar_topics` escribe el fichero entero y el servicio corre en paralelo).
  Comando:
  ```
  python3 - <<'EOF'
  import sys; sys.path.insert(0, "/home/dibanez/.local/libexec/x86-host-runtime")
  import hermes_bridge as hb
  t = hb.topics(); t.pop("INFRA-232", None); hb.guardar_topics(t)
  print("TID", hb.topic_de("INFRA-232", titulo="PRUEBA INFRA-216", crear=True))
  EOF
  ```
  Esperado: `TID <n>` con n ≠ 2868; el topic `INFRA-232 · PRUEBA INFRA-216` aparece en el grupo de Telegram.

- [ ] CA2 — Entrada del guard verificada: el informe de cierre está publicado en Jira (adjunto `90-informe-cierre.html` + comentario con `Informe completo: <url>` — los de esta mañana valen; si el CTO re-publica el suyo, mejor evidencia).
  Comando: `python3 -c 'import sys; sys.path.insert(0,"/home/dibanez/.local/libexec/x86-host-runtime"); import hermes_bridge as hb; print(hb.informe_publicado("INFRA-232"))'`
  Esperado: `True` (con `False`, NO seguir: el test de la rama positiva requiere el informe; publicar adjunto+comentario y re-medir).

- [ ] CA3 — Pulsado el botón (el mismo endpoint que el botón «✅ Cerrar topic» de Telegram, firma HMAC).
  Comando: `curl -s "http://100.83.56.98:19911/hermes/cerrar?key=INFRA-232&t=$(python3 -c 'import sys; sys.path.insert(0,"/home/dibanez/.local/libexec/x86-host-runtime"); import hermes_bridge as hb; print(hb.firma("INFRA-232"))')"`
  Esperado: `Topic de INFRA-232 cerrado ✅. Ya puedes cerrar esta pestaña.` (respuesta 200; el texto "cerrado" no es la evidencia del borrado — lo es CA4).

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
  Esperado: `BORRADO: sendMessage: Bad Request: message thread not found`. Además: el topic `INFRA-232 · PRUEBA INFRA-216` ya no aparece en el grupo (captura visual opcional como evidencia secundaria).

- [ ] CA5 — Sin regresión: la marca `cerrado` queda escrita (el heartbeat no volverá a tocar el topic muerto) y el barrido en seco no propone tocar nada de esta épica.
  Comando: `python3 -c 'import sys,json; sys.path.insert(0,"/home/dibanez/.local/libexec/x86-host-runtime"); import hermes_bridge as hb; print(json.dumps(hb.topics().get("INFRA-232", {})))' && python3 ~/.local/libexec/x86-host-runtime/hermes_bridge.py limpiar --dry-run`
  Esperado: el JSON contiene la clave `"cerrado"`; el dry-run no lista `INFRA-232` (y solo lista épicas Done/Cancelled con topic vivo).

- [ ] CA6 — La épica queda CANCELADA ("Al acabar la prueba se cancela") con un comentario de progreso final que enlace la evidencia (TID creado, respuesta del botón, sonda).
  Comando: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py gate INFRA-232 Cancelled` (el gate dice qué falta) y luego la transición; verificación: `mcp__atlassian__jira_get_issue INFRA-232 fields=status` → `Cancelled`.
  Esperado: status `Cancelled`. Si el flujo de la compañía exige cerrar por otro estado, el CTO lo decide y lo deja escrito en el comentario — el criterio es que la épica de prueba NO quede abierta.

## Restricciones

- Cero cambios de código ni de despliegue. Si la prueba descubre un defecto en el puente, NO se arregla aquí: Request/épica nueva con la evidencia, y se reporta.
- Solo se toca el topic de INFRA-232. No sondear ni cerrar topics de otras épicas (la sonda de calibración de pm a INFRA-98/1952 dejó un mensaje "sonda PM" — no repetir la operación).
- La edición de `hermes-topics.json` es SOLO retirar la entrada de INFRA-232 y en el mismo proceso (CA1); no reescribir el fichero a mano con otro editor.
- El secreto HMAC (`~/.company/jira-trigger/secret`) no se imprime ni se copia: la firma se genera con `hb.firma()` como en CA3.
- La rama negativa (sin informe → cierra sin borrar) NO se prueba aquí — la cubre su propio test (INFRA-233 es el camino CLI de la rama positiva; si Dani quiere la negativa, es otra épica de prueba).

## Trabajo reciente (24 h)

- 23-09 07:47Z — PR x86-host-runtime #273 fusionada a `main` (squash `3ecce40`), CI desplegado al x86; `cerrar_topic` con `deleteForumTopic` + guard, verificado por QA (agent-aef2c3a) en el fichero vivo. Sesión CTO 419d188f: INFRA-216 Done, historias INFRA-227/228 Done. → El trabajo de esta épica es solo la verificación E2E y su cancelación.
- 23-09 ~08:23–08:25Z — DevOps (agent-aec20bca) usó INFRA-232 (botón) e INFRA-233 (CLI) como vehículos: topics 2868/2870 creados, informe publicado, ambos borrados (sondas pm: `message thread not found`). Las épicas NO se cancelaron → eso y el ciclo con discriminador medido es lo que queda.
- 23-09 15:32Z — esta sesión de plan (pm 193f13ac): mediciones de la sección "Estado medido". Ninguna sesión viva trabaja en esto (radar 15:30Z).

## Diseño

Diseñador: no — no hay interfaz nueva ni cambiada: se ejerce un botón existente («✅ Cerrar topic» → `GET /hermes/cerrar`) y se verifica su efecto en Telegram con sondas a la Bot API.

## Historias previstas

- H1 — E2E del botón sobre INFRA-232: topic fresco, guard verificado, botón pulsado, sonda de borrado, sin regresión y épica cancelada (CA1–CA6). Dueño: **devops** (es un ciclo sobre el sistema vivo, sin código). Una sola historia.

## Tamaño

S — sin código: seis comandos contra el puente desplegado y una transición de Jira; ~15–20 min de ejecución.
