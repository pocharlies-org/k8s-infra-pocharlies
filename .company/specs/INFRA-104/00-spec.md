Rol: pm · Fecha: 2026-10-08T09:27:23Z · Sesión: 5a6418a7-f9c3-48cc-82f9-dd38b437a308 · Estado: LISTO

## Valor
Quien opera Synapse tiene un sistema con solo lo que de verdad funciona. Si no se hace, cinco piezas siguen encendidas sin que nadie les mande trabajo, y cada limpieza futura tropieza con ellas.

## Objetivo
Cada uno de los cinco programas (expenses, trellis, reminders, messaging-media, messaging-contact-sync) sale con una decisión escrita, retirado o conservado con su publicador vivo nombrado, y ejecutada: la retirada es un PR contra el tronco de GitOps y otro contra el de código, nunca un borrado a mano.

Repo: pocharlies-org/synapse (código, tronco main), con pocharlies-org/k8s-synapse-pocharlies (GitOps, tronco deploy/prod, app ArgoCD synapse).

## Medido hoy (2026-10-08)
- synapse origin/main = 400c9d22. k8s-synapse-pocharlies origin/deploy/prod = f7f54e4, la revisión que ArgoCD tiene sincronizada (Synced Healthy).
- ArgoCD app synapse: syncPolicy automated, prune true, selfHeal true. La descripción de la épica dice sync manual y no es así. Un merge a deploy/prod retira del clúster en cuanto sincroniza. Comando: `kubectl get application synapse -n argocd -o jsonpath='{.spec.syncPolicy}'`. Salida: `{"automated":{"prune":true,"selfHeal":true},...}`.
- `kubectl get deploy -n synapse` (antes, 2026-10-08): 17 Deployments. De los cinco: expenses 0/0, messaging-media 0/0, messaging-contact-sync 0/0, reminders 1/1, trellis 1/1. Vivos además: messaging-send 1/1 (SYNAPSE_COMMAND_ACTIONS = send,send_draft,pin_message,close_topic), voicelab 1/1, gmail 1/1 (desde 2026-10-04 16:12Z, digest 01f2179c).
- Ficheros en main: services/synapse-adapter-expenses, -trellis y -reminders existen. services/synapse-adapter-messaging-media y -messaging-contact-sync NO existen: son Deployments de la imagen de messaging, cuyo código vive en services/synapse-adapter-messaging (lo opera INFRA-102, 2/5). El ScaledObject está en la GitOps como k8s/keda/scaledobject-vision-window.yaml.
- GitOps k8s/kustomization.yaml (deploy/prod): líneas 51 (keda), 60 (expenses), 62 (messaging-media), 63 (messaging-contact-sync), 65 (reminders), 67 (trellis); configs en 125 (configs/expenses-tenants.yaml), 127 (configs/adapter-expenses.yaml), 130 (configs/adapter-reminders.yaml), 132 (configs/adapter-trellis.yaml). El pin del trío messaging-drafts (send, media y contact-sync juntos) está en las líneas 253-290; las 283 y 290 nombran media y contact-sync.
- Claves ExternalSecret propias de estos programas en k8s/eso: ninguna (git grep vacío).
- Workflows (lectura de /api/v1/workflows): family.tasks.push-to-reminders y skirmshop.tasks.push-to-reminders, disabled, últimas ejecuciones 2026-06-27 y 2026-08-24. Son los únicos publicadores de commands.mac_bridge.*, y están apagados. family.expense.process disabled (última 2026-07-14, timed_out). skirmshop.expense.process ENABLED (última 2026-10-03, timed_out): quién publicó ese disparo no está identificado; medirlo antes de retirar.
- Publicadores de attachment.TENANT.received: gmail, services/synapse-adapter-gmail/src/synapse_adapter_gmail/main.py:4660 (`_publish_attachment`, llamado en las líneas 3345 y 3399). Con la config de GitOps no emite hoy (expense_labels vacío; expense_all_attachments false en la cuenta de skirmshop), pero el código vive en un Deployment vivo. Messaging, adapter.py:1643, republica con messaging.dispatch_invoice_processing, y messaging-send NO consume esa acción. Telegram, ingest.py:414: código en services/synapse-adapter-telegram, sin Deployment vivo.
- El registro de gastos de synapse-tools-mcp escribe en la tabla synapse.expenses con INSERT directo (server.py:385). No depende del adapter de expenses.
- Libs: synapse_openclaw lo importan services conversation, expenses, llm, messaging, ops-explainer, telegram, voicelab y web-operator. synapse_prompts lo importan expenses, llm, messaging, voicelab y web-operator. De esos, siguen vivos messaging-send, ops-explainer y voicelab. La épica decía «hoy solo expenses, messaging y ops-explainer»: no es así.
- Contratos en libs/synapse-contracts/registry.yaml: expenses.process (línea 286), reminders.add, reminders.update y reminders.delete (1968, 1986, 2004), trellis.render_requested (2236), y la entrada mac_bridge (grep la localiza).
- Dos reglas que chocan: la cabecera de CONTRACTS.yaml dice que retirar = status removed; la épica dice deprecated. El CTO fija cuál aplica con la skill synapse-contracts antes del primer PR de contratos.
- Línea para architect: el ARCHITECTURE.md de k8s-synapse-pocharlies dice automated (correcto), pero el de la épica dice sync manual; y su digest de gmail (b12d605d) no es el vivo (01f2179c).

