Rol: pm · Fecha: 2026-10-08T09:20:00Z · Sesión: 7f43840d-ed64-4889-b148-fb6437e1a724 · Estado: ESPERA

## Objetivo

La ops UI, el MCP y la documentación de Synapse dejan de enseñar pantallas, tools y colas de programas que ya no existen, cuando SC-319 y las hijas 2/5, 3/5 y 4/5 hayan cerrado. Esta épica no borra programas: quita lo que los enseña y lo escribe en la documentación.

Repo: synapse

## Espera

Esta épica va la última de la familia y no se puede ejecutar hasta que cierren las hermanas. Medido el 08-10-2026 a las 09:19Z:

- INFRA-97 (To Do), INFRA-102 (To Do), INFRA-103 (Backlog), INFRA-104 (Backlog): abiertas.
- SC-319 (padre): no se puede medir con el MCP. La búsqueda por clave `key = SC-319` devuelve INFRA-97. Comprobarla a mano en https://e-dani.atlassian.net/browse/SC-319 antes de reabrir.

Comando de comprobación: `jira_search` con la JQL `key in (INFRA-97, INFRA-102, INFRA-103, INFRA-104) AND statusCategory != Done`. Salida que significa que ya llegó: total 0. Y SC-319 en Done o Cancelled en el navegador.

Cuando llegue: el PM vuelve a este spec, repite la medición (PASO 0 de la épica) y lo pasa a LISTO o lo re-planifica.

Revisar: 2026-10-15

## Criterios de aceptación

