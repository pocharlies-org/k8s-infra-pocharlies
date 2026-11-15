Rol: pm · Fecha: 2026-10-03T08:33:30Z · Sesión: cc30b55d-313a-4642-9cb5-d07d94a60f3c · Estado: LISTO

## Objetivo

Unificar pocharlies y staticduo en un core común + overlays house-* y congelar el contrato servidor↔extensión↔AgentGateway versionado (M1B–M5). Plan firmado en INFRA-302 (D1-D3), ya troceado en tareas INFRA-384..391 (M1A y M2 Done; quedan M1B, M3, M4, M5, Infra). Sin solapes: SC-1417 es la puerta Playwright sin login; INFRA-413 es ventanas por sesión (el binding de M1B lo comparte: coordinar, no duplicar).

Repo: k8s-infra-pocharlies (espacio de trabajo; los repos canónicos son pocharlies-org/agent-jake-browser-mcp-server y pocharlies-org/agent-jake-browser-mcp-extension — transferidos el 02-10; la imagen vive en k8s-agentjake-browser-mcp-pocharlies)

## Criterios de aceptación

- [x] C1 (M1A, cumplido, verificado 2026-10-02): estructura de packages en ambos repos.
  Comando: `gh api repos/pocharlies-org/agent-jake-browser-mcp-server/contents/packages --jq '.[].name' | tr '\n' ' '` (y el mismo con `-extension`) → `core house-pocharlies house-staticduo ` (medido exacto hoy en ambos).
