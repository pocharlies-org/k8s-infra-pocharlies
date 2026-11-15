Rol: pm · Fecha: 2026-10-04T21:40:00Z · Sesión: eee84ade-1925-48c5-b452-703c4e1fff97 · Estado: LISTO

## Objetivo
Aligerar las imágenes propias del dominio Skirmshop (labels, shopify-apps, control-panel, picker, brain-v2, rag, skirmbooks) con bases comunes, multi-stage, sin cachés en la capa final, .dockerignore y dependencias antes que código, con antes/después medido con crane y verificado en producción. Bloqueada por INFRA-536 (inventario, bases comunes por digest y guard CI reusable); `mcp-stdio-pool-bridge` es de INFRA-541, no de esta épica.

Repo: skirmshop-labels

Imágenes del dominio y dónde está su Dockerfile (verificado el 04-10 en `~/k8s/<repo>`, excluyendo `.claude/worktrees/*`, que son copias de agentes y no cuentan):
- skirmshop-labels: **un solo `Dockerfile`** parametrizado con `--build-arg APP=<workspace>` que produce las 17 imágenes (ya es multi-stage, `pnpm deploy --prod`, node:22-alpine; usa `--mount=type=cache` que no entra en la imagen). Hay `.dockerignore`.
- skirmshopshopifyapp (rag-app): `Dockerfile` multi-stage (deps/builder/runner, node:20-alpine); el runner copia el `node_modules` completo del builder (con devDependencies) → candidato claro.
- skirmbooks-gestoria-src: `Dockerfile` (backend, **una sola etapa** sobre `uv:python3.12-bookworm-slim`, instala apt) → candidato claro; además `Dockerfile.deploy-delta` y `Dockerfile.migrations`. skirmbooks-ui y skirmbooks-aeat-browser: el CTO los localiza en el inventario de INFRA-536.
- shopify-back-in-stock (3 Dockerfiles: app + workers email/whatsapp), shopify-bundle-app, shopify-collections-tree-app, shopify-translation-app, shopify-sii-app (4 FROM; **sin `.dockerignore`**), skirmshop-affiliate-api, skirmshop-serial-numbers, skirmshop-brain-v2 (`Dockerfile` + `Dockerfile.relations`), skirmshop-control-panel (`bff/` y `web/`, Dockerfile dentro de cada subcarpeta), k8s-shopify-admin-mcp-pocharlies (1 Dockerfile, sin `.dockerignore`).
- skirmshop-picker: **no hay** Dockerfile en `k8s-shopify-picker-pocharlies` ni repo `skirmshop-picker` en `~/k8s`; el CTO lo localiza vía el inventario de INFRA-536. No se inventan rutas.
- Fuera: imágenes de terceros (clamav, maddy, minio, synapse/api, correlator, operator serverlessworkflow) y `mcp-stdio-pool-bridge` (INFRA-541).

## Criterios de aceptación
- [ ] Cada imagen propia del dominio tocada: Dockerfile multi-stage donde aplique, sin caché de pip/uv/npm/apt en la capa final, `.dockerignore` presente, dependencias antes que código, sin devDependencies en el runner.
  - Comando: `crane export {img@nuevo} - | tar -tf - | grep -E '(^|/)(\.cache|__pycache__|node_modules/\.cache|\.npm|\.uv|var/lib/apt/lists/.+)'` → vacío; `docker run --rm -i hadolint/hadolint < {Dockerfile}` → exit 0 (hadolint no está instalado en el x86; se corre por docker); `test -f {repo}/.dockerignore` → exit 0.
  - Salida esperada: ninguna caché en la capa final, hadolint limpio (o con `# hadolint ignore=` justificado en el propio Dockerfile) y `.dockerignore` en cada repo tocado.

- [ ] Antes/después con crane: el tamaño comprimido baja en todas las imágenes tocadas; las mayores del dominio (skirmbooks-backend, rag-app, control-panel-bff/ui, labels) llevan fila en la tabla de la épica.
  - Comando: `crane manifest --platform linux/amd64 {img@antes} | jq '[.layers[].size]|add'` y lo mismo con `{img@nuevo}` (resolver el índice multi-arch a amd64: corren en x86/sauvage).
  - Salida esperada: bytes después < bytes antes en cada imagen; las 17 labels comparten Dockerfile, así que basta medir cada una y registrar la tabla completa en `50-entrega.md`.

- [ ] Bases comunes adoptadas donde haya 3 o más consumidores de la misma pila (node, python-slim+uv), fijadas por digest, usando las que entregue INFRA-536.
  - Comando: `grep -n '^FROM' {Dockerfile}` en cada Dockerfile de una misma pila.
  - Salida esperada: los Dockerfiles de la pila usan la base común de 536 con `@sha256:`. Si 536 no entregó la base de una pila, esa pila queda fuera con motivo escrito (no se crea una base propia aquí).

