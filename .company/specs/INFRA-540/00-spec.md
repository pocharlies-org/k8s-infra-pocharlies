Rol: pm · Fecha: 2026-10-04T20:35:00Z · Sesión: 0d8a0749-bdf2-4720-9979-e7b4d0128a5d · Estado: LISTO

## Objetivo
Aligerar synapse (la imagen propia más grande medida: 581.614.255 B comprimidos, 16 capas, medida hoy con crane) y las 8 imágenes de su dominio (synapse-document-intake y las whatsappmcp de socialmedia, entre 196 y 232 MB cada una), aplicando multi-stage, bases comunes por digest, sin cachés en la capa final y .dockerignore, con antes/después medido y verificación en producción (synapse mueve pedidos, mensajería y SII). Hija de INFRA-474; usa el inventario, las bases comunes y el guard reusable que produce INFRA-536 (bloqueada por ella; sin solape de alcance con otras hijas: 537 jarvis, 538 dgx-infra, 539 skirmshop, 541 mcp-stdio-pool-bridge y cola larga).

Repo: synapse (ancla; el dominio abarca también synapse-document-intake y k8s-socialmedia-pocharlies, donde viven los Dockerfiles de las whatsappmcp — medido: los 8 Dockerfiles están en connectors/*, mcp-server/ y workers/ de ese repo; ~/k8s/whatsappmcp está vacío).

## Criterios de aceptación
- [ ] C1 — Cada imagen propia del dominio con Dockerfile saneado: multi-stage donde aplique, sin caché de pip/uv/npm/apt en la capa final, dependencias antes que código, sin duplicadas. (.dockerignore ya existe en los 3 repos — medido hoy: synapse/, synapse-document-intake/ y k8s-socialmedia-pocharlies/ lo tienen.)
  - Comando: por imagen nueva, crane export harbor.lan.e-dani.com/homelab/{img}@{digest-nuevo} - | tar -tf - | grep -E '(^|/)(\.cache|__pycache__|\.npm|\.uv|\.pnpm-store)/' → vacío; hadolint sobre el Dockerfile → exit 0 sin errores; grep -c '^FROM' {Dockerfile} → ≥2 donde aplique multi-stage (hoy synapse y todos los whatsappmcp tienen 1 solo FROM — medido).
  - Salida esperada: ninguna caché en la capa final, hadolint limpio, y los Dockerfiles de synapse y document-intake con etapas de build separadas de runtime.

- [ ] C2 — Antes/después medido con crane manifest y el comprimido baja en cada imagen; synapse mantiene su fila en la tabla top-10 de la épica padre.
  - Comando: antes (medido hoy 04-10): crane manifest harbor.lan.e-dani.com/homelab/synapse@sha256:9a53aad429a22dea95ddcebde6fc7b76172074cbc31909c645e03f339234d3cd | jq '[.layers[].size]|add' → 581614255. Baselines hoy por tag (el pin por digest suelto falla sin el nombre; usar tag): mcp-server:v1.3.98 → 215183574; whatsapp-connector:v1.3.94 → 217065848; telegram-connector:v1.3.78 → 202049722; telegram-sync:v1.3.82 → 197437788; instagram-connector:v1.3.74 → 196408896; crane manifest --platform linux/amd64 harbor.lan.e-dani.com/homelab/synapse-document-intake:0.1.2-20260620 | jq '[.layers[].size]|add' → 231629255 (es índice multi-arch: siempre --platform linux/amd64). Después: el mismo comando con el tag/digest nuevo.
  - Salida esperada: comprimido después < antes en las 7 imágenes; synapse con su fila en la tabla de la épica padre.

- [ ] C3 — Bases comunes fijadas por digest donde haya 3+ consumidores de la misma pila.
  - Comando: grep -n '^FROM' {Dockerfile} → la base del inventario 536 por @sha256:. Medido hoy: 7 Dockerfiles de k8s-socialmedia-pocharlies usan harbor.lan.e-dani.com/cache/library/node:22-bookworm-slim SIN digest (instagram, telegram, whatsapp-cloud, whatsapp-synapse-bridge, whatsapp-web, mcp-server, whatsapp-open-worker → 3+ consumidores, les aplica); telegram-sync usa python:3.12-slim (1 consumidor en el repo); synapse ya fija su base uv por digest pero document-intake usa python:3.12-slim sin digest.
  - Salida esperada: FROM por digest en los 7 node, en document-intake y donde 536 defina base común python.

- [ ] C4 — Sin regresión: cada imagen nueva pasa sus tests, su healthcheck y queda verificada en producción tras su pin. OJO (medido hoy): synapse es UNA imagen consumida por ~20 Deployments en el ns synapse pinneados a digests DISTINTOS (9a53aad admin, 6f96b07 shopify/reminders/trellis/expenses, 1c853d2 messaging-send/media/contact-sync, 2bd5513, 1fd8065…) — la entrega debe subir TODOS los pins al digest nuevo, no solo uno.
  - Comando: kubectl get application {synapse|document-intake|socialmedia} -n argocd -o jsonpath='{.spec.source.targetRevision} {.status.sync.status}' → «deploy/prod Synced» (los tres medidos hoy: deploy/prod); kubectl get deploy -n synapse -o jsonpath='{range .items[*]}{.metadata.name}={.spec.template.spec.containers[0].image}{"\n"}{end}' con todos los digests = el nuevo; kubectl rollout status deploy/{name} -n {ns} --timeout=180s → successfully rolled out para los deployments clave (engine/gateway/admin/dispatcher/adapters, whatsapp-connector, telegram-sync, mcp-server); y un pedido/mensaje de prueba de synapse y del bridge WhatsApp→Synapse funciona.
  - Salida esperada: rollout completo, pods ready, CI verde, flujo de negocio (mensajería/pedidos/SII) vivo; reversible con el pin anterior en cada repo de manifiestos.

- [ ] C5 — Guard de CI conectado a los workflows que construyen estas imágenes.
  - Comando: grep -rEl 'image-guard|hadolint' .github/workflows/ en synapse, synapse-document-intake y k8s-socialmedia-pocharlies → el workflow de build (en socialmedia es ci.yml, matriz de 8 imágenes en las líneas ~130-136) invoca el reusable de 536.
  - Salida esperada: el build de cada imagen del dominio corre lint + check de tamaño en CI.

## Restricciones
- Bloqueada por INFRA-536 (To Do, spec LISTO): necesita su inventario, bases comunes por digest y guard reusable. No arrancar hasta que 536 cierre.
- GitOps: PR contra deploy/prod en los tres (medido hoy en .spec.source.targetRevision de las apps ArgoCD synapse, document-intake y socialmedia). El pin va en k8s-synapse-pocharlies / k8s-document-intake-pocharlies / k8s-socialmedia-pocharlies (overlays/prod/patch-image.yaml en socialmedia). Nunca push directo al tronco.
- synapse es infraestructura crítica (mensajería, pedidos, SII, adapters): una regresión rompe flujos de Skirmshop. Una imagen → ~20 Deployments con pins distintos: subirlos todos con su PR y verificar los clave; reversible con el pin anterior.
- synapse-smtp corre en el ns synapse con imagen ghcr.io/pocharlies/synapse-smtp:2026.07.08-1 (org propia en ghcr; crane manifest contra ghcr no resuelve sin auth — que la clasifique el inventario de 536: si es espejo/adaptación de tercero, fuera de alcance).
- No tocar clamav (tercero en document-intake) ni imágenes de terceros. Las bases cache/library/* de Harbor son espejos: se pinnean por digest, no se reconstruyen.
- No arreglar el buildkit degradado (INFRA-475).

## Trabajo reciente (24 h)
- 04-10-2026 ~19:40 UTC, sesión pm 31bce0d2 (plan de INFRA-474): esta hija creada con spec borrador LISTO; midió synapse@9a53aad = 581.614.255 B / 16 capas (la mayor propia). Este spec revalida y amplía sus premisas con mediciones de hoy.
- 04-10-2026, sesión pm VIVA en INFRA-536 (ses-pm-INFRA-536, 63e87f75): el inventario/bases/guard se está construyendo ahora — es la puerta de esta; no duplicar su trabajo.
- 04-10-2026, INFRA-475 (sre-devops): buildkit degradado — ralentiza builds, fuera de alcance.
- Medido hoy por esta fase de plan: tamales de las 7 imágenes (C2), Dockerfiles de las whatsappmcp en k8s-socialmedia-pocharlies (~/k8s/whatsappmcp vacío), targetRevision deploy/prod en las 3 apps ArgoCD, .dockerignore presente en los 3 repos, pins de synapse fragmentados entre ~20 deployments con digests distintos.

## Diseño
Diseñador: no — sin interfaz nueva; son Dockerfiles, CI y pins GitOps.

## Historias previstas
- Dockerfile de synapse (developer): multi-stage, base python común por digest, sin caché, deps antes que código; afecta a los ~20 Deployments del ns synapse.
- Dockerfile de synapse-document-intake (developer): multi-stage, base python por digest, misma higiene (hoy FROM python:3.12-slim sin digest, un solo FROM).
- Dockerfiles de las whatsappmcp (developer): los 8 del repo k8s-socialmedia-pocharlies (mcp-server, conectores whatsapp-web/whatsapp-cloud/telegram/instagram, telegram-sync, whatsapp-synapse-bridge, whatsapp-open-worker): node:22 por digest común, multi-stage donde aplique.
- Builds, pines y before/after (devops): por repo, construir, subir, pinear TODOS los deployments de synapse al digest nuevo, medir C2.
- Guard CI (devops): conectar el reusable de 536 a ci.yml de socialmedia y a los workflows de build de synapse y document-intake.
- Verificación en producción (qa): rollout de los deployments clave + healthcheck + flujo de mensajería/pedidos/SII y bridge WhatsApp→Synapse.

## Tamaño
M — 7-8 imágenes pero un solo patrón de cambio (reescritura de Dockerfile + pin); la complejidad está en verificar el flujo de negocio de synapse sin romperlo, no en el número de ficheros. Menos de una semana, ≤6 historias: un CTO.

## Dificultad
Dificultad: media — no hay decisión de arquitectura ni toca infraestructura delicada del cluster (el cambio es de Dockerfile/pin, reversible con el pin anterior), pero synapse es infraestructura crítica de negocio con ~20 deployments pinneados a digests distintos y hay que mirar qué existe (bases de 536, matriz de ci.yml) antes de escribir para no duplicar ni romper; la verificación del flujo de negocio sube el riesgo por encima de baja.
