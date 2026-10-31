Rol: pm · Fecha: 2026-10-04T21:42:00Z · Sesión: 7d0accb0-9b10-4f0d-8ebf-eb4a4fe9e696 · Estado: LISTO

## Objetivo
Aligerar la cola larga de imágenes propias de INFRA-474: primero la infra MCP compartida (`mcp-stdio-pool-bridge`, 164 MB, 14 Deployments, y `mcp-stdio-bridge`, 174 MB, 3 Deployments), después los `*-mcp` sueltos y las apps sueltas, con bases comunes por digest, multi-stage, sin cachés y dependencias antes que código; antes/después medido con crane y verificado en producción.
`Repo:` es el ancla de infra MCP compartida (el manifiesto de la cola y el seguimiento viven aquí); los Dockerfiles de las demás imágenes están en ~25 repos propios y se tocan por historias, cada una con su PR contra el tronco de ESE repo.

Repo: k8s-infra-pocharlies

## Criterios de aceptación
Medido hoy (04-10-2026) con `crane` y `kubectl`, no asumido.

- [ ] `mcp-stdio-pool-bridge` (tag viva `v0.1.9@sha256:fa0dc8989b91911ca1507e99a286868fcfe677e0dedec30416043aa1b447ffa4`, 164065072 B comprimido amd64, 11 capas) y `mcp-stdio-bridge` (tag viva `v0.2.0@sha256:bf8133d638cea9b170d9ff0faf6666f6e83bffeee706d77d8674b48535fef41a`, 173840000 B, 8 capas) bajan de tamaño, sin cachés en la capa final.
  - Comando: `crane manifest --platform linux/amd64 harbor.e-dani.com/homelab/mcp-stdio-pool-bridge@<digest-nuevo> | jq '[.layers[].size]|add'` (y el mismo para `mcp-stdio-bridge`); `crane export harbor.e-dani.com/homelab/mcp-stdio-pool-bridge@<digest-nuevo> - | tar -tf - | grep -E '(^|/)(\.cache|__pycache__|node_modules/\.cache|\.npm)/'`.
  - Salida esperada: pool-bridge < 164065072 y bridge < 173840000; el `grep` no imprime nada.

- [ ] Los 14 Deployments que usan `mcp-stdio-pool-bridge` (analytics-mcp, company-metrics-mcp, cto-office-mcp, gsc-mcp, hermes-gateway, merchant-mcp, onepassword-mcp, shopify-mcp, skirmshop-plugins-mcp, skirmshop-plugins-mcp-admin, dgx-control-mcp, studio-mcp, tts-mcp, workspace-mcp) y los 3 de `mcp-stdio-bridge` (sauvage-admin-mcp, grok-mcp, weight-mcp) corren la imagen nueva y los MCP responden (no solo pod ready).
  - Comando: `kubectl get deploy -A -o json | jq -r '.items[]|.metadata.name as $n|.spec.template.spec.containers[]|select(.image|test("mcp-stdio(-pool)?-bridge"))|"\($n) \(.image)"'` y, por cada MCP, `tools/list` por AgentGateway/Synapse (`mcp__synapse__health` o la ruta MCP propia) → respuesta con herramientas.
  - Salida esperada: todos con el digest nuevo; todos devuelven su lista de herramientas. `hermes-gateway` solo cambia por su pipeline (ver Restricciones).

- [ ] Cada `*-mcp` suelto propio (brain-mcp v0.1.12 171 MB, picqer-mcp 79 MB, shopify-admin-mcp 75 MB, stt-mcp 75 MB, tesla-control-mcp 73 MB, offers-mcp 72 MB, dgx-synapse-mcp 70 MB, agent-jake-browser-mcp-server 74 MB, teslamate-mcp 60 MB) y cada app suelta propia confirmada (mayores: hermes-agent 973 MB, libreplay-web 849 MB, bambulab-openclaw 581 MB, uriel-poster 553 MB, tomorrowland-app 183 MB, cv-manu 89 MB) pasa las reglas de higiene y baja de tamaño (medidas de hoy sobre la tag más alta en Harbor; la baseline exacta es la tag VIVA, se mide al empezar cada historia).
  - Comando: por imagen `crane manifest --platform linux/{arch} {img@antes} | jq '[.layers[].size]|add'` vs `{img@después}`; `docker run --rm -i hadolint/hadolint < Dockerfile`; `test -f .dockerignore`.
  - Salida esperada: comprimido después < antes en cada imagen tocada; hadolint exit 0; `.dockerignore` presente. Una imagen sin margen real (p. ej. las ya pequeñas de ~21-33 MB: blog, web-edani, codex-arcade, serpentetool-frontend, galan/uriel-site, cv-dani) se documenta "sin cambio: ya mínima" con su medida, no se fuerza.

- [ ] Bases comunes de 536 adoptadas donde haya 3+ consumidores de la misma pila, fijadas por `@sha256:`.
  - Comando: `grep -n '^FROM' <Dockerfile>` en cada Dockerfile tocado de una pila con 3+ consumidores.
  - Salida esperada: la base común de 536 por digest. Si 536 aún no la publicó, la historia queda sin ese criterio y se dice; no se inventa una base propia.

- [ ] Sin regresión en producción: cada imagen nueva pasa su CI y healthcheck y queda verificada en vivo tras su pin.
  - Comando: `kubectl rollout status deploy/<name> -n <ns> --timeout=180s`; `kubectl get pods -n <ns> -l <selector> -o jsonpath='{.items[*].status.containerStatuses[*].ready}'`; comprobación de efecto (MCP `tools/list`, HTTP 200 de la app).
  - Salida esperada: "successfully rolled out", `true` en todos, y el MCP/app responde. Evidencia sobre el objeto vivo, no sobre ArgoCD en verde.

