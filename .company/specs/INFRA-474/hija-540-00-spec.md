Rol: pm · Fecha: 2026-10-04 · Sesión: 31bce0d2-7f1f-492d-8c17-6f2ee2b613f3 · Estado: LISTO

## Objetivo
Aligerar synapse (la imagen propia más grande medida, 581 MB comprimida), synapse-document-intake y las imágenes whatsappmcp/socialmedia, aplicando bases comunes, multi-stage, sin cachés en la capa final, .dockerignore y dependencias antes que código. Synapse mueve pedidos, mensajería y SII en producción, así que el antes/después se mide y cada imagen se verifica en producción tras su pin.

Repo: synapse (ancla) y synapse-document-intake, k8s-socialmedia-pocharlies — la lista definitiva la fija el inventario de INFRA-536.

Imágenes del dominio: synapse (una imagen, muchos Deployments: engine, gateway, admin, dispatcher, adapters, mcp), synapse-document-intake, whatsappmcp-mcp-server, whatsappmcp-whatsapp-connector, whatsappmcp-telegram-connector, whatsappmcp-telegram-sync, whatsappmcp-instagram-connector, whatsappmcp-whatsapp-synapse-bridge, synapse-smtp (si es propia; si es espejo de tercero, fuera).

## Criterios de aceptación
- [ ] Cada imagen propia del dominio: Dockerfile multi-stage donde aplique, sin caché de pip/uv/npm/apt en la capa final, .dockerignore, dependencias antes que código, sin dependencias duplicadas.
  - Comando: por imagen, `crane export {img@nuevo} - | tar -tf - | grep -E '(^|/)(\.cache|__pycache__|node_modules/\.cache|\.npm|\.uv)/'` → vacío; `docker run --rm -i hadolint/hadolint < {Dockerfile}` → exit 0 sin errores; `test -f .dockerignore`.
  - Salida esperada: ninguna caché en la capa final, hadolint limpio y .dockerignore en cada imagen tocada.

- [ ] synapse (581 MB) y las demás: antes/después con crane manifest, el tamaño comprimido baja; synapse entra en la tabla de las 10 propias más grandes de la épica.
  - Comando: antes `crane manifest harbor.lan.e-dani.com/homelab/synapse@sha256:9a53aad429a22dea95ddcebde6fc7b76172074cbc31909c645e03f339234d3cd | jq '[.layers[].size]|add'` → 581614255; después el mismo comando con el digest nuevo → menor. Para cada imagen del dominio, igual (resolver `--platform linux/amd64` si es índice).
  - Salida esperada: comprimido después < antes en cada imagen; synapse con su fila en la tabla de la épica.

- [ ] Bases comunes adoptadas donde haya 3 o más consumidores de la misma pila, fijadas por digest.
  - Comando: `grep -n '^FROM' {Dockerfile}` → la base común de 536 por `@sha256:` (synapse y document-intake comparten pila python; las whatsappmcp comparten pila node/python).
  - Salida esperada: los Dockerfiles de 3+ consumidores de una pila usan la base común por digest.

- [ ] Sin regresión: cada imagen nueva pasa sus tests y su healthcheck y queda verificada en producción tras su pin (synapse mueve pedidos/mensajería/SII: cuidado).
  - Comando: `kubectl rollout status deploy/{name} -n {ns} --timeout=180s` → "successfully rolled out" (synapse tiene muchos Deployments: engine, gateway, dispatcher, adapters — verificar los del dominio tocado); `kubectl get pods -n synapse -l {selector} -o jsonpath='{.items[*].status.containerStatuses[*].ready}'` → true; tests de CI en verde; y el flujo de negocio (un pedido/mensaje de prueba) funciona.
  - Salida esperada: rollout completo, pods ready, tests verdes y el flujo de synapse (mensajería/pedidos/SII) funciona en producción.

- [ ] Guard de CI conectado a los workflows que construyen estas imágenes.
  - Comando: `grep -rEl 'image-guard|hadolint' .github/workflows/` en synapse, synapse-document-intake y k8s-socialmedia-pocharlies → el workflow de build invoca el reusable de 536.
  - Salida esperada: el build de las imágenes del dominio corre lint + check de tamaño.

## Restricciones
- Bloqueada por INFRA-536: necesita inventario, bases comunes por digest y guard reusable.
- GitOps: PR contra el tronco que lee ArgoCD para cada repo (synapse, document-intake y socialmedia leen `deploy/prod` según CLAUDE.md — comprobar `.spec.source.targetRevision`, no asumir); el pin va en k8s-synapse-pocharlies / k8s-document-intake-pocharlies / k8s-socialmedia-pocharlies. Nunca push directo al tronco.
- synapse es infraestructura de negocio crítica (mensajería, pedidos, SII, adapters): una regresión rompe flujos de Skirmshop y compañía. Cada imagen con su PR, pin y verificación de flujo; reversible con el pin anterior.
- synapse es UNA imagen consumida por ~20 Deployments (engine, gateway, admin, dispatcher, adapters, mcp): un cambio en el Dockerfile afecta a todos; verificar los Deployments clave, no solo uno.
- synapse-smtp (ghcr pocharlies/synapse-smtp): si el inventario la clasifica como espejo de tercero, queda fuera.
- No tocar clamav (document-intake la usa de tercero) ni imágenes de terceros.
- No arreglar el buildkit degradado (INFRA-475).

## Trabajo reciente (24 h)
- 04-10-2026, sesión pm: medido con crane — `synapse@sha256:9a53aad…` = 581614255 bytes comprimido, 16 capas: es la imagen propia más grande medida hasta ahora (mayor que jarvis-backend, 488 MB). Está en la tabla de las 10 mayores de la épica. Las whatsappmcp-* y document-intake completan el dominio.
- 04-10-2026, INFRA-475 (sre-devops): buildkit degradado — ralentiza builds, fuera de alcance.
- 03-10-2026, sesión 2a51949b: origen de INFRA-474.
- Sin sesión VIVA en synapse/socialmedia sobre tamaño de imágenes.

## Diseño
Diseñador: no — sin interfaz de usuario nueva; son Dockerfiles y sus despliegues.

## Historias previstas
- Dockerfile de synapse (developer): multi-stage, base común python por digest, sin caché, deps antes que código; afecta a todos los Deployments que consumen la imagen.
- Dockerfile de synapse-document-intake (developer): misma higiene.
- Dockerfiles de whatsappmcp/socialmedia (developer): mcp-server, conectores whatsapp/telegram/instagram, telegram-sync, whatsapp-synapse-bridge.
- Builds, pines y before/after (devops): por repo, construir, subir, pinear, medir (synapse entra en la tabla top-10).
- Verificación en producción (qa): rollout de los Deployments clave + healthcheck + flujo de mensajería/pedidos/SII.
- Guard CI (devops): conectar el reusable de 536 a los workflows de build del dominio.

## Tamaño
M — synapse es una imagen (aunque la consuman ~20 Deployments) y document-intake/socialmedia son unas 8 imágenes más; la complejidad está en verificar que el flujo de negocio no se rompe, no en el número de Dockerfiles. Una semana.

## Dificultad
Dificultad: media — synapse es la imagen propia más grande y es infraestructura crítica de negocio (mensajería, pedidos, SII), así que una regresión duele; pero el cambio es una reescritura de Dockerfile, acotada y reversible con el pin anterior, y no toca infraestructura delicada ni datos irreversibles. La verificación del flujo de negocio es lo que sube el riesgo por encima de baja.