- [ ] C2 (M1B, INFRA-386): PROTOCOL_VERSION negociada en el handshake del WebSocket (127.0.0.1:18766); server y extensión declaran versión y una combinación incompatible se rechaza con error explícito, nunca degradación silenciosa.
  Comando: `gh api "repos/pocharlies-org/agent-jake-browser-mcp-server/git/trees/master?recursive=1" --jq '.tree[].path' | grep -icE protocol` → ≥1 (hoy 0; PRs de docs #3 abiertas en ambos repos, pendientes de Jordi) + test automatizado que arranca server+extensión incompatibles y aserta el rechazo.
- [ ] C3 (M2, INFRA-387; parte de código cumplida 02-10): core sin conocimiento de casas.
  Comando: `gh api repos/pocharlies-org/agent-jake-browser-mcp-server/contents/packages/core/src/tools/interaction.ts --jq .content | base64 -d | grep -cE 'house-pocharlies|house-staticduo|op-safe'` → 0 (medido hoy; igual en la extensión, packages/core/src/background/tools/handlers/interaction.ts, medido 0). Queda: 7 días de runs del updater (DGX-147) sin auto-fusión de conflictos — se verifica junto con M3.
- [ ] C4 (M3, INFRA-388): guarda del updater — conflicto en catch-up ⇒ NO auto-fusiona (abre ticket + aviso), y la imagen solo es desplegable desde el repo canónico (guarda en CI).
  Comando: `gh api "repos/pocharlies-org/agent-jake-browser-mcp-server/contents/.github/workflows" --jq '.[].name'` → contiene el workflow de guarda (hoy solo ci.yml y pr-review.yml); qa provoca un conflicto en rama: el updater termina en ticket + aviso, sin merge.
- [ ] C5 (M4, INFRA-389): un solo MCP de navegador registrado en las dos casas.
  Comando (x86): `/usr/bin/grep -rlE 'browser-harness|chrome-mac' ~/.config 2>/dev/null | wc -l` → 0 (medido hoy: 4; usar /usr/bin/grep, el grep del host es ugrep y da 0 falso con xargs).
- [ ] C6 (M5 + Infra, INFRA-390/391): contract test de versión en CI e imagen desplegada construida desde el canónico, fijada por digest en GitOps y verificada en el pod vivo tras autorización.
  Comandos: `gh run list --repo pocharlies-org/agent-jake-browser-mcp-server --limit 5` → run del contract test en success (hoy solo Product CI y PR review); `grep -m1 'image:' /home/dibanez/k8s/k8s-agentjake-browser-mcp-pocharlies/k8s/base/manifest.yaml` → digest del build canónico (hoy: tag fork-b89a98d@sha256:555cdf8e… del fork viejo); y el pod vivo coincide con ese digest.

## Restricciones

- Sin merge sin revisión de Jordi (staticduo); sin despliegue sin autorización explícita (rollout aparte).
- D1: capa de despliegue fuera del repo de producto (nas-docker de staticduo; k8s-agentjake-browser-mcp-pocharlies aquí).
- D2: core sin casas; un fix común entra al core por PR fusionada antes de usarse.
- Contrato: tools y handshake son superficie versionada; un cambio roto = entrada .vN+1 nueva con la vieja deprecated, nunca edición.
- Allowlist AgentGateway (#149) única puerta externa; /api/public/send nunca gana acciones destructivas ni de topics.
- El recorte CDP a la pestaña de trabajo es default del core (escape HARNESS_SCOPE=off).
- Coordinación con staticduo SOLO por el topic Telegram 374 (chat -1004434337797); sus merges y despliegues no se autorizan desde aquí.
- Las PRs de la extensión #4 (webauthn, abierta), #5 (close_tab, ya mergeada) y #6 (lifecycle new_tab, abierta) pertenecen a INFRA-374/INFRA-413, NO a esta épica.

## Trabajo reciente (24 h)

- 02-10 12:39Z: server PR#4 mergeada (fix new_tab, master 648717eb, gate qa+architect verde) y PR#5 mergeada (pr-review.yml al tronco, 123e7e58). INFRA-387 (M2) → Done 14:52Z.
- 02-10 ~14:51Z: repos canónicos TRANSFERIDOS a pocharlies-org (autorizado por Dani, comentado en INFRA-387).
- 02-10: M1B en curso por su cuenta: PRs de docs #3 abiertas en server y extensión con las resoluciones A-F de Codex; pendientes de revisión de Jordi. Server master sin código de handshake (grep protocol = 0).
- 02-10: staticduo anuncia que su siguiente turno es M1B (topic 374).
- 02-10 ~21:50Z (re-medido): extensión master avanzó a 013dc705 (20:07Z) con el merge de PR#5 close_tab (de INFRA-413, no de esta épica) y PR#7 pr-review.yml al tronco. PRs abiertas en extensión: #3 docs M1B (MERGEABLE), #4 webauthn y #6 lifecycle (estas dos de INFRA-374/INFRA-413).
- 02-10 ~21:50Z (re-medido): server master sigue en 648717eb, grep protocol = 0, única PR abierta #3 docs (MERGEABLE), pendiente de Jordi; workflows solo ci.yml y pr-review.yml; runs Product CI y PR review en success; interaction.ts grep = 0.
- 02-10 ~21:50Z: C5 sigue en 4 duplicidades en x86; C6 manifest sigue con fork-b89a98d@sha256:555cdf8e… (fork viejo). Jira: INFRA-386/388/389/390/391 To Do, INFRA-387 Done.
- Nota: sin sesión local viva trabajando esta épica.

## Diseño

Diseñador: no — no hay interfaz nueva ni cambiada: el sidepanel copiloto ya existe y esta épica no toca su diseño; el resto son repos, contrato y despliegue.

## Historias previstas

Las historias YA EXISTEN como tareas hijas (creadas 01-10 por orden de Dani); el CTO las orquesta en este orden, sin duplicados:

- INFRA-386 · M1B handshake PROTOCOL_VERSION + binding por sesión + puerto (dueño: developer, server + extensión, ambas casas; arranca por aquí — las PRs de docs #3 ya están abiertas)
- INFRA-388 · M3 guarda del updater DGX-147 + CI de compatibilidad (dueño: devops; con la observación de 7 días cierra también el resto de C3)
- INFRA-389 · M4 registro único de MCP en las dos casas (dueño: devops)
- INFRA-390 · M5 contract test de versión (dueño: developer)
- INFRA-391 · Infra: GitOps de la imagen + nas-docker (dueño: devops)
- (INFRA-384, INFRA-385 · M1A · Done 01-10; INFRA-387 · M2 · Done 02-10)
- qa valida cada tarea contra su criterio; el pm cierra la épica cuando las seis queden Done.

## Tamaño

L — 5 tareas abiertas, 3 repos propios + coordinación externa con staticduo, y la observación de 7 días del updater: más de una semana de reloj aunque el código por tarea sea acotado.

## Dificultad

Dificultad: alta — congela una interfaz que ambas casas ya consumen (handshake WebSocket + superficie de tools: criterio 1 de arquitectura) y M3/M4 tocan el updater diario compartido y el registro de MCP del que cuelgan los agentes (criterio 3): un fallo rompe el navegador de los agentes de las dos casas.