- [ ] Sin regresión: cada imagen nueva pasa los tests de su repo y su healthcheck, y queda verificada en producción tras su pin.
  - Comando: `kubectl rollout status deploy/{name} -n {ns} --timeout=180s` → `successfully rolled out`; `kubectl get pods -n {ns} -l {selector} -o jsonpath='{.items[*].status.containerStatuses[*].ready}'` → `true`; `kubectl get deploy {name} -n {ns} -o jsonpath='{.spec.template.spec.containers[*].image}'` → el digest nuevo (objeto vivo, no el semáforo de ArgoCD); CI del repo en verde. Flujo de negocio: labels (crear una etiqueta de prueba o `labels_shipment_status` sobre un pedido real reciente), SII (envío/estado SII), pedidos/rag-app (endpoint de salud + una consulta), control-panel (login + carga de la UI).
  - Salida esperada: rollout completo, pods ready, digest vivo = digest nuevo, tests verdes y flujo de negocio verificado por qa en producción.

- [ ] Guard de CI conectado a los workflows que construyen estas imágenes.
  - Comando: `grep -rEl 'image-guard|hadolint' {repo}/.github/workflows/` en cada repo del dominio tocado.
  - Salida esperada: el workflow de build de cada repo invoca el reusable de 536 (lint + check de tamaño).

## Restricciones
- Bloqueada por INFRA-536 (hoy en To Do, 04-10: sin inventario, bases comunes ni guard entregados). No se arranca el build hasta que 536 esté Done.
- GitOps: PR contra el tronco que lee ArgoCD para cada repo (comprobar `.spec.source.targetRevision` de su Application; skirmshop-labels es `main`, el resto suele ser `deploy/prod` o `master`, no asumir). El pin de despliegue va en el repo de manifiestos (`k8s-shopify-*-pocharlies`, `k8s-skirmbooks-pocharlies`, `k8s-skirmshop-control-panel-pocharlies`, etc.). Nunca push directo al tronco.
- Skirmshop es negocio en producción: labels, SII, pedidos y control-panel no se rompen. Una imagen = un PR = un pin = una verificación; reversible volviendo al pin anterior.
- amd64 (x86/sauvage): resolver índices multi-arch a `linux/amd64`.
- Ignorar `.claude/worktrees/*` al contar o lintar Dockerfiles (copias de agentes).
- No tocar imágenes de terceros ni `mcp-stdio-pool-bridge` (INFRA-541). No arreglar el buildkit degradado (INFRA-475).
- Si el repo no tiene `ARCHITECTURE.md` (ninguno de los muestreados lo tiene), se anota para el architect; no bloquea.

## Trabajo reciente (24 h)
- 04-10-2026, sesión pm 31bce0d2: borrador previo con mediciones de crane/kubectl (~35 de las 100 imágenes propias candidatas son de Skirmshop). Re-validado hoy: premisas vivas salvo la cuenta de Dockerfiles de labels (1 Dockerfile para 17 imágenes, no 17).
- 04-10-2026, INFRA-475 (sre-devops): buildkit degradado, ralentiza builds, fuera de alcance.
- `company-sesion estado --key INFRA-539` → sin sesiones; ningún transcript de las últimas 24 h menciona INFRA-539/536 salvo esta planificación. INFRA-536 sigue en To Do.

## Diseño
Diseñador: no — sin interfaz nueva; son Dockerfiles y sus despliegues (control-panel-ui solo cambia su imagen, no su interfaz).

## Historias previstas
- Dockerfile de skirmshop-labels (developer): ajustar el único Dockerfile (base común por digest, runtime mínimo, hadolint) y medir las 17 imágenes.
- Dockerfiles de shopify-apps y servicios (developer): affiliate, back-in-stock (+workers), bundle, collections-tree, translation, sii, serial-numbers, rag-app (skirmshopshopifyapp), picker, admin-mcp, brain-v2, control-panel bff/web; añadir `.dockerignore` donde falte (sii, admin-mcp).
- Dockerfiles de skirmbooks (developer): backend (pasar a multi-stage), deploy-delta, migrations, ui, aeat-browser.
- Builds, pines y antes/después (devops): por repo, construir, subir, pinear en el repo de manifiestos y medir con crane.
- Verificación en producción (qa): rollout, healthcheck y flujo de negocio (labels, SII, pedidos, control-panel) sobre el objeto vivo.
- Guard CI (devops): conectar el reusable de 536 a los workflows de build de los repos del dominio.

## Tamaño
L — ~35 imágenes en ~15 repos, todas en producción de negocio, cada una con PR, pin y verificación. Son cambios acotados por Dockerfile y reversibles por pin; se secuencia por subdominio (labels / shopify-apps / skirmbooks). Si al arrancar el tech-lead estima más de una semana, la parte en tandas dentro de esta misma épica (no se divide en hijas).

## Dificultad
Dificultad: media — cambios Dockerfile por Dockerfile, acotados y reversibles con el pin anterior; el riesgo es de negocio (labels, SII, pedidos), no técnico. El guard CI reutiliza el reusable de 536 y esta épica solo lo conecta, no toca CI/CD compartido, por eso no sube a alta.
