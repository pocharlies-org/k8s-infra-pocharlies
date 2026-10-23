Rol: pm · Fecha: 2026-10-04 · Sesión: 31bce0d2-7f1f-492d-8c17-6f2ee2b613f3 · Estado: LISTO

## Objetivo
Aligerar la cola larga de imágenes propias: la infraestructura MCP compartida (mcp-stdio-pool-bridge y mcp-stdio-bridge, de alto apalancamiento porque las consumen ~15-20 Deployments MCP) y las apps sueltas restantes. Aplicar bases comunes, multi-stage, sin cachés en la capa final, .dockerignore y dependencias antes que código; antes/después medido y verificado en producción.

Repo: mcp-stdio-pool-bridge / mcp-stdio-bridge (ancla, infra MCP compartida) y los repos de las apps sueltas — la lista definitiva la fija el inventario de INFRA-536 (algunas pueden ser espejos de terceros y quedar fuera).

Imágenes del dominio: mcp-stdio-pool-bridge (164 MB amd64, usada por analytics/company-metrics/cto-office/gsc/merchant/onepassword/shopify/studio/tts/workspace-mcp y hermes), mcp-stdio-bridge (grok/weight/sauvage-admin-mcp), brain-mcp, dgx-synapse-mcp, stt-mcp, offers-mcp, picqer-mcp, shopify-admin-mcp, tesla-control-mcp, teslamate-mcp, hermes-agent, blog, cv-dani/cv-manu/cv-oracle, ha-dashboard, libreplay-web, tomorrowland-app, galan-proposal-chat/galan-proposal-site, uriel-poster/uriel-proposal-chat/uriel-proposal-site, web-edani, serpentetool-backend/serpentetool-frontend, opencode-node-ops, agent-jake-browser-mcp-server, bambulab-openclaw, aurora-server/aurora-frontend, codex-arcade.

## Criterios de aceptación
- [ ] mcp-stdio-pool-bridge y mcp-stdio-bridge (alto apalancamiento): sin caché en la capa final, multi-stage donde aplique, .dockerignore, dependencias antes que código; antes/después con crane manifest, baja.
  - Comando: antes `crane manifest --platform linux/amd64 harbor.e-dani.com/homelab/mcp-stdio-pool-bridge:v0.1.9 | jq '[.layers[].size]|add'` → 164065072; después el mismo comando con el digest nuevo → menor. `crane export {img@nuevo} - | tar -tf - | grep -E '(^|/)(\.cache|__pycache__|node_modules/\.cache|\.npm)/'` → vacío.
  - Salida esperada: comprimido después < 164065072 y ninguna caché en la capa final; el cambio se refleja en los ~15-20 Deployments que la consumen.

- [ ] Cada app propia del dominio: mismas reglas de higiene; antes/después medido, baja en todas las tocadas; las que estén entre las 10 propias más grandes entran en la tabla de la épica.
  - Comando: por imagen, `crane manifest [--platform linux/{arch}] {img@antes} | jq '[.layers[].size]|add'` vs `{img@después}` → menor; `docker run --rm -i hadolint/hadolint < {Dockerfile}` → exit 0; `test -f .dockerignore`.
  - Salida esperada: comprimido después < antes en cada imagen tocada, hadolint limpio, .dockerignore presente.

- [ ] Bases comunes adoptadas donde haya 3 o más consumidores de la misma pila, fijadas por digest.
  - Comando: `grep -n '^FROM' {Dockerfile}` → la base común de 536 por `@sha256:` (los *-mcp y varias apps comparten pila python o node).
  - Salida esperada: los Dockerfiles de 3+ consumidores de una pila usan la base común por digest.

- [ ] Sin regresión: cada imagen nueva pasa sus tests y su healthcheck y queda verificada en producción tras su pin.
  - Comando: `kubectl rollout status deploy/{name} -n {ns} --timeout=180s` → "successfully rolled out"; `kubectl get pods -n {ns} -l {selector} -o jsonpath='{.items[*].status.containerStatuses[*].ready}'` → true; tests de CI en verde. Para mcp-stdio-pool-bridge, comprobar que los MCP que la consumen responden (no solo el pod ready).
  - Salida esperada: rollout completo, pods ready, tests verdes y los MCP/apps responden en producción.

