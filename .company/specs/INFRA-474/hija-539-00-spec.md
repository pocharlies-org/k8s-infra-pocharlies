Rol: pm · Fecha: 2026-10-04 · Sesión: 31bce0d2-7f1f-492d-8c17-6f2ee2b613f3 · Estado: LISTO

## Objetivo
Aligerar las imágenes propias del dominio Skirmshop (tienda en producción), aplicando bases comunes, multi-stage, sin cachés en la capa final, .dockerignore y dependencias antes que código. Son muchas imágenes pequeñas/medianas (Node y Python) repartidas en varios repos; el objetivo es que bajen de tamaño sin romper negocio (labels, SII, pedidos).

Repo: skirmshop-labels (ancla, 17 imágenes) y los repos del dominio — la lista definitiva la fija el inventario de INFRA-536.

Imágenes del dominio: skirmshop-labels-* (correos-adapter, correos-express-adapter, event-gateway, event-projector, label-storage, notification-dispatcher, outbox-relay, routing-service, saga-launcher, shopify-app, shopify-fulfillment-service, synapse-janitor, synapse-workflow-registrar, telegram-optin-ingest, tracking-ingestion, ups-adapter, whatsapp-optin-ingest), shopify-affiliate-app, shopify-back-in-stock (+worker-email, +worker-whatsapp), shopify-bundle-app, shopify-collections-tree-app, shopify-translation-app, shopify-sii-app, shopify-admin-mcp, skirmshop-serial-numbers, skirmshopshopifyapp (rag-app), skirmshop-picker, skirmshop-brain-v2, control-panel-bff, control-panel-ui, skirmbooks-backend, skirmbooks-ui, skirmbooks-aeat-browser.

## Criterios de aceptación
- [ ] Cada imagen propia del dominio: Dockerfile multi-stage donde aplique, sin caché de pip/uv/npm/apt en la capa final, .dockerignore, dependencias antes que código, sin dependencias duplicadas.
  - Comando: por imagen, `crane export {img@nuevo} - | tar -tf - | grep -E '(^|/)(\.cache|__pycache__|node_modules/\.cache|\.npm|\.uv)/'` → vacío; `docker run --rm -i hadolint/hadolint < {Dockerfile}` → exit 0 sin errores; `test -f .dockerignore`.
  - Salida esperada: ninguna caché en la capa final, hadolint limpio y .dockerignore en cada imagen tocada.

- [ ] Antes/después con crane manifest: el tamaño comprimido baja en todas las tocadas; las que estén entre las 10 propias más grandes entran en la tabla de la épica.
  - Comando: `crane manifest {img@antes} | jq '[.layers[].size]|add'` (si `.manifests` existe, resolver con `--platform linux/amd64`: estas imágenes corren en x86/sauvage) vs el digest nuevo → menor.
  - Salida esperada: comprimido después < antes en cada imagen; las mayores del dominio (skirmbooks-backend, rag-app, control-panel) con su fila si entran en el top-10.

- [ ] Bases comunes adoptadas donde haya 3 o más consumidores de la misma pila (p. ej. node, python-slim+uv), fijadas por digest.
  - Comando: `grep -n '^FROM' {Dockerfile}` → la base común de 536 por `@sha256:` en los 3+ consumidores de una pila (las 17 labels y las shopify-apps comparten pila).
  - Salida esperada: los Dockerfiles de una misma pila (node o python) usan la base común por digest.

- [ ] Sin regresión: cada imagen nueva pasa sus tests y su healthcheck y queda verificada en producción tras su pin (Skirmshop es negocio: cuidado con labels, SII, pedidos).
  - Comando: `kubectl rollout status deploy/{name} -n {ns} --timeout=180s` → "successfully rolled out"; `kubectl get pods -n {ns} -l {selector} -o jsonpath='{.items[*].status.containerStatuses[*].ready}'` → true; tests de CI del repo en verde. Para labels/SII/pedidos, comprobar el flujo de negocio (no solo el pod).
  - Salida esperada: rollout completo, pods ready, tests verdes y el flujo de negocio (etiquetas, SII, pedidos) funciona en producción.

