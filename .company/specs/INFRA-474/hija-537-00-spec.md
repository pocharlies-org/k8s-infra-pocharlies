Rol: pm · Fecha: 2026-10-04 · Sesión: 31bce0d2-7f1f-492d-8c17-6f2ee2b613f3 · Estado: LISTO

## Objetivo
Aligerar jarvis-backend (y jarvis-alexa si comparte base/Dockerfile) del repo jarvis: es el piloto que valida el método de INFRA-474 con el caso que lo destapó. Sin /root/.cache de uv, con un solo OpenCV, multi-stage, sobre la base común python+uv fijada por digest que produce INFRA-536, con .dockerignore y dependencias antes que código; medido antes/después y verificado en producción.

Repo: jarvis (pocharlies-org/jarvis; el caso se midió en jarvis#24, imagen 20261004-quick-ack-9588e44, 488 MB comprimida)

## Criterios de aceptación
- [ ] jarvis-backend final sin /root/.cache y con un solo OpenCV.
  - Comando: `crane export {jarvis-backend@nuevo-digest} - | tar -tf - | grep -c 'root/\.cache'` → `0`; `crane export {jarvis-backend@nuevo-digest} - | tar -tf - | grep -iE 'opencv|cv2' | grep -oE 'opencv[a-z0-9._-]*' | sort -u` → una sola familia (no `opencv-python-headless` y `opencv-contrib-python` a la vez).
  - Salida esperada: 0 entradas bajo /root/.cache y un único paquete OpenCV.

- [ ] Dockerfile multi-stage, .dockerignore, dependencias antes que código, sin caché de pip/uv/apt en la capa final (cache mount de BuildKit o borrado en la misma capa), sobre la base común python+uv fijada por digest.
  - Comando: `test -f .dockerignore && echo OK`; `docker run --rm -i hadolint/hadolint < Dockerfile` → exit 0 sin errores; `grep -n '^FROM' Dockerfile` → la base común por `@sha256:`; `grep -n 'COPY' Dockerfile` muestra deps (pyproject/uv.lock) copiados antes que el código.
  - Salida esperada: .dockerignore presente, hadolint limpio, FROM por digest de la base de 536, capas de dependencias antes que las de código.

- [ ] Antes/después medido: el tamaño comprimido baja respecto a los 488 MB de 20261004-quick-ack-9588e44.
  - Comando: antes `crane manifest harbor.lan.e-dani.com/homelab/jarvis-backend@sha256:2b70ae296aee1418f4dabc9669e27ac3e8a10b1257b3ff9705ef2335db012ba7 | jq '[.layers[].size]|add'` → 488317099; después el mismo comando con el nuevo digest → menor.
  - Salida esperada: comprimido después < 488317099 bytes; la fila entra en la tabla antes/después de la épica.

- [ ] Sin regresión: jarvis-backend pasa sus tests y su healthcheck y queda verificado en producción tras su pin de despliegue.
  - Comando: `kubectl rollout status deploy/jarvis-backend -n jarvis --timeout=180s` → "successfully rolled out"; `kubectl get pods -n jarvis -l app=jarvis-backend -o jsonpath='{.items[*].status.containerStatuses[*].ready}'` → true; tests de CI del repo jarvis en verde.
  - Salida esperada: rollout completo, pod ready, tests verdes, y el endpoint de jarvis responde en producción.

- [ ] El guard de CI de INFRA-536 queda conectado al workflow que construye jarvis-backend.
  - Comando: `grep -rEl 'image-guard|hadolint' .github/workflows/` en el repo jarvis → el workflow de build invoca el reusable de 536.
  - Salida esperada: el build de jarvis-backend corre el lint + check de tamaño.

## Restricciones
- Bloqueada por INFRA-536: necesita la base común python+uv por digest y el guard reusable antes de reescribir el Dockerfile.
- GitOps: PR contra el tronco del repo jarvis; el pin de despliegue va en su repo de manifiestos (k8s-jarvis-pocharlies o el que lea ArgoCD); nunca push directo al tronco.
- El build/push puede ir lento por el buildkit degradado (INFRA-475): no es bloqueo de esta hija, pero medir el tiempo de build/push para la tabla.
- Si jarvis-alexa no comparte base ni Dockerfile con jarvis-backend, queda fuera (decisión del tech-lead al abrir la hija).
- No cambiar la funcionalidad de jarvis-backend: solo higiene de imagen. Una regresión funcional rompe el asistente de hogar.

## Trabajo reciente (24 h)
- 03-10-2026, sesión 2a51949b: midió jarvis-backend (488 MB, 677 MB de caché uv en /root/.cache, OpenCV duplicado ~290 MB, 478 MB en /usr/lib/x86_64-linux-gnu de GL+ffmpeg) y creó INFRA-474. El push a Harbor caducó varias veces (capas de 243 MB y 89 MB a ~1 MB/s) y el build en k8s-buildkit se cortó a los 25 min.
- 04-10-2026, INFRA-475 (sre-devops): buildkitd-amd64 degradado en savage (apt a ~30 s/paquete, 19 reinicios) — es la causa del build lento; Request aparte, fuera de alcance.
- 04-10-2026, sesión pm: verificado el tamaño actual con crane — `jarvis-backend@sha256:2b70ae…` = 488317099 bytes comprimido, 11 capas, mayor 243694825. Es el "antes" de la tabla.
- Imagen en uso: `kubectl get deploy -n jarvis` → jarvis-backend corre `harbor.lan.e-dani.com/homelab/jarvis-backend:20261004-quick-ack-9588e44@sha256:2b70ae…`.

## Diseño
Diseñador: no — sin interfaz de usuario; es una reescritura de Dockerfile y su despliegue.

## Historias previstas
- Reescribir Dockerfile de jarvis-backend (developer): multi-stage, base común por digest, uv sin caché (cache mount o --no-cache), un solo OpenCV, .dockerignore, deps antes que código.
- Build + pin de despliegue + before/after (devops): construir, subir a Harbor, medir comprimido antes/después, pinear en el repo de manifiestos.
- Verificación en producción (qa): rollout, healthcheck, endpoint de jarvis responde, tests verdes.
- Conectar el guard CI (devops): el workflow de build de jarvis invoca el reusable de 536.

## Tamaño
S — un repo, una imagen (dos si jarvis-alexa comparte), reescritura de Dockerfile + un despliegue. Acotado.

## Dificultad
Dificultad: media — el arreglo en sí es una reescritura de Dockerfile (claro y reversible), pero jarvis-backend es el caso que dio el build de 25 min y el push que caducaba: hay que medir de verdad el antes/después con el buildkit degradado (INFRA-475) de fondo, y una regresión funcional rompe el asistente de hogar en producción. No es alta porque el cambio es una imagen, reversible con el pin anterior.