- [ ] C1. synapse-admin no tiene pantallas, rutas ni entradas de allowlist de brain, product-creator, translations ni conversation. Comando: `git -C ~/k8s/synapse grep -n -i -E 'product.creator|translations|conversation' origin/main -- services/synapse-admin/src`. Salida esperada: sin líneas. Medido hoy: el patrón amplio con brain da 18 ficheros y 266 líneas, porque brain aparece en sitios que no se quitan. El developer acota el patrón a las allowlists en su primera historia y lo pega en el 70-qa.
- [ ] C2. La ruta /#/handlers lista solo manifests que existen en la imagen. Comando: `curl -s https://ADMIN_HOST/api/v1/handlers` (la ruta es GET /handlers en services/synapse-admin/src/synapse_admin/routes/api_v1.py, línea 4193), comparado con `ls` de los manifests de la imagen. Salida esperada: la misma lista. ADMIN_HOST no sale del ingress: `kubectl get ingress -n synapse` no devuelve host hoy. La historia de admin lo fija.
- [ ] C3. Ninguna ruta de api_v1.py devuelve 500 por un import ausente. Comando: `cd ~/k8s/synapse/services/synapse-admin && uv run pytest tests/unit -q`, más el recorrido de rutas del router con su código de estado. Salida esperada: 0 failed y cero códigos 500 en el recorrido. El recorrido no existe hoy como test: lo añade la historia de admin.
- [ ] C4. product_creator_create_request no existe en el código de tools-mcp y list_capabilities no la devuelve. Comandos: `git -C ~/k8s/synapse grep -n 'product_creator_create_request' origin/main -- services/synapse-tools-mcp` y `mcp__synapse__list_capabilities`. Salida esperada: el grep sin líneas y la tool ausente de la lista, con la salida de antes y de después pegada. Hoy: el nombre no aparece en services/synapse-tools-mcp; aparece en workflows/skirmshop/product-creator/agent-create.v1.yaml (línea 2) y la tool sigue expuesta en el MCP vivo.
- [ ] C5. refresh_api_docs devuelve la lista nueva, sin endpoints de los servicios borrados. Comando: `mcp__synapse__refresh_api_docs` y luego `mcp__synapse__list_capabilities`. Salida esperada: ningún endpoint de los servicios retirados, pegada. La lista de servicios retirados sale de las evidencias de SC-319 y las hijas.
- [ ] C6. WORKER-MATRIX.md coincide con los Deployments del día del cierre. Comandos: `kubectl get deploy -n synapse -o name | sed 's#deployment.apps/##' | sort` y `git -C ~/k8s/k8s-synapse-pocharlies show origin/deploy/prod:k8s/configs/WORKER-MATRIX.md | grep -oE 'synapse-[a-z0-9-]+' | sort -u`. Salida esperada: las dos listas idénticas, una al lado de la otra. Hoy no coinciden: la matriz nombra servicios que kubectl no lista (synapse-adapter-brain, synapse-adapter-conversation, entre otros) y hay 21 Deployments vivos.
- [ ] C7. docs/29-pending-roadmap.md tiene la sección de cerrado con la fecha y las claves de la limpieza. Comando: `git -C ~/k8s/synapse show origin/main:docs/29-pending-roadmap.md | grep -n -i -E 'cerrad|INFRA-97|INFRA-10[2-5]|SC-319'`. Salida esperada: una sección de cerrado con fecha y las cinco claves (SC-319, INFRA-97, INFRA-102, INFRA-103, INFRA-104 e INFRA-105).
- [ ] C8. CLAUDE.md del repo ya no cita synapse-adapter-gmail como patrón canónico y cita un servicio que existe. Comandos: `git -C ~/k8s/synapse show origin/main:CLAUDE.md | grep -n 'synapse-adapter-gmail'` (hoy, línea 166) y `kubectl get deploy -n synapse SERVICIO_CITADO`. Salida esperada: sin cita canónica a gmail y un Deployment vivo para el servicio que la sustituya. Premisa a corregir: la épica dice que synapse-adapter-gmail ya no existe, y no es cierto hoy (ver Análisis). Si el CTO decide que gmail sigue siendo el patrón, este criterio se reescribe como decisión nueva, no se borra.
- [ ] C9. docs/08-event-fabric.md no lista ninguna cola retirada. Comando: `git -C ~/k8s/synapse grep -n -E 'LISTA_DE_COLAS_RETIRADAS' origin/main -- docs`. Salida esperada: sin coincidencias. BLOQUEADO EN EL PLAN: la lista de colas retiradas aún no existe; sale de las evidencias de las hijas cuando cierren. Hasta entonces el comando no es ejecutable.
- [ ] C10. CONTRACTS.yaml es coherente: ninguna entrada borrada y las que pierden superficie quedan en deprecated. Comando: `git -C ~/k8s/synapse diff origin/main...HEAD -- CONTRACTS.yaml | grep -E '^-[[:space:]]*-?[[:space:]]*id:'`. Salida esperada: sin líneas. Además, lista de entradas afectadas con su épica de origen, en el 70-qa.
- [ ] C11. Evidencia de cierre en un comentario de SC-319: PRs de los dos repos, digest final pineado y visible en los Deployments, kubectl get deploy y kubectl get endpoints finales, conteo de colas del vhost /synapse antes y después, pendientes.sh limpio. Comandos: `kubectl get deploy -n synapse` y `kubectl get endpoints -n synapse` (hoy: 21 Deployments y 18 Endpoints). BLOQUEADO EN EL PLAN: no hay comando documentado para el conteo de colas, y pendientes.sh no existe en origin/main de synapse ni en ~/k8s/*/. Hay que nombrar su ruta y el comando del conteo antes de cerrar.

## Restricciones

- Desde los roles: nada de kubectl apply, patch, delete ni scale, y nada de argocd app sync. El sync de WORKER-MATRIX lo pide el CTO al operador con el comando exacto, y se verifica en el objeto vivo.
- Siempre PR: synapse contra main, k8s-synapse-pocharlies contra deploy/prod. Nunca push directo, nunca --force.
- Nada de skirmbooks, gestoria ni document-intake.
- La documentación se escribe contra la medición del día del cierre, no contra la lista del 07-09.
- Un contrato no se borra: si pierde superficie pasa a deprecated, y un breaking change es una entrada .vN+1 (skill synapse-contracts). Los commits que tocan CONTRACTS.yaml llevan el trailer Contract-Change.
- Documentación que cierra con el trabajo: cada criterio cumplido nombra su documento, o dice en una línea que no hizo falta.

## Trabajo reciente (24 h)

- 08-10 08:36Z, synapse main 400c9d22 (PR #240) y 09:42Z, GitOps deploy/prod f7f54e4: el adapter gmail sigue vivo y se despliega (imagen v2026.10.08.3). Afecta a C8: la premisa de la épica no se cumple.
- 07-10 16:24Z a 08-10 08:36Z: 7 commits de synapse main tocan services/synapse-admin, services/synapse-tools-mcp, CONTRACTS.yaml, docs/ o CLAUDE.md. Todos son del adapter gmail (INFRA-631, 634, 643, 649, 664, 705) y ninguno de la limpieza. Afecta a C8 y C10: esos ficheros siguen cambiando, hay que volver a medir al cerrar.
- GitOps deploy/prod, últimas 24 h: 14 commits, ninguno toca WORKER-MATRIX.md.
- Sesiones vivas (claude-tmux list): ninguna. Transcripciones de las últimas 24 h con las palabras clave: ninguna.
- Brain claude-personal, fuera de 24 h pero relevante: 06-10 (INFRA-105 es la última de la familia; el spec estaba en BORRADOR), 04-10 (lectura de estado de las épicas de la familia), 03-10 (re-plan de INFRA-97 medido con synapse main en 34150347; hoy main está en 400c9d22, así que ese análisis está desfasado).

## Análisis (medido 08-10-2026, antes de dejar la épica en ESPERA)

- Familia: INFRA-97 To Do (spec LISTO, plan-dividida y plan-revisado), INFRA-102 To Do, INFRA-103 Backlog, INFRA-104 Backlog. SC-319 no medible con el MCP.
- Enlaces Blocks en Jira: INFRA-105 figura como bloqueador de INFRA-97, INFRA-102, INFRA-103 e INFRA-104. El encargo dice lo contrario (esta va la última). No creo ni borro enlaces en fase PLAN. DECISIÓN PARA EL CTO O EL SUPERVISOR: invertirlos.
- C8: premisa falsa. synapse-adapter-gmail tiene Deployment 1/1 y lo despliega GitOps hoy. Decisión para el CTO: si gmail es el patrón canónico, el criterio cambia.
- C1: el patrón amplio da 18 ficheros y 266 líneas en synapse-admin. Sin acotar, el criterio no se puede comprobar.
- C4: la tool se genera desde workflows/skirmshop/product-creator/agent-create.v1.yaml. Quitarla obliga a retirar ese workflow, que es una ruta /synapse consumida por otros: contrato, pasa a deprecated.
- agent-m2m-mcp: no tiene carpeta propia en services/ de origin/main. Hay Deployment vivo (synapse-agent-m2m-mcp). El developer localiza su fuente antes de tocarla.
- C6: la matriz no coincide con el clúster hoy (ver C6).
- C11: pendientes.sh no existe en origin/main de synapse ni en ~/k8s/*/. El conteo de colas no tiene comando documentado.
- C2: el ingress del namespace synapse no devuelve host.
- Brain: no encontré un ANALISIS INFRA-105 previo. Las conclusiones de 06-10 y 03-10 coinciden con lo medido arriba.

