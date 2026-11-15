Rol: pm · Fecha: 2026-10-04 · Sesión: 31bce0d2-7f1f-492d-8c17-6f2ee2b613f3 · Estado: LISTO

## Objetivo
Construir en k8s-infra-pocharlies la plataforma de la que dependen las demás hijas de INFRA-474: un inventario regenerable de todas las imágenes propias, el grafo base→imágenes→Deployments, las imágenes base comunes fijadas por digest y un guard reutilizable de CI (lint de Dockerfile + aviso de crecimiento de tamaño). Es la hija que bloquea a 537-541: sin inventario ni bases, la corrección de Dockerfiles no arranca.

Repo: k8s-infra-pocharlies (tronco main)

## Criterios de aceptación
- [ ] Inventario regenerable por script de todas las imágenes propias (Harbor `homelab/*` y ghcr `pocharlies-org/*` en uso en el clúster), con: repo y ruta del Dockerfile, imagen base con tag y digest, tamaño comprimido y descomprimido, capas más grandes, fecha del último build y Deployments que la usan; y clasifica propias vs espejos de terceros.
  - Comando: `python3 scripts/image-inventory.py` genera `docs/images/inventario.md` (+`.json`). Por imagen, el script usa (verificado hoy): `crane manifest --platform linux/{arch} {img@digest} | jq '[.layers[].size]|add'` (comprimido; si `.manifests` existe es índice multi-arch y se resuelve a la plataforma del clúster), `crane config {img@digest} | jq -r '.created'` (fecha build), `kubectl get deploy -A -o json | jq -r '...select(.image|test("{nombre}"))...'` (Deployments). Tamaño descomprimido: `docker pull {img}` + `docker image inspect --format '{{.Size}}'` o suma de `crane export` por plataforma.
  - Salida esperada: tabla con los ~100 candidatos medidos hoy, cada propia con sus 7 campos, y una columna/clase "espejo de tercero" para redis, onepassword-connect, vllm-*, searxng, clamav, agentgateway, etc.

- [ ] Grafo de dependencias base → imágenes propias (también bases propias intermedias) → proyectos y Deployments, publicado en el repo y regenerable con un script, no hecho a mano.
  - Comando: `python3 scripts/image-graph.py` genera `docs/images/grafo.md` y `grafo.dot`; `python3 scripts/image-graph.py && git diff --exit-code -- docs/images/grafo.md` → sin diferencias (determinista).
  - Salida esperada: grafo en el repo (Markdown + .dot) que se regenera idéntico; los nodos base son las imágenes base (propias y de terceros) y las hojas son Deployments.

- [ ] Bases comunes propuestas y aplicables donde haya 3 o más consumidores de la misma pila (p. ej. python-slim+uv, node), construidas, subidas a Harbor y fijadas por digest.
  - Comando: el inventario agrupa por pila y lista consumidores; `docker build -t harbor.e-dani.com/homelab/base-{pila}:{tag} bases/{pila}/ && crane push ... harbor.e-dani.com/homelab/base-{pila}:{tag}`; `crane digest harbor.e-dani.com/homelab/base-{pila}:{tag}` → sha256 fijado en `docs/images/bases.md`.
  - Salida esperada: al menos las bases de las pilas con 3+ consumidores (python-slim+uv, node) existen en Harbor por digest y `bases.md` lista cada base con sus consumidores.

- [ ] Guard reutilizable de CI (lint del Dockerfile con hadolint + tope de tamaño o aviso por crecimiento) que los workflows que construyen imágenes puedan llamar.
  - Comando: un workflow `reusable-image-guard.yml` (workflow_call) en k8s-infra-pocharlies (o en k8s-gitops-pocharlies junto a reusable-ci.yml, decisión del tech-lead) que corre `docker run --rm -i hadolint/hadolint < Dockerfile` y compara `crane manifest {img} | jq '[.layers[].size]|add'` contra una línea base en `docs/images/sizes-baseline.json`, fallando o avisando si crece.
  - Salida esperada: el workflow existe, es invocable por `uses:` desde otro repo, y una PR de prueba con un Dockerfile que engorda o con un error hadolint lo detecta.

## Restricciones
- GitOps: PR contra `main` de k8s-infra-pocharlies; nunca merge ni push directo al tronco.
- hadolint no está instalado en local: el guard lo corre vía imagen docker (`hadolint/hadolint`) o action en CI.
- Varias imágenes son índice multi-arch (comfyui es arm64): el inventario y el guard resuelven el índice a la plataforma que corre el clúster (arm64 Sparks, amd64 x86/sauvage).
- No corregir Dockerfiles de imágenes concretas: eso es de las hijas 537-541. Esta hija solo produce inventario, grafo, bases y guard.
- No tocar el buildkit degradado (INFRA-475).
- Las bases comunes se proponen y construyen aquí; adoptarlas en cada Dockerfile es de las hijas de dominio.

## Trabajo reciente (24 h)
- 04-10-2026, sesión pm (INFRA-474): medido el inventario real con crane/kubectl — 100 repos propios candidatos, 198 refs en Deployments; `synapse` 581 MB (manifiesto único, 16 capas), `jarvis-backend` 488 MB (11 capas, mayor 243 MB), `mcp-stdio-pool-bridge` 164 MB amd64 (usada por ~15 Deployments), `comfyui` índice OCI arm64. crane y skopeo operativos contra Harbor (HTTP 200, creds en ~/.docker/config.json).
- 03-10-2026, sesión 2a51949b: origen de INFRA-474, midió jarvis-backend con crane.
- 04-10-2026, INFRA-475 (sre-devops): buildkit degradado en sauvage, fuera de alcance pero ralentiza builds.
- Sin ANALISIS INFRA-474 previo; `.company/specs/INFRA-283/inventario.md` es de CronJobs, no de imágenes (no hay inventario de imágenes previo).

## Diseño
Diseñador: no — sin interfaz de usuario; el entregable es scripts + Markdown (inventario, grafo, bases) + un workflow de CI, todo en repo, sin superficie visual.

## Historias previstas
- Inventario regenerable (developer): script + `inventario.md`/`.json` con los 7 campos y clasificación propia/tercero.
- Grafo regenerable (developer): script + `grafo.md`/`.dot` determinista.
- Bases comunes (devops): Dockerfiles de bases python-slim+uv y node, build+push a Harbor, fijado por digest, `bases.md` con consumidores.
- Guard CI reusable (devops): `reusable-image-guard.yml` (hadolint + size-baseline) invocable por los repos de imagen.
- (qa verifica que el inventario y el grafo se regeneran idénticos y que el guard detecta un Dockerfile que engorda.)

## Tamaño
M — un repo, scripts nuevos contra crane/kubectl/Harbor API, dos bases comunes y un workflow reusable; sin despliegues de negocio. Acotado y revertible.

## Dificultad
Dificultad: media — no toca producción (son scripts, docs, bases y un guard opt-in), pero define el método y las bases que siguen las otras cinco hijas, y el inventario debe resolver bien el multi-arch y clasificar propias vs espejos (un error aquí propaga mal las prioridades). Reversible: todo vive en k8s-infra-pocharlies.