## Trabajo reciente (24 h)
- 2026-10-08 09:19Z, sesión analista (PLAN de INFRA-103, gateway 3/5): quita del gateway los providers gmail, telegram, telegram_customer y whatsapp. No toca los cinco programas. Antes de H5, confirmar que contact-sync no sale por el provider whatsapp.
- 2026-10-08 09:20Z, sesión analista (PLAN de INFRA-105, 5/5): quita pantallas y la tool product_creator de tools-mcp. Sin efecto sobre los cinco; el registro de gastos de tools-mcp no pasa por el adapter.
- 2026-10-08, gmail: cinco commits y dos pins de release (v2026.10.08.1 y v2026.10.08.3) en 24 h (INFRA-631, 643, 649, 664, 705). El adapter que contiene el publicador de attachment está vivo y en cambio. Riesgo para H1: que alguien active expense_all_attachments o expense_labels.
- Fuera de 24 h, vigente: comentario de Dani en INFRA-97 del 04-10. synapse-adapter-gmail NO se borra: lo rescata INFRA-473 (correo con secretarias). Por eso gmail queda fuera de todos los programas de esta épica. INFRA-473 no nombra expenses ni synapse-adapter-reminders; confirmarlo en H1 y H3.

## Preguntas al operador (criterio 2)
Las lleva el CTO por el VP antes de la primera PR. Con la evidencia de arriba, cada una tiene su recomendación.
- P1 (reminders): ¿sigue en uso el Mac bridge? Evidencia: los dos workflows mac_bridge están disabled y el adapter está en 1/1 sin nada que le llegue. R1: si no, retirar (H3).
- P2 (messaging-contact-sync): ¿se siguen sincronizando contactos de WhatsApp? Si sí, nombrar quién lo arranca y conservar. Evidencia: 0/0 y fuera de SYNAPSE_COMMAND_ACTIONS de messaging-send. R2: si no, retirar (H5).
- P3 (expenses): ¿se retira gastos o se le da entrada nueva? Si es entrada nueva, es épica propia y esta retirada no se ejecuta.
- Con recomendación técnica, solo confirmación del CTO: trellis (retirar, con su ScaledObject, H2) y messaging-media (retirar, H4).

## Criterios de aceptación
Cada criterio tiene una sola historia dueña, entre paréntesis. Los comandos se ejecutan tal cual sobre los repos; las salidas se pegan en la 50-entrega de cada historia.

