Rol: pm · Fecha: 2026-10-04 · Sesión: 31bce0d2-7f1f-492d-8c17-6f2ee2b613f3 · Estado: DIVIDIDA

## Objetivo
Que todas las imágenes propias (construidas desde un Dockerfile nuestro) ocupen lo justo, se construyan y suban rápido y compartan bases comunes fijadas por digest, con un inventario y un grafo regenerables de qué base usa cada proyecto. No lo cubren SC-1759 (e2e en CI, rol regression) ni INFRA-400 (colas de CI en k8s-gitops): comparten motivación (build/push lentos) pero no alcance (tamaño e higiene de imágenes).

Repo: k8s-infra-pocharlies (inventario, grafo, bases comunes y guard CI; los Dockerfile se corrigen en el repo de cada imagen, con su PR y su pin de despliegue)

## Por qué se divide
Medido hoy (04-10-2026) con crane + `kubectl get deploy -A -o json`: 100 repos de imágenes propias candidatas (Harbor `homelab/*` y ghcr `pocharlies*`) en uso, 198 referencias en Deployments, repartidas en ~30 repos de código. Un solo CTO no abarca ni un repo ni una semana. Se divide en una hija plataforma (que bloquea a las demás) y cinco hijas de dominio. Cada Dockerfile vive en el repo de su imagen, con su PR y su pin.

## Criterios de aceptación
Son los de la épica; cada uno lo cumple una hija (o el agregado de varias). Comandos verificados hoy contra Harbor.

- [ ] Inventario de todas las imágenes propias (Harbor `homelab/*` y ghcr `pocharlies-org/*` en uso en el clúster): repo y ruta del Dockerfile, imagen base con tag y digest, tamaño comprimido y descomprimido, capas más grandes, fecha del último build y Deployments que la usan. (Hija INFRA-536)
  - Comando: `python3 scripts/image-inventory.py` (script que crea 536) regenera `inventario.md`/`.json`; por imagen, tamaño comprimido = `crane manifest --platform linux/{arch} {img@digest} | jq '[.layers[].size]|add'`, fecha de build = `crane config {img@digest} | jq -r '.created'`, Deployments = `kubectl get deploy -A -o json | jq -r '.items[]|.metadata.namespace as $n|.metadata.name as $d|(.spec.template.spec.containers[]?.image)|select(test("{nombre}"))|"\($n)/\($d)"'`.
  - Salida esperada: tabla con los ~100 candidatos, clasificando propias vs espejos de terceros (redis, onepassword-connect, vllm, searxng, clamav, agentgateway...), cada propia con sus 7 campos.

- [ ] Grafo de dependencias base → imágenes propias (también bases propias intermedias) → proyectos y Deployments, publicado en el repo y regenerable con un script, no hecho a mano. (Hija INFRA-536)
  - Comando: `python3 scripts/image-graph.py` regenera `grafo.md`/`.dot`; `python3 scripts/image-graph.py && git diff --exit-code -- grafo.md` = sin diferencias (determinista).
  - Salida esperada: fichero de grafo en el repo que se regenera idéntico.

- [ ] Bases comunes propuestas y aplicadas donde haya 3 o más consumidores de la misma pila (python-slim+uv, node), fijadas por digest. (Bases: INFRA-536; adopción: 537-541)
  - Comando: `crane manifest harbor.e-dani.com/homelab/base-{pila}@sha256:{digest}` existe; en cada consumidor, `grep -n '^FROM' Dockerfile` apunta a la base por digest.
  - Salida esperada: imágenes base en Harbor fijadas por digest y los Dockerfiles de 3+ consumidores de una pila usándolas.

- [ ] Dockerfiles corregidos: multi-stage donde aplique; ninguna caché de pip/uv/npm/apt en la imagen final (cache mounts de BuildKit o borrado en la misma capa); `.dockerignore`; dependencias antes que código; sin dependencias duplicadas. (Hijas 537-541, cada una en su dominio)
  - Comando: por imagen, `crane export {img@digest} - | tar -tf - | grep -E '(^|/)(\.cache|__pycache__|node_modules/\.cache|\.uv)/'` → vacío; `docker run --rm -i hadolint/hadolint < Dockerfile` → exit 0 sin errores.
  - Salida esperada: ninguna caché en la capa final y hadolint limpio en los Dockerfiles tocados.

