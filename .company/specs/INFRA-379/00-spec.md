Rol: pm · Fecha: 2026-10-02T00:04:30Z · Sesión: d8097142-9dc2-4d25-846d-711f525b7cec · Estado: DIVIDIDA

# INFRA-379 — Gestor de fotos con IA: MCP + app iOS

## Objetivo
Un núcleo compartido (ingesta de la librería de Fotos, índice de embeddings, operaciones ver/buscar/duplicados/ordenar/borrar con gate humano) y dos fachadas sobre él: un MCP para agentes y una app iOS companion. El trabajo vive en las hijas INFRA-402 (núcleo + MCP) e INFRA-403 (app iOS); esta épica no lo duplica.

Repo: k8s-photos-mcp-pocharlies (nuevo, lo crea INFRA-402)

## Criterios de aceptación
Se verifican con lo que entreguen las hijas (detalle de comandos en sus specs).
- [ ] Búsqueda en lenguaje natural en menos de 5 s. Comando: bench de búsqueda de INFRA-402 (`python tests/bench_search.py --queries 50`) sobre la librería completa. Esperado: `p95_s < 5.0`, exit 0.
- [ ] Gate humano en borrado. Comando: llamar a la tool `photos_delete` por el MCP y comprobar que la foto sigue en la librería. Esperado: respuesta `{"status":"pending-confirmation"}` y 0 fotos borradas hasta una confirmación explícita (desde la app iOS o con token de confirmación).
- [ ] Privacidad sin egreso externo. Comando: `kubectl get networkpolicy -n photos` y prueba de egreso a internet desde el pod. Esperado: política default-deny de egreso; solo DNS, Qdrant y bge-m3 permitidos; la prueba de egreso externo falla (timeout).
- [ ] MCP completo. Comando: `tools/list` contra la ruta del agentgateway. Esperado: tools de ver, buscar, duplicados y ordenar (más borrar con gate) presentes.

## Restricciones
- Borrar fotos exige gate humano: nunca se borra sin confirmación explícita; el borrado no se deshace con un revert.
- Nada sale del clúster sin OK de Dani (ni fotos, ni miniaturas, ni embeddings a servicios externos).
- Qdrant: colección propia nueva, no la del brain.

## Trabajo reciente (24 h)
- Cluster k3s: nodos gx10-ec3d, nvidia-dgx, ks5-cp-1..3, sauvage, ubuntu. El Mac NO es nodo del clúster: la librería de Fotos vive en el Mac/iPhone de Dani.
- Existe el runner self-hosted `nexus-mac`, que ya compila e instala apps con devicectl (pipeline de llm-status-ios, 30-09).
- La ingesta de Fotos ha de salir del Mac (Photos.framework / osxphotos export por el runner) o de CloudKit: el spike de la primera historia de INFRA-402 decide cuál.
- Reutilizable: Qdrant en `aiops-qdrant.aiops:6333` (colección propia nueva, NO la del brain) y embeddings de texto bge-m3 en ns `llm`.
- Decenas de MCPs ya desplegados; repo mínimo de ejemplo: `k8s-stt-mcp-pocharlies` (Dockerfile, server.py, k8s/, tests/).
- Registro de MCPs en `k8s-agentgateway-pocharlies` (`k8s/base/agentgateway-config.yaml`, `MCP-TOPOLOGY.md`).
- Nada construido aún: no existe repo photos ni despliegue. La épica se creó 2026-10-01 09:47 desde Telegram (Hermes agentic-link).
- Últimas 24 h: sin trabajo que afecte salvo la creación de la épica y su paso a Backlog por el supervisor; ninguna sesión viva en esto.

## Diseño
Diseñador: sí — app iOS companion con galería, búsqueda y revisión de duplicados; mockup ya lanzado
- fotos-ios: galería, búsqueda NL, revisión de duplicados con confirmación y propuestas de orden · job 20261001-234116-fotos-ios

El mockup se adjunta solo a INFRA-379.

## Historias previstas
INFRA-402 (núcleo + MCP, repo k8s-photos-mcp-pocharlies):
- Spike de ingesta: Mac (Photos.framework/osxphotos por nexus-mac) vs CloudKit, con decisión escrita (dueño: cto)
- Repo y servicio base del MCP desplegado como ArgoCD app, siguiendo k8s-stt-mcp (dueño: devops)
- Ingesta + embeddings de imagen e índice en colección Qdrant propia (dueño: developer)
- Tools ver/buscar/duplicados/ordenar y bench p95 < 5 s (dueño: developer)
- Borrado con gate humano (pending-confirmation) (dueño: developer)
- NetworkPolicy default-deny de egreso y registro en agentgateway (dueño: devops)
- QA end to end (dueño: qa)

INFRA-403 (app iOS, repo photos-ios):
- Repo y pipeline nexus-mac con devicectl (dueño: devops)
- Galería y búsqueda NL (dueño: developer)
- Revisión de duplicados con confirmación y propuestas de orden (dueño: developer)
- Revisión UX antes de QA (dueño: designer)
- QA en dispositivo (dueño: qa)

## Dificultad
Dificultad: alta — servicio nuevo que no existe (arquitectura) y borrado de fotos personales que no se deshace con un revert (datos)

## Tamaño
L: dos repos nuevos, ML de embeddings e iOS.

## Hijas
1. INFRA-402 — núcleo Fotos + MCP (primero).
2. INFRA-403 — app iOS companion (después). Enlace Blocks 402 -> 403 ya creado.