- [ ] Guard de CI conectado a los workflows que construyen estas imágenes.
  - Comando: `grep -rEl 'image-guard|hadolint' .github/workflows/` en cada repo del dominio → el workflow de build invoca el reusable de 536.
  - Salida esperada: el build de las imágenes del dominio corre lint + check de tamaño.

## Restricciones
- Bloqueada por INFRA-536: necesita inventario, bases comunes por digest y guard reusable.
- GitOps: PR contra el tronco que lee ArgoCD para cada repo (comprobar `.spec.source.targetRevision`; hermes-agent vive en k8s-openclaw-qwen36-pocharlies que lee `deploy/prod`); el pin va en el repo de manifiestos correspondiente. Nunca push directo al tronco.
- mcp-stdio-pool-bridge es infraestructura MCP compartida de la compañía: una regresión rompe ~15-20 MCP a la vez. Verificar los MCP consumidores, no solo el pod. Reversible con el pin anterior.
- hermes-agent es un fork y se despliega SOLO con su pipeline (hermes-despliegue.yml, runner x86-hermes); la app de ArgoCD `hermes` está en sync manual: nunca `kubectl rollout restart deploy/hermes-gateway` ni `argocd app sync hermes`. Un cambio solo de imagen sigue su pipeline.
- El inventario de 536 clasifica propias vs espejos: algunas de esta lista (p. ej. aurora-kubectl-agent de gcr, codex-arcade si es de tercero) pueden quedar fuera. Trabajar solo las confirmadas como propias.
- No tocar imágenes de terceros (redis, onepassword-connect, vllm, searxng, clamav, minio, nats, agentgateway).
- No arreglar el buildkit degradado (INFRA-475).

## Trabajo reciente (24 h)
- 04-10-2026, sesión pm: medido con crane — `mcp-stdio-pool-bridge:v0.1.9` amd64 = 164065072 bytes comprimido, 11 capas; la consumen ~15-20 Deployments MCP (analytics, company-metrics, cto-office, gsc, merchant, onepassword, shopify, studio, tts, workspace, hermes). Es el arreglo de mayor apalancamiento del dominio: una imagen, muchos consumidores.
- 04-10-2026, INFRA-475 (sre-devops): buildkit degradado — ralentiza builds, fuera de alcance.
- 03-10-2026, sesión 2a51949b: origen de INFRA-474.
- Sin sesión VIVA en estos repos sobre tamaño de imágenes.

## Diseño
Diseñador: no — sin interfaz de usuario nueva; son Dockerfiles y sus despliegues. (galan/uriel/blog/web-edani/libreplay tienen UI, pero aquí solo se aligera su imagen, no se cambia la interfaz.)

## Historias previstas
- mcp-stdio-pool-bridge y mcp-stdio-bridge (developer): la imagen compartida, multi-stage + sin caché + base común; alto apalancamiento, va primero.
- *-mcp sueltos (developer): brain-mcp, dgx-synapse-mcp, stt-mcp, offers-mcp, picqer-mcp, shopify-admin-mcp, tesla-control-mcp, teslamate-mcp.
- Apps sueltas (developer): blog, cv-*, ha-dashboard, libreplay-web, tomorrowland-app, galan/uriel, web-edani, serpentetool, opencode-node-ops, agent-jake-browser, bambulab-openclaw, aurora, codex-arcade, hermes-agent (por su pipeline).
- Builds, pines y before/after (devops): por repo, construir, subir, pinear, medir.
- Verificación en producción (qa): rollout + healthcheck + los MCP/apps responden.
- Guard CI (devops): conectar el reusable de 536 a los workflows de build del dominio.

## Tamaño
L — muchas imágenes pequeñas en ~20 repos distintos, con una de alto apalancamiento (mcp-stdio-pool-bridge) y varias apps sueltas; cada una con su PR, pin y verificación. Probablemente haya que secuenciarlo (primero la infra MCP compartida, luego las apps); si al arrancar supera una semana, el tech-lead lo parte.

## Dificultad
Dificultad: media — la mayoría son imágenes pequeñas y cambios reversibles con el pin anterior, pero mcp-stdio-pool-bridge es infraestructura MCP compartida (una regresión rompe ~15-20 MCP de la compañía a la vez) y hermes-agent tiene su propio pipeline de despliegue manual. No es alta porque no toca infraestructura delicada del clúster ni datos irreversibles, y cada app se revierte por separado.