- [ ] jarvis-backend sin `/root/.cache` y con un solo OpenCV. (Hija INFRA-537)
  - Comando: `crane export {jarvis-backend@nuevo} - | tar -tf - | grep -c 'root/\.cache'` → 0; `crane export {jarvis-backend@nuevo} - | tar -tf - | grep -iE 'opencv|cv2' | grep -oE 'opencv[a-z0-9._-]*' | sort -u` → una sola familia.
  - Salida esperada: 0 entradas bajo `/root/.cache` y un único OpenCV.

- [ ] Tabla antes/después en la épica (tamaño comprimido, tiempo de build y de push) de las 10 imágenes propias más grandes. Todas bajan. (Agregado de 537-541; la consolida el pm al validar)
  - Comando: por imagen, `crane manifest --platform linux/{arch} {img@antes} | jq '[.layers[].size]|add'` vs `{img@después}`; tiempo de build/push del log del run de CI.
  - Salida esperada: tabla con las 10 mayores; comprimido antes > después en las 10.

- [ ] Ninguna regresión: cada imagen nueva pasa sus tests y su healthcheck, y queda verificada en producción tras su despliegue. (Hijas 537-541)
  - Comando: `kubectl rollout status deploy/{name} -n {ns} --timeout=180s` → "successfully rolled out"; `kubectl get pods -n {ns} -l {selector} -o jsonpath='{.items[*].status.containerStatuses[*].ready}'` → true; tests de CI en verde.
  - Salida esperada: rollout completo, pods ready y tests verdes por imagen.

- [ ] Una comprobación en CI (lint del Dockerfile y tope de tamaño o aviso por crecimiento) que impida que las imágenes nuevas vuelvan a engordar, en los workflows que construyen imágenes. (Guard: INFRA-536; adopción: 537-541)
  - Comando: el workflow reusable de 536 existe en el repo; en cada repo de imagen, `grep -rEl 'image-guard|hadolint' .github/workflows/` lo invoca; una PR de prueba con un Dockerfile que engorda falla o avisa.
  - Salida esperada: el guard corre en los workflows de build y marca crecimiento/lint.

## Restricciones
- GitOps: PR contra el tronco que lee ArgoCD (k8s-infra-pocharlies=`main`; dgx-infra=`master`; synapse/socialmedia/labels = el que lea cada app, frecuentemente `deploy/prod`); nunca merge ni push directo al tronco, siempre PR.
- No cambiar de registry ni de sistema de build (Harbor, ARC, buildkit).
- No arreglar el buildkit degradado de sauvage: es INFRA-475 (Request aparte). Los builds grandes pueden tardar por esto; no es un bloqueo de esta épica.
- Imágenes de terceros que solo consumimos (vLLM, LiteLLM, Harbor, ArgoCD, redis, onepassword-connect, searxng, clamav, agentgateway...): solo aparecen en inventario y grafo, no se tocan.
- Los pesos de modelos y los volúmenes no son imágenes: fuera de alcance.
- Varias imágenes son multi-arch (índice OCI): el inventario y el antes/después resuelven el índice a la plataforma que corre el clúster (arm64 en los Sparks, amd64 en x86/sauvage). Medido hoy: `comfyui` es índice arm64; `synapse` y `jarvis-backend` son manifiesto único.
- Cada Dockerfile corregido va con su PR y su pin de despliegue, verificado en producción (merged no es delivered).
- push x86→OVH lento (~1 MB/s): el antes/después de push se mide, no se promete un umbral fijo; el objetivo es que bajen los MB.

