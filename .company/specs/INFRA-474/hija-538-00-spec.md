Rol: pm · Fecha: 2026-10-04 · Sesión: 31bce0d2-7f1f-492d-8c17-6f2ee2b613f3 · Estado: LISTO

## Objetivo
Aligerar las imágenes propias de dgx-infra, que son las más pesadas del estate (torch, GL, ffmpeg, modelos) y por tanto las que más MB ahorran. Aplicar bases comunes, multi-stage, sin cachés en la capa final, .dockerignore y dependencias antes que código; antes/después medido por imagen y verificado en producción.

Repo: dgx-infra (tronco master)

Imágenes del dominio (lista definitiva la fija el inventario de INFRA-536): comfyui, comfyui-rtx, krea2-trainer, dgx-infra/omnivoice, dgx-infra/omnivoice-audio, dgx-infra/voicelab, dgx-infra/ofimatica, dgx-dashboard-backend, dgx-dashboard-ui, partcrafter-api, trellis2-api, weight-resolver, dgx-messages, bge-m3-embedding, stt-turbo, dgx-infra/chat.

## Criterios de aceptación
- [ ] Cada imagen propia de dgx-infra: Dockerfile multi-stage donde aplique, sin caché de pip/uv/npm/apt en la capa final, .dockerignore, dependencias antes que código, sin dependencias duplicadas.
  - Comando: por imagen, `crane export {img@nuevo} - | tar -tf - | grep -E '(^|/)(\.cache|__pycache__|node_modules/\.cache|\.uv)/'` → vacío; `docker run --rm -i hadolint/hadolint < {Dockerfile}` → exit 0 sin errores; `test -f .dockerignore`.
  - Salida esperada: ninguna caché en la capa final, hadolint limpio y .dockerignore en cada imagen tocada.

- [ ] Antes/después con crane manifest resolviendo el índice multi-arch a la plataforma que corre el clúster: el tamaño comprimido baja en todas las tocadas; las de dgx-infra que estén entre las 10 propias más grandes entran en la tabla antes/después de la épica.
  - Comando: `crane manifest {img@antes}` → si `.manifests` existe es índice: `crane manifest --platform linux/arm64 {img@antes} | jq '[.layers[].size]|add'` (comfyui es arm64); si es manifiesto único, `crane manifest {img} | jq '[.layers[].size]|add'`. Repetir con el digest nuevo → menor.
  - Salida esperada: comprimido después < antes en cada imagen; las mayores (comfyui, bge-m3, stt-turbo, omnivoice, dgx-dashboard) con su fila en la tabla de la épica.

- [ ] Bases comunes adoptadas donde haya 3 o más consumidores de la misma pila, fijadas por digest.
  - Comando: `grep -n '^FROM' {Dockerfile}` → la base común de 536 por `@sha256:` en las imágenes de la misma pila (p. ej. las python+torch que comparten base).
  - Salida esperada: los Dockerfiles de 3+ consumidores de una pila usan la base común por digest.

- [ ] Sin regresión: cada imagen nueva pasa sus tests y su healthcheck y queda verificada en producción tras su pin.
  - Comando: `kubectl rollout status deploy/{name} -n {ns} --timeout=300s` → "successfully rolled out"; `kubectl get pods -n {ns} -l {selector} -o jsonpath='{.items[*].status.containerStatuses[*].ready}'` → true; tests de CI de dgx-infra en verde. Para comfyui/omnivoice/voicelab, comprobar además que el servicio responde (no solo el pod ready).
  - Salida esperada: rollout completo, pods ready, tests verdes y el servicio (creative/inference) responde en producción.

- [ ] Guard de CI conectado al workflow que construye las imágenes de dgx-infra.
  - Comando: `grep -rEl 'image-guard|hadolint' .github/workflows/` en dgx-infra → el/los workflows de build invocan el reusable de 536.
  - Salida esperada: el build de las imágenes de dgx-infra corre lint + check de tamaño.

## Restricciones
- Bloqueada por INFRA-536: necesita el inventario (lista y ranking), las bases comunes por digest y el guard reusable.
- GitOps: PR contra `master` de dgx-infra (tronco que lee ArgoCD); cada pin de despliegue en su overlay; nunca push directo al tronco.
- Multi-arch: comfyui y otras son índice OCI (arm64 en los Sparks). Medir SIEMPRE con `--platform linux/arm64` (o la plataforma real del Deployment), no con el índice crudo (da `.layers` null).
- El buildkit degradado (INFRA-475) ralentiza los builds grandes (torch/modelos): medir el tiempo, no es bloqueo; si un build no acaba por infra, citar INFRA-475.
- Los perfiles de cómputo de los Sparks son exclusivos: leer el ConfigMap `gpu-arbiter-state` (ns comfyui) antes de crear cualquier carga de build/prueba en gx10-ec3d/nvidia-dgx; con `effective_mode: llm-tp` no cabe nada más.
- Los pesos de modelos y los volúmenes no son imágenes: fuera. vllm-openai, vllm-omni y otros de terceros que solo se consumen: fuera (solo inventario/grafo).
- dgx-infra es crítico (creative + inference + dashboard): una regresión rompe ComfyUI/Krea2, voz, el dashboard o la inferencia. Verificar el servicio, no solo el pod.

## Trabajo reciente (24 h)
- 04-10-2026, sesión pm: medido con crane — `comfyui:ci-c2c03c4…` es índice OCI arm64 (no amd64); `synapse` 581 MB y `jarvis-backend` 488 MB son las mayores propias medidas (no son de dgx-infra, pero marcan el listón de la tabla). dgx-infra tiene las imágenes más pesadas por torch/GL/modelos.
- 04-10-2026, INFRA-475 (sre-devops): buildkitd-amd64 degradado en sauvage — afecta a los builds grandes de dgx-infra; Request aparte.
- 03-10-2026, sesión 2a51949b: origen de INFRA-474 (jarvis-backend).
- Sin sesión VIVA en dgx-infra sobre esto. SC-1759 (e2e en CI) toca dgx-infra pero son tests e2e, no tamaño de imagen: sin solape.

## Diseño
Diseñador: no — sin interfaz de usuario nueva; son Dockerfiles y sus despliegues.

## Historias previstas
- Dockerfiles pesados multi-stage (developer): por imagen (comfyui, omnivoice, voicelab, ofimatica, dgx-dashboard, bge-m3, stt-turbo, partcrafter, trellis, weight-resolver, dgx-messages, krea2-trainer, chat), multi-stage + sin caché + deps antes que código + base común donde aplique.
- Builds y despliegues (devops): construir (arm64/amd64 según nodo), subir a Harbor, pinear, antes/después medido.
- Verificación en producción (qa): rollout + healthcheck + el servicio creative/inference responde.
- Guard CI (devops): conectar el reusable de 536 a los workflows de build de dgx-infra.

## Tamaño
L — ~16 imágenes pesadas en un monorepo crítico, builds grandes y lentos (torch/modelos), multi-arch, y verificación de servicio en producción por imagen. Probablemente haya que secuenciarlo en varias oleadas; si al arrancar supera una semana, el tech-lead lo parte.

## Dificultad
Dificultad: alta — dgx-infra es creative/inference crítico (ComfyUI, Krea2, voz, dashboard, embeddings), las imágenes son enormes y multi-arch, el build compartido va degradado (INFRA-475) y los builds pueden no acabar, y los Sparks tienen perfil de cómputo exclusivo (gpu-arbiter-state) que hay que respetar al probar. Una regresión aquí tumba servicios de GPU en producción.
