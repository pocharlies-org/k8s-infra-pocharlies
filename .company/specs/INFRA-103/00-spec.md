Rol: pm · Fecha: 2026-10-08T09:25:00Z · Sesión: dfce1e5d-60b5-4499-9f50-8cf33283cb3b · Estado: FALTA INFO

## Valor
Quien depende de Telegram y WhatsApp para recibir mensajes de clientes y avisos de Synapse, no lo nota; lo que cambia es que el gateway deja de tener entradas que nadie usa. Si no se hace, el gateway sigue publicando a colas que se acumulan y el plan de limpieza de Synapse se queda a medias.

## Diseño
Diseñador: no — retirada de código y configuración; ninguna pantalla ni superficie nueva.

## Dificultad
Dificultad: alta — borra colas de RabbitMQ, suscripciones de Pub/Sub y registros de webhook de Telegram. Eso no se deshace con un revert: se pierden mensajes y configuración. El código del gateway sí se revierte.

## Objetivo
Retirar del gateway los providers telegram, telegram_customer y whatsapp, con sus rutas de webhook, sus colas de entrada, sus claves del ExternalSecret y los dos workflows inertes ops.delete-message y ops.alert-discard. Gmail queda fuera por decisión de Dani del 04-10 (comentario 21293 de INFRA-103, ligada a INFRA-473). Sujeto a la pregunta de abajo: hoy esas colas tienen consumidor.

Repo: synapse
Repo (GitOps): k8s-synapse-pocharlies (tronco deploy/prod; ArgoCD app synapse, path k8s, sync manual, prune solo por el operador)

## Pregunta para Dani
Hoy las colas adapter.telegram.ingress, adapter.telegram.customer_ingress y adapter.whatsapp.webhooks tienen consumidor: el 28-09 se midieron adapter.telegram.customer_ingress y adapter.whatsapp.webhooks con un consumidor cada una (comentario 16014; adapter.telegram.ingress no se midió), y en sauvage siguen activas las unidades synapse-adapter-telegram y synapse-adapter-whatsapp. Retirar los providers corta esas entradas. ¿Apagamos en esta épica las entradas de Telegram (ingesta y clientes) y de WhatsApp, con sus unidades de sauvage, o la épica se queda en quitar código y configuración sin tocar colas ni webhooks?

## Medido hoy (08-10, 09:20Z)
- Tronco synapse main = 400c9d22. Tronco GitOps deploy/prod = f7f54e4. La app ArgoCD synapse está Synced y Healthy en f7f54e4.
- k8s/configs/gateway.yaml no tiene clave gateway.providers: su bloque es webhooks, con shopify, gmail, stripe, telegram y github_actions. No aparecen whatsapp ni telegram_customer en el fichero del tronco.
- Código del gateway (services/synapse-gateway/src): _WEBHOOK_PROVIDERS lista diez providers (shopify, gmail, stripe, telegram, telegram_customer, whatsapp, instagram, github_actions, jira, alertmanager). Las rutas de webhook están en main.py: /webhooks/whatsapp (l.233), /webhooks/telegram (l.276) y /webhooks/telegram/customer (l.303). Quedan fuera de la épica /webhooks/instagram (l.252), /webhooks/jira (SC-259; el receptor de Jira, cuyo secreto es jira.webhook.secret) y /webhooks/gmail.
- Credenciales por provider (config.py): telegram usa telegram.webhook.secret, telegram_customer usa telegram_customer_webhook.secret y whatsapp usa whatsapp.webhook.secret. Ninguna de esas tres es una clave explícita de synapse-secrets.
- k8s/eso/externalsecret-prod.yaml (synapse-secrets) tiene cinco secretKey explícitas: telegram_bot.token, agentgateway.draft.client_secret, synapse_admin.http.password, shopify_admin_token.skirmshop y jira.api.token. Además tiene dataFrom.extract key synapse-prod: trae toda la ítem de 1Password, así que quitar una clave no es borrar una línea.
- Workflows: workflows/_ops/ops.delete-message.v1.yaml y workflows/_ops/alert-discard.v1.yaml existen en main. Hay 167 ficheros bajo workflows/ en main.
- Registro de contratos (libs/synapse-contracts/registry.yaml): webhook.telegram.received (l.4286), webhook.telegram_customer.received (l.4305) y webhook.whatsapp.received (l.4318). CONTRACTS.yaml no lista estas superficies.
- Unidades systemd --user en sauvage: synapse-adapter-telegram y synapse-adapter-whatsapp, activas (running). El adapter de gmail ya no es unidad de sauvage: corre como pod en k8s (synapse-adapter-gmail, 94 min).
- Pods y endpoints de synapse (08-10): gateway en dos réplicas (sauvage y ks5-cp-2), endpoints de dispatcher, engine, admin, gmail, shopify, reminders y demás vivos. Esta es la línea base del criterio 6.
- Colas /synapse y config viva del pod del gateway: NO medidas. El rol PM no tiene permiso de exec al cluster; ver Bloqueo 9.

