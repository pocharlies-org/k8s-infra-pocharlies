Rol: pm · Fecha: 2026-10-02T00:04:30Z · Sesión: d8097142-9dc2-4d25-846d-711f525b7cec · Estado: LISTO

# INFRA-403 — App iOS companion

## Objetivo
Una app iOS nueva que muestra la galería, busca en lenguaje natural y permite revisar duplicados y propuestas de orden contra la API definida por INFRA-402. Cualquier borrado pasa por una confirmación explícita en la app.

Repo: photos-ios (nuevo)

## Criterios de aceptación
- [ ] La app compila e instala. Comando: workflow de CI en nexus-mac con devicectl. Esperado: run en verde y app instalada en el iPhone (`devicectl device info apps` la lista).
- [ ] Búsqueda NL. Comando: buscar una frase en la app contra el MCP de producción. Esperado: resultados en menos de 5 s, comprobado en el test UI.
- [ ] Duplicados con confirmación. Comando: test UI que marca un duplicado para borrar. Esperado: la app muestra pantalla de confirmación y no llama a confirmar hasta pulsarla; sin pulsar, la foto sigue en la librería.
- [ ] Propuestas de orden visibles. Esperado: pantalla con las propuestas de `photos_sort` y acción de aceptar/rechazar.
- [ ] Revisión UX hecha. Esperado: `nota-designer-ux.md` adjunta a la historia antes de QA.

## Restricciones
- Depende de INFRA-402 (Blocks); no empieza antes de que su API esté desplegada.
- Un solo repo, sin tocar infra compartida.
- Nada sale del clúster sin OK de Dani; la app solo habla con el gateway propio.
- El borrado siempre requiere confirmación explícita del usuario.

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
Diseñador: sí — app iOS nueva; mockup diseno-fotos-ios-mockup.dc.html adjunto en INFRA-379
- Historia de revisión UX (dueño: designer) antes de QA.

## Historias previstas
- Repo photos-ios y pipeline nexus-mac con devicectl (dueño: devops)
- Galería y búsqueda NL (dueño: developer)
- Revisión de duplicados con confirmación y propuestas de orden (dueño: developer)
- Revisión UX (dueño: designer)
- QA en dispositivo (dueño: qa)

## Dificultad
Dificultad: media — app nueva sobre API ya definida en un solo repo, sin tocar infra compartida

## Tamaño
M