- [ ] Guard de CI de 536 conectado a los workflows de build de las imágenes tocadas.
  - Comando: `grep -rEl 'image-guard|hadolint' .github/workflows/` en cada repo tocado.
  - Salida esperada: el workflow de build invoca el reusable de 536 (lint + tope de tamaño). Depende de que 536 entregue el reusable.

## Restricciones
- Bloqueada por INFRA-536 (Plataforma: inventario, bases comunes por digest, guard reusable; hoy en To Do, con `Blocks` hacia 537-541). Solape: 536 produce inventario/bases/guard; esta épica los ADOPTA y no los construye. INFRA-537 (piloto jarvis, To Do) no ha entregado nada aplicable todavía (su spec solo cubre jarvis-backend).
- Hermanas, sin duplicar: 538 (dgx-infra), 539 (Skirmshop), 540 (Synapse/socialmedia). Si una imagen de esta lista cae en su dominio (p. ej. los `skirmshop-*`, synapse, whatsappmcp, comfyui/omnivoice), es de ELLAS.
- Clasificación propia vs espejo: pendiente de 536. Marcadas «pendiente de clasificación de 536»: `codex-arcade` (26 MB, tag `20260728-fixes`) y `aurora-server`/`aurora-frontend` (no existen como repo `homelab/*` en Harbor; pueden vivir en ghcr o ser espejos como aurora-kubectl-agent). No se trabajan hasta que 536 las confirme propias.
- `mcp-stdio-pool-bridge` es infraestructura MCP compartida: una regresión tumba 14 MCP a la vez, y uno es `hermes-gateway`. Despliegue por etapas (un MCP de bajo riesgo primero), verificando `tools/list`, no solo pod ready. Reversible con el pin anterior (`v0.1.9@sha256:fa0dc898…`, `v0.2.0@sha256:bf8133d6…`).
- `hermes-gateway` y `hermes-agent` (fork, 973 MB): se despliegan SOLO con `hermes-despliegue.yml` (runner `x86-hermes`, tronco `deploy/prod`). Nunca `kubectl rollout restart deploy/hermes-gateway`, `argocd app sync hermes` ni apply a mano. El pin del pool-bridge en Hermes va por esa pipeline y es la última etapa.
- `weight-mcp` y `sauvage-admin-mcp` usan `mcp-stdio-bridge:v0.2.0` sin digest: el pin por digest es parte de la historia.
- GitOps: PR contra el tronco que lee ArgoCD en cada repo (comprobar `.spec.source.targetRevision`); el pin va en el repo de manifiestos. Nunca push directo.
- Fuera: imágenes de terceros (redis, onepassword-connect, vllm, searxng, clamav, minio, nats, agentgateway) y buildkit degradado (INFRA-475). Compute: nada de esto crea cargas en los Sparks; si una imagen es arm64, no construir en `gx10-ec3d`/`nvidia-dgx` sin leer `gpu-arbiter-state`.

## Trabajo reciente (24 h)
- 04-10-2026, sesión 31bce0d2 (pm, INFRA-474): dividió INFRA-474 en 536-541 con `Blocks` 536 → 537-541; midió `mcp-stdio-pool-bridge` en 164 MB.
- 04-10-2026, sesiones pm paralelas eee84ade (INFRA-539) y esta (7d0accb0): planes hermanos en curso, sin cambios de código.
- 04-10-2026, INFRA-475 (sre-devops): buildkit degradado, ralentiza builds, fuera de alcance.
- Sin sesión viva sobre tamaño de imágenes (`claude-tmux list`: solo sesiones Hermes cb/edani-key).

## Diseño
Diseñador: no — solo Dockerfiles y pines; ninguna UI nueva o cambiada.

## Historias previstas
Orden: la ancla primero, luego en paralelo, el guard al final.
1. Ancla: `mcp-stdio-pool-bridge` + `mcp-stdio-bridge` — multi-stage, sin caché, `.dockerignore`, base común, before/after, pin por digest en los 17 Deployments (Hermes al final, por su pipeline) (dueño: developer; pines y despliegue: devops).
2. `*-mcp` sueltos: brain-mcp, picqer-mcp, shopify-admin-mcp, stt-mcp, tesla-control-mcp, offers-mcp, dgx-synapse-mcp, agent-jake-browser-mcp-server, teslamate-mcp (dueño: developer).
3. Apps sueltas grandes: libreplay-web, bambulab-openclaw, uriel-poster, tomorrowland-app, cv-manu, opencode-node-ops, ha-dashboard (dueño: developer).
4. `hermes-agent` (fork, 973 MB) por su pipeline propia (dueño: devops).
5. Apps ya pequeñas (blog, web-edani, serpentetool-*, galan/uriel-*, cv-dani/oracle) + clasificadas por 536 (codex-arcade, aurora): medir y limpiar solo lo que tenga margen (dueño: developer).
6. Guard de 536 conectado a los workflows de build de todas las anteriores (dueño: devops).
7. Verificación en producción de cada tanda: rollout + `tools/list`/HTTP (dueño: qa).

## Tamaño
L — ~25 repos y ~30 imágenes, pero el valor se concentra en la historia 1 (17 Deployments) y en 4-5 imágenes de cientos de MB; 7 historias secuenciadas por un CTO en ~1-2 semanas con la ancla primero. No se divide: los repos van por historia, no por épica, y partirla duplicaría la coordinación con 536.

## Dificultad
Dificultad: media — alto apalancamiento (la ancla toca 17 Deployments MCP, uno es Hermes), pero es reversible por pin anterior y no toca datos ni la infraestructura delicada del clúster.