## Trabajo reciente (24 h)
- 03-10-2026, sesión 2a51949b (cwd /home/dibanez/k8s): creó INFRA-474 midiendo jarvis-backend (488 MB comprimida, 677 MB de caché uv en /root/.cache, OpenCV duplicado) y usó crane para exportar/subir la imagen. Es el origen de la épica; el piloto (hija 537) parte de esa medida.
- 04-10-2026, perfil sre-devops (turnos 06:45-14:20): INFRA-475, Request suelta por el buildkitd-amd64 degradado en sauvage (apt a ~30 s/paquete, 19 reinicios). Fuera de alcance aquí, pero ralentiza los builds de las hijas; se cita como riesgo, no como bloqueo.
- 04-10-2026, esta sesión pm: inventario real medido con crane/kubectl — 100 repos propios candidatos, 198 refs en Deployments, `synapse` 581 MB (la mayor propia), `jarvis-backend` 488 MB, `mcp-stdio-pool-bridge` 164 MB (usada por ~15 Deployments). Sin ANALISIS INFRA-474 previo.
- No hay sesión VIVA trabajando en INFRA-474 (`claude-tmux list`: solo hermes-edani-key y hermes-cb-uncensored, ajenas).

## Diseño
Diseñador: no — no hay interfaz de usuario nueva; el entregable es inventario/grafo en Markdown + scripts + plantillas de Dockerfile y un workflow de CI, todo en repos, sin superficie visual que recorrer.

## Historias previstas
La épica se divide en 6 hijas (ver ## Hijas); el tech-lead de cada hija la rompe en historias. Unidades previstas y rol dueño:
- INFRA-536 Plataforma: inventario (developer), grafo (developer), bases comunes construidas y fijadas por digest (devops), guard CI reusable (devops).
- INFRA-537 jarvis piloto: reescribir Dockerfile jarvis-backend/alexa (developer), before/after + pin de despliegue (devops), verificación en producción (qa).
- INFRA-538 dgx-infra: Dockerfiles pesados multi-stage (developer), builds/despliegues (devops), verificación (qa).
- INFRA-539 Skirmshop: Dockerfiles por repo (developer), despliegues (devops), verificación (qa).
- INFRA-540 Synapse+socialmedia: Dockerfiles (developer), despliegues (devops), verificación (qa).
- INFRA-541 MCPs+apps sueltas: mcp-stdio-*-bridge y apps (developer), despliegues (devops), verificación (qa).
- revisión UX: no aplica (sin UI).

## Tamaño
L — 100 imágenes propias candidatas en ~30 repos, inventario+grafo+bases+guard nuevos, tabla antes/después de las 10 mayores y verificación en producción de cada imagen tocada. Se divide en 6 hijas precisamente por esto.

## Dificultad
Dificultad: alta — toca la cadena de build/CI de casi todo el estate (el guard va en los workflows que construyen imágenes), las imágenes más pesadas son de dgx-infra (creative/inference crítico) y synapse (pedidos/mensajería/SII en producción), y ya se atascó antes: el build de jarvis-backend dio 25 min y el push a Harbor caducó varias veces (buildkit degradado, INFRA-475). Una regresión en una imagen de negocio o de inferencia rompe producción.

## Hijas
Orden de arranque (la plataforma bloquea a las demás; el supervisor no lanza una hija con un Blocks abierto):
1. INFRA-536 — Plataforma: inventario, grafo, bases comunes y guard CI (k8s-infra-pocharlies, main). Sin bloqueante: arranca primero.
2. INFRA-537 — Piloto jarvis-backend (jarvis). Bloqueada por 536.
3. INFRA-538 — dgx-infra: imágenes pesadas (dgx-infra, master). Bloqueada por 536.
4. INFRA-539 — Skirmshop (skirmshop-labels + shopify-* + control-panel + picker + brain + rag + skirmbooks). Bloqueada por 536.
5. INFRA-540 — Synapse y socialmedia (synapse, synapse-document-intake, k8s-socialmedia-pocharlies). Bloqueada por 536.
6. INFRA-541 — MCPs compartidos y apps sueltas (mcp-stdio-*-bridge, *-mcp, hermes-agent, blog, cv, ha-dashboard, libreplay, tomorrowland, galan/uriel, web-edani, serpentetool, aurora, tesla*-mcp, opencode-node-ops, agent-jake-browser, bambulab-openclaw, codex-arcade). Bloqueada por 536.

Las hijas 537-541 son paralelizables entre sí una vez hecha 536; no se bloquean entre ellas. La tabla antes/después de las 10 mayores y el "todas bajan" se consolidan al validar la épica (pm) con las medidas de 537-541.
