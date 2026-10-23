Rol: pm · Fecha: 2026-10-02T00:04:30Z · Sesión: d8097142-9dc2-4d25-846d-711f525b7cec · Estado: LISTO

# INFRA-402 — Núcleo Fotos + MCP

## Objetivo
Un servicio nuevo que ingiere la librería de Fotos de Dani, la indexa con embeddings y la expone por un MCP con ver, buscar, duplicados y ordenar, y con borrado bajo gate humano. Corre en un namespace propio sin egreso externo y queda registrado en el agentgateway como los demás MCPs.

Repo: k8s-photos-mcp-pocharlies (nuevo)

## Criterios de aceptación
- [ ] MCP con las 4 operaciones. Comando: `tools/list` vía agentgateway (`curl -s -X POST $GW/photos/mcp -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'`). Esperado: tools de ver, buscar, duplicados y ordenar (más `photos_delete`).
- [ ] Búsqueda NL rápida. Comando: `python tests/bench_search.py --queries 50` sobre la librería completa. Esperado: `p95_s < 5.0`, exit 0.
- [ ] Gate de borrado. Comando: llamar `photos_delete` sobre una foto de prueba y luego listarla. Esperado: `status: pending-confirmation`, la foto sigue ahí; solo tras confirmación explícita se borra.
- [ ] Sin egreso. Comando: `kubectl get networkpolicy -n photos`. Esperado: política de egreso default-deny con solo DNS, Qdrant y bge-m3 permitidos; `kubectl exec` con curl a internet falla.
- [ ] Registro en agentgateway. Comando: grep de la ruta photos en `k8s/base/agentgateway-config.yaml` y entrada en `MCP-TOPOLOGY.md` de k8s-agentgateway-pocharlies. Esperado: ruta presente y mergeada; el `tools/list` anterior responde por ella.
- [ ] Spike resuelto. Esperado: nota del CTO adjunta con la decisión Mac vs CloudKit antes de las historias de ingesta.

## Restricciones
- Gate humano para borrar; sin confirmación explícita no se borra nada.
- Nada sale del clúster sin OK de Dani.
- Qdrant `aiops-qdrant.aiops:6333`: colección propia nueva, no tocar la del brain.
- Pipeline y despliegue como ArgoCD app; runners según la skill ci-runners-arc, salvo la ingesta que sale del Mac.
- Contrato del MCP (nombres de tools): una vez publicado no se renombra; breaking = tool nueva.

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
Diseñador: no — servicio MCP sin interfaz propia

## Historias previstas
- Spike de ingesta Mac vs CloudKit (dueño: cto)
- Repo, Dockerfile, server.py, k8s/ y ArgoCD app (dueño: devops)
- Ingesta de la librería e índice de embeddings en Qdrant (dueño: developer)
- Tools ver/buscar/duplicados/ordenar + bench p95 (dueño: developer)
- Borrado con gate humano (dueño: developer)
- NetworkPolicy de egreso default-deny + registro en agentgateway (dueño: devops)
- QA end to end sobre producción (dueño: qa)

## Dificultad
Dificultad: alta — servicio nuevo + borrado irreversible de datos personales

## Tamaño
M/L