- [ ] C1 (H6). Los cinco programas tienen decisión escrita: programa, decisión (RETIRADO o CONSERVADO), quién la tomó y el porqué en una línea. Comando: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py get --rol cto INFRA-104 nota-cto-decisiones-huerfanos.md $SCRATCH/dec.md && grep -cE "^- (expenses|trellis|reminders|messaging-media|messaging-contact-sync): (RETIRADO|CONSERVADO) — " $SCRATCH/dec.md`. Salida esperada: 5.
- [ ] C2 (H6). Las tres preguntas al operador están formuladas y respondidas, con la respuesta pegada, antes de la primera PR. Comando: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py get --rol cto INFRA-104 nota-cto-operador-preguntas.md $SCRATCH/q.md && grep -cE "^(P[1-3]|R[1-3]): " $SCRATCH/q.md`. Salida esperada: 6 (tres P y tres R), y la fecha de la última R anterior al primer `createdAt` de `gh pr list -R pocharlies-org/synapse --search INFRA-104 --state all --json createdAt`.
- [ ] C3 (H6). Por cada CONSERVADO: publicador vivo con fichero y línea, y contador publish subiendo. Si ninguno se conserva, la línea dice «ninguno CONSERVADO». Comandos: `git grep -n "attachment\.\|render_requested\|mac_bridge" origin/main -- services` y, en dos lecturas separadas, `curl -s -u USUARIO:CLAVE http://synapse-rmq.databases.svc:15672/api/queues/%2Fsynapse/COLA | jq '.message_stats.publish'`. Salida esperada: la segunda lectura mayor que la primera.
- [ ] C4a (H1). RETIRADO expenses limpio. Comandos: `git grep -n -E "adapter-expenses|expenses-tenants" origin/deploy/prod -- k8s` (vacío); `git cat-file -e origin/main:services/synapse-adapter-expenses` (código distinto de cero); `git ls-tree --name-only origin/main workflows/family/expense workflows/skirmshop/expense` (vacío). Diffs de los dos repos pegados.
- [ ] C4b (H2). RETIRADO trellis limpio, con su ScaledObject. Comandos: `git grep -n -E "adapter-trellis|scaledobject-vision" origin/deploy/prod -- k8s` (vacío); `git cat-file -e origin/main:services/synapse-adapter-trellis` (distinto de cero). Diffs pegados.
- [ ] C4c (H3). RETIRADO reminders limpio (si P1 responde no). Comandos: `git grep -n "adapter-reminders" origin/deploy/prod -- k8s` (vacío); `git cat-file -e origin/main:services/synapse-adapter-reminders` (distinto de cero); `git ls-tree --name-only origin/main workflows/family/tasks workflows/skirmshop/tasks | grep push-to-reminders` (vacío). Diffs pegados.
- [ ] C4d (H4). RETIRADO messaging-media del fabric, sin tocar el código de messaging. Comando: `git grep -n "messaging-media" origin/deploy/prod -- k8s` (vacío, con las líneas 62 y 283 fuera del kustomization y del pin del trío). Diff pegado.
- [ ] C4e (H5). RETIRADO messaging-contact-sync del fabric (si P2 responde no). Comando: `git grep -n "messaging-contact-sync" origin/deploy/prod -- k8s` (vacío, líneas 63 y 290 fuera). Diff pegado.
- [ ] C5 (H6). Tras el merge, la sincronización automática deja fuera los retirados y deja los conservados. Comando: `KUBECONFIG=~/.kube/config kubectl get deploy -n synapse` antes y después, pegado. Salida esperada: ninguna fila de expenses, trellis, reminders, messaging-media ni messaging-contact-sync; send, voicelab, shopify y gateway presentes. Comprobación del tronco: `kubectl get application synapse -n argocd -o jsonpath='{.status.sync.revision}'` igual al merge commit de deploy/prod.
- [ ] C6 (cada H1 a H5). Por cada retirado, las colas huérfanas quedan declaradas en la nota del CTO, y o bien se borran o bien llevan 24 h sin publicar. Comando: `curl -s -u USUARIO:CLAVE http://synapse-rmq.databases.svc:15672/api/queues/%2Fsynapse | jq -r '.[] | select(.name|test("expense|trellis|render_requested|reminder|mac_bridge|media|contact_sync")) | "\(.name) msgs=\(.messages) consumers=\(.consumers) publish=\(.message_stats.publish // 0)"'`. Salida esperada: cada cola de la lista tiene consumers=0 y, o no existe, o publish no sube en 24 h. Nunca se purgan dlq.*, synapse.unroutable ni adapter.ops_explainer.failures.
- [ ] C7 (H5). Si se retira contact-sync, INFRA-102 lo anota: sale del trío del pin messaging-drafts-release-metadata. Comando: `jira_get_issue INFRA-102 include=comments` y buscar «messaging-contact-sync» en un comentario posterior a la decisión. Salida esperada: presente. Si se conserva, la línea dice «no aplica» con P2 respondida.
- [ ] C8 (H6). Libs: se dice en una línea quién importa synapse-openclaw y synapse-prompts tras las decisiones, y se borra solo lo que ningún services/* importa. Comando: `git grep -rn -E "synapse_openclaw|synapse_prompts" origin/main -- services libs`. Salida esperada hoy: voicelab, messaging-send y ops-explainer siguen importándolas, así que no se borran.
- [ ] C9 (H6). CONTRACTS: las entradas cuya superficie desaparece pasan a estado de retirada (deprecated o removed, según la regla que fije el CTO), nunca se borran, y el commit lleva `Contract-Change:`. Comandos: `git grep -n -E "expenses.process|reminders\.(add|update|delete)|trellis.render_requested|mac_bridge" origin/main -- libs/synapse-contracts/registry.yaml` y `git log --format=%B origin/main --grep "Contract-Change:"`. Salida esperada: el número de entradas no baja y hay un trailer por contrato retirado. Si ninguno pierde superficie, la línea lo dice.
- [ ] C10 (H6). Documentación: por cada criterio, el documento que lo refleja o la línea de que no hacía falta. Documento principal: ARCHITECTURE.md de synapse (lista expenses, reminders y trellis como adaptadores). Comando: `grep -c "^- C[0-9]" 50-entrega.md` en cada historia; el total de líneas de las seis cubre C1 a C10.

## Restricciones
- Los roles no escriben en el clúster ni en ArgoCD. Solo lectura (`kubectl get`, `kubectl get application`). Nunca `kubectl delete` de una Application.
- Como la app sincroniza sola, el merge de GitOps es la acción. Antes de mergear, el CTO confirma en el objeto vivo qué réplicas caen (hoy reminders 1/1 y trellis 1/1; los demás ya están en 0/0).
- Orden: P1 a P3 antes de la primera PR (C2). La decisión sobre messaging-media y messaging-contact-sync va antes de que INFRA-102 (2/5) fije el trío de messaging, porque comparten el pin. Ese PR de pin va junto al de la 2/5 o después: lo fija el CTO.
- Enlaces Blocks de INFRA-104 en Jira: id 10550 (con INFRA-97) y 10555 (con INFRA-105). El orden es contradictorio: la nota del 06-10 pone INFRA-105 primero, y la descripción de INFRA-97 pone 5/5 al final. Lo decide el CTO antes del dispatch; estos enlaces no se tocan aquí.
- Si P3 pide entrada nueva de gastos, la retirada de expenses no se ejecuta: es épica propia.
- Fuera de alcance: gmail (INFRA-473), weight-resolver (Application propia), tablas Postgres huérfanas (otra épica, incluida synapse.expenses), skirmbooks, gestoria y document-intake.
- Nada de GPU: no toca gx10-ec3d ni nvidia-dgx.

## Diseño
Diseñador: no — es retirada de Deployments, código y contratos; no hay pantalla nueva ni cambiada (la admin UI es de INFRA-105).

## Historias previstas
- H1 expenses (dueño developer; subtarea GitOps devops). Decisión de P3. Si se retira: Deployment, configs, services/synapse-adapter-expenses, workflows expense.process de family y skirmshop, contrato expenses.process. Criterios C4a, C6.
- H2 trellis (dueño developer; subtarea GitOps devops). Retirada con su ScaledObject, services/synapse-adapter-trellis y contrato trellis.render_requested. Criterios C4b, C6.
- H3 reminders (dueño developer). Decisión de P1. Si se retira: Deployment, configs, services/synapse-adapter-reminders, workflows push-to-reminders de family y skirmshop, contratos reminders.* y mac_bridge. Criterios C4c, C6.
- H4 messaging-media (dueño devops). Sale del trío del pin en GitOps; el código es de INFRA-102. Criterios C4d, C6.
- H5 messaging-contact-sync (dueño devops). Decisión de P2. Sale del trío y se anota en INFRA-102. Criterios C4e, C6, C7.
- H6 decisiones, libs, CONTRACTS y documentos (dueño developer; el CTO firma las decisiones). Criterios C1, C2, C3, C5, C8, C9, C10. Cierra la épica.

## Tamaño
M. Seis historias, un CTO. Dos repos acoplados por el pin de imagen y por el trío de messaging. Espera de respuestas del operador (C2) y de INFRA-102 para H4 y H5. No se parte en hijas: cada retirada es un par de PR del mismo programa.

## Dificultad
Dificultad: media — retirar Deployments y el ScaledObject se deshace con revert del GitOps, y el borrado de services/ con revert del código. Lo no reversible es el contenido de una cola borrada: las colas se borran solo con cero consumidores y publish estable 24 h. Como la sincronización es automática con prune, el merge es la acción y no hay paso manual de respaldo.