## Bloqueos antes de escribir historias
El CTO los resuelve con el operador. Ninguno lo ejecuta un rol.
1. Bots de Telegram. Hay que nombrar cada token: qué bot es de ingesta, cuál es de clientes y cuál es el de notificaciones de SC-240 (ese no se toca). Comando del operador por bot: curl -s "https://api.telegram.org/bot$TOKEN/getWebhookInfo", salida pegada en la historia.
2. Claves del ExternalSecret. Dos cosas: qué claves salen de la ítem synapse-prod (solo las que usaban en exclusiva los providers retirados) y confirmación escrita de que el receptor de Jira no usa ninguna de ellas. jira.api.token y jira.webhook.secret no se tocan.
3. Frontera con SC-240. La clave SC-240 responde como SC-662 (mismo id 10609, «Épica 4 — Telegram como sistema de notificaciones de la compañía»), Done desde el 01-10 y asignada al CTO. La épica dice In Progress y «esperando jira.webhook.secret». El CTO confirma si son la misma épica y qué webhook vivo queda para SC-240.
4. Orden con GitOps 119. No aplica: #119 se fusionó el 11-09. No hay orden que decidir.
5. Precondición SC-319. Esta épica va después de SC-319 F1 (synapse #188, borra 125 workflows disabled) y F2 (#189, borra servicios muertos). Están abiertas desde el 11-09 y sin fusionar en main. El criterio de «workflows loaded count=27» depende de F1: hoy el número de ficheros en workflows/ no es 29. El CTO decide si F1 entra antes.
6. Solape con INFRA-97. Su criterio 7 borra services/synapse-adapter-gmail, -telegram y -whatsapp. Lo de gmail contradice la decisión del 04-10. Telegram y whatsapp siguen vivos en sauvage desde ese código: borrar el código antes de retirar sus unidades deja un reinicio sin fuente. Esta épica no borra esos adapters; INFRA-97 se recorta (su spec no es de esta épica).
7. Nombres de colas. El registro las llama adapter.telegram.ingress, adapter.telegram.customer_ingress y adapter.whatsapp.webhooks (registry.yaml l.4299, l.4317, l.4330). Son tres, no cuatro: gmail queda.
8. Meta. No sé si el webhook de WhatsApp Cloud registrado en Meta apunta a /webhooks/whatsapp. Si apunta, quitar la ruta devuelve 404 a Meta. El operador lo mira en la consola de Meta antes de la historia del gateway.
9. Lecturas que hace el operador (el rol PM no puede): kubectl -n databases exec shared-rabbitmq-0 -- rabbitmqctl list_queues -p /synapse name messages consumers, y kubectl -n synapse get cm synapse-config -o yaml para la config viva. Salida pegada en la historia.

## Criterios de aceptación
Revisados el 08-10 por dos hechos nuevos: la decisión de Dani del 04-10 (gmail queda) y lo medido arriba (la clave gateway.providers no existe; la cola y el provider reales son tres). Son decisiones nuevas, no ajustes para que la entrega encaje.

- [ ] 1. El gateway vivo no carga telegram, telegram_customer ni whatsapp. Gmail no entra en la lista.
  Comando: kubectl -n synapse exec deploy/synapse-gateway -- cat /etc/synapse/gateway.yaml | grep -n -E "^  (telegram|telegram_customer|whatsapp):"
  Esperado: sin salida. Y en código: grep -rn -E "telegram_customer|\"whatsapp\"" services/synapse-gateway/src → sin coincidencias.

- [ ] 2. Las rutas retiradas dejan de existir: un POST a /webhooks/whatsapp, /webhooks/telegram y /webhooks/telegram/customer devuelve 404 o 410, y ninguna cola de /synapse sube su publish por esa petición.
  Comando: curl -s -o /dev/null -w "%{http_code}\n" -X POST https://synapse.e-dani.com/webhooks/telegram (las tres rutas). Contador antes y después: API de gestión, ver criterio 7.
  Esperado: 404 o 410 en las tres; contador igual antes y después.

- [ ] 3. /webhooks/jira y /webhooks/gmail siguen respondiendo y no devuelven 404 por esta causa.
  Comando: curl -s -o /dev/null -w "%{http_code}\n" -X POST https://synapse.e-dani.com/webhooks/jira -H "Content-Type: application/json" -d "{}" (igual para /webhooks/gmail).
  Esperado: 401, 403 o 400 (rechaza la firma). Nunca 404.

- [ ] 4. Las claves retiradas del ExternalSecret son exactamente las aprobadas en el bloqueo 2. jira.api.token y jira.webhook.secret no se tocan. El número de claves sincronizadas se cuenta antes y después, sin imprimir valores.
  Comando: git show origin/deploy/prod:k8s/eso/externalsecret-prod.yaml | grep -c "secretKey:" (antes: 5) y kubectl -n synapse get secret synapse-secrets -o jsonpath="{.data}" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" (antes y después).
  Esperado: el diff quita solo las claves aprobadas; jira.api.token sigue en el fichero; el conteo de claves baja solo en las retiradas.

- [ ] 5. Los workflows ops.delete-message y ops.alert-discard no están en disco y el engine arranca con «workflows loaded count=27».
  Comando: git ls-tree -r --name-only origin/main workflows | grep -c -E "ops\.delete-message|alert-discard" y kubectl -n synapse logs deploy/synapse-engine | grep "workflows loaded count=".
  Esperado: 0 en el primero; «workflows loaded count=27» en el segundo. Solo se cumple con SC-319 F1 en main (bloqueo 5).

- [ ] 6. Los endpoints vivos de synapse no cambian: los mismos servicios, las mismas IP y los mismos puertos antes y después.
  Comando: kubectl -n synapse get endpoints | tee antes.txt (línea base del 08-10 en la sección Medido); mismo comando después con tee despues.txt; y diff antes.txt despues.txt.
  Esperado: diff vacío para gateway, dispatcher, engine, admin, gmail, shopify, reminders y demás servicios vivos.

- [ ] 7. El contador publish de synapse.unroutable está estable durante 24 h.
  Comando: dos lecturas separadas 24 h de curl -s -u "$RMQ_USER:$RMQ_PASS" "http://shared-rabbitmq.databases.svc.cluster.local:15672/api/queues/%2Fsynapse/synapse.unroutable?columns=name,message_stats.publish" (rabbitmqctl 3.13 no da publish; se lee por la API de gestión desde un pod del ns synapse).
  Esperado: el valor no sube entre las dos lecturas. La primera lectura es la línea base; no se compara con ninguna anterior.

- [ ] 8. Las tres colas de entrada ya no existen en /synapse. Las DLQ y las colas fuera de alcance siguen igual.
  Comando: kubectl -n databases exec shared-rabbitmq-0 -- rabbitmqctl list_queues -p /synapse name messages consumers | grep -E "telegram|whatsapp". Antes de cada borrado, comprobar que ningún consumidor vivo queda colgado de la cola o de su DLQ (lección de INFRA-294).
  Esperado: sin las tres colas; dlq.* y synapse.unroutable presentes con el conteo de antes; conteo total antes y después pegado.

- [ ] 9. Cada acción externa se pide al operador con su comando exacto, y su salida queda pegada en la historia. Ningún rol la ejecuta.
  Comando: jira_get_issue INFRA-103 con include=comments.
  Esperado: una entrada por acción (deleteWebhook por bot, suscripción de Pub/Sub, borrado de cada cola), cada una con comando y salida del operador.

- [ ] 10. Las tres entradas de registro de webhook pasan a deprecated (nunca se borran) y el push lleva el trailer Contract-Change.
  Comando: grep -n -A8 -E "^  webhook\.(telegram|telegram_customer|whatsapp)\.received:" libs/synapse-contracts/registry.yaml | grep -E "deprecated"; git log -1 --format=%B | grep "Contract-Change:"; python3 scripts/contracts/seed_registry.py --check.
  Esperado: tres líneas deprecated; trailer presente; el gate sale con código 0. CONTRACTS.yaml no lista estas superficies: sin cambio ahí, dicho aquí.

- [ ] 11. Documentación: cada criterio cumplido nombra el documento que lo refleja, o dice explícitamente que no hacía falta.
  Comando: grep -rn -E "telegram_customer|/webhooks/whatsapp|/webhooks/telegram" services/synapse-gateway/README.md services/synapse-gateway/manifest.yaml docs/ → sin menciones vivas, o listadas una a una.
  Documentos que cambian: services/synapse-gateway/README.md y services/synapse-gateway/manifest.yaml (lista de rutas). El resto: sin cambio, dicho aquí.

- [ ] 12. Los tests del gateway pasan sin los providers retirados, y las rutas que se quedan siguen registradas.
  Comando: cd services/synapse-gateway && uv run pytest -q; y grep -n -E "/webhooks/(gmail|instagram|jira|github-actions|stripe|shopify)" services/synapse-gateway/src/synapse_gateway/main.py.
  Esperado: pytest sin fallos; las seis rutas aparecen en main.py.

## Restricciones
- Esta épica no borra código de los adapters telegram, whatsapp ni gmail: eso es INFRA-97 y se coordina con su recorte (bloqueo 6).
- Fuera de alcance: /webhooks/instagram (provider instagram, no listado; se decide aparte), /webhooks/gmail, /webhooks/jira, /webhooks/github-actions, /webhooks/stripe, /webhooks/shopify y alertmanager.
- Fuera de alcance: el topic de Pub/Sub y la suscripción de openclaw; el bot de notificaciones de SC-240; las colas dlq.*, synapse.unroutable y adapter.ops_explainer.failures, que no se borran ni se purgan.
- Acciones externas: deleteWebhook, borrado de suscripciones Pub/Sub (solo la suscripción, nunca el topic) y borrado de colas. Las pide el CTO al operador; ningún rol las ejecuta.
- Orden: PR de código primero; PR de GitOps después y sincronizado a mano por el operador (sync manual con prune). Nunca push directo al tronco, nunca --force.
- Secretos: nunca al host ni al log. El ExternalSecret se lee por nombres de clave, nunca por valores.

## Trabajo reciente (24 h)
- 08-10 06:48Z — INFRA-97 e INFRA-102 modificadas en el mismo segundo (campo updated). No he leído el historial completo: la respuesta de Jira es demasiado grande. Antes de tocar alcance, el CTO mira qué cambió.
- 08-10 06:40Z — sesión sre (agente a42ed16e, INFRA-740): métricas y alerta del adapter gmail. No toca el gateway.
- 08-10 — synapse main #233 a #240 y GitOps #181 a #186: adapter gmail y messaging. Ninguno toca services/synapse-gateway (git log de siete días sobre esa ruta, vacío) ni synapse-secrets.
- 08-10 06:13Z — GitOps PR #183 (INFRA-652, ARCHITECTURE de digest_destinos). No toca el gateway.
- Sesiones vivas: ninguna de las que lista pgrep nombra INFRA-103 ni el gateway en su línea de comando.
- Búsqueda de transcripts de 24 h: find devolvió 0 ficheros en ~/.claude/projects y en ~/.claude-company. El brain sí muestra actividad (líneas de arriba).
- Antecedentes (más de 24 h): brain sin ANALISIS INFRA-103. Previos relacionados: re-plan de INFRA-97 del 03-10 (que reserva ops.delete-message y ops.alert-discard para esta épica) y el comentario de Dani del 04-10 que deja gmail fuera.

## Historias previstas
- H1 · developer · synapse: quitar telegram, telegram_customer y whatsapp de services/synapse-gateway (config, providers, rutas, tests). Criterios 2 (código), 3, 12.
- H2 · developer · synapse: borrar workflows/_ops/ops.delete-message.v1.yaml y workflows/_ops/alert-discard.v1.yaml. Criterio 5. Tras SC-319 F1.
- H3 · devops · k8s-synapse-pocharlies: quitar el bloque telegram de k8s/configs/gateway.yaml, las claves aprobadas del ExternalSecret y el bump del gateway. Criterios 1, 4, 6.
- H4 · developer · synapse: registry deprecated (tres entradas), README y manifest del gateway. Criterios 10, 11.
- H5 · operador (acciones externas, no es rol): deleteWebhook por bot, suscripciones de Pub/Sub y borrado de colas con consumidor comprobado. Criterios 2 (contador), 8, 9.
- H6 · qa: evidencia de cada criterio en 70-qa.md, al final.
Orden: H2 después de SC-319 F1; H1 y H4 en el mismo PR de código; H3 después de H1 desplegado; H5 después de H3 sincronizado, y los contadores de la criterio 2 antes de borrar nada.

## Tamaño
M — dos repos (synapse y GitOps), tres providers, dos workflows, claves del ExternalSecret por evaluar, tres colas, tres entradas de contrato y cinco acciones externas que pide el operador. No se parte: es una sola superficie con un orden estricto.