- [ ] Guard de CI conectado a los workflows que construyen estas imágenes.
  - Comando: `grep -rEl 'image-guard|hadolint' .github/workflows/` en cada repo del dominio → el workflow de build invoca el reusable de 536.
  - Salida esperada: el build de las imágenes del dominio corre lint + check de tamaño.

## Restricciones
- Bloqueada por INFRA-536: necesita inventario, bases comunes por digest y guard reusable.
- GitOps: PR contra el tronco que lee ArgoCD para cada repo (comprobar `.spec.source.targetRevision`; en el dominio Skirmshop suele ser `deploy/prod` o `master`, no asumir `main`); el pin de despliegue va en el repo de manifiestos k8s-shopify-*-pocharlies / k8s-skirmbooks-pocharlies / etc. Nunca push directo al tronco.
- Skirmshop es negocio en producción: labels, SII, pedidos y control-panel no pueden romperse. Cada imagen con su PR, su pin y su verificación de negocio; reversible con el pin anterior.
- Varias imágenes son amd64 (x86/sauvage); resolver el índice multi-arch a amd64 si lo hay.
- No tocar imágenes de terceros (synapse/api, correlator, operator de serverlessworkflow; clamav; maddy; minio): solo inventario/grafo.
- No arreglar el buildkit degradado (INFRA-475).

## Trabajo reciente (24 h)
- 04-10-2026, sesión pm: medido con crane/kubectl — el dominio Skirmshop aporta ~35 de las 100 imágenes propias candidatas; `mcp-stdio-pool-bridge` (164 MB) la usan varios MCP de Skirmshop pero es de la hija 541; `skirmbooks-backend` y `skirmshopshopifyapp` (rag-app) son de las mayores del dominio.
- 04-10-2026, INFRA-475 (sre-devops): buildkit degradado — ralentiza builds, fuera de alcance.
- 03-10-2026, sesión 2a51949b: origen de INFRA-474.
- Sin sesión VIVA en Skirmshop sobre tamaño de imágenes. SC-1759 (e2e) no toca estos repos.

## Diseño
Diseñador: no — sin interfaz de usuario nueva; son Dockerfiles y sus despliegues. (control-panel-ui tiene UI, pero aquí solo se aligera su imagen, no se cambia la interfaz.)

## Historias previstas
- Dockerfiles de skirmshop-labels (developer): las 17 imágenes, base común node/python por digest, multi-stage, sin caché.
- Dockerfiles de shopify-apps (developer): affiliate, back-in-stock(+workers), bundle, collections-tree, translation, sii, serial-numbers, rag-app, picker, brain-v2, control-panel-bff/ui.
- Dockerfiles de skirmbooks (developer): backend, ui, aeat-browser.
- Builds, pines y before/after (devops): por repo, construir, subir, pinear, medir.
- Verificación en producción (qa): rollout + healthcheck + flujo de negocio (labels/SII/pedidos).
- Guard CI (devops): conectar el reusable de 536 a los workflows de build del dominio.

## Tamaño
L — ~35 imágenes en ~15 repos, todas en producción de negocio, cada una con su PR, pin y verificación. Probablemente haya que secuenciarlo por subdominio (labels / shopify-apps / skirmbooks); si al arrancar supera una semana, el tech-lead lo parte.

## Dificultad
Dificultad: media — los cambios son Dockerfile por Dockerfile, acotados y reversibles con el pin anterior, y las imágenes son pequeñas/medianas; pero es negocio en producción (labels, SII, pedidos) y una regresión rompe el flujo de la tienda. No es alta porque cada imagen se puede revertir al pin anterior en minutos y no toca infraestructura delicada ni datos irreversibles.