## Diseño

Diseñador: no — no se diseña ninguna pantalla nueva; solo se quitan pantallas existentes y se corrige texto de documentación.

## Historias previstas

- H1 · synapse-admin: quitar pantallas, rutas y allowlists, y el recorrido de rutas sin 500 · dueño: developer · criterios C1, C2, C3
- H2 · tools MCP: quitar product_creator_create_request y retirar su workflow como contrato deprecated · dueño: developer · criterios C4, C5
- H3 · GitOps: WORKER-MATRIX.md alineado con el clúster del día del cierre · dueño: devops · criterio C6
- H4 · docs: docs/29 (sección de cerrado), CLAUDE.md, docs/08 · dueño: developer · criterios C7, C8, C9
- H5 · CONTRACTS.yaml: pasada de coherencia · dueño: developer · criterio C10
- H6 · cierre: evidencia de C11 en comentario de SC-319 · dueño: qa (evidencia) y devops (digest, Deployments, endpoints y colas)
- Sync: tras el merge de H3, el CTO pide al operador el comando exacto de argocd sync y se verifica en el objeto vivo.

## Tamaño

M. Dos repos (synapse y k8s-synapse-pocharlies), unos 18 ficheros de admin según el patrón amplio, un workflow y un contrato de ruta, documentación y la evidencia de cierre. No borra código.

## Dificultad

Dificultad: media — trabajar sobre lo que ya existe: quitar referencias de productos vivos en dos repos y en GitOps, con un contrato de ruta que pasa a deprecated. No borra programas y se deshace con revert.
