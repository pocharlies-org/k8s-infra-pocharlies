Rol: pm · Fecha: 2026-09-30 · Sesión: e59328f8-79d9-499c-95af-7f4771a2143f · Estado: LISTO

# INFRA-296 — MCP /workspace: drive_create_file acepta binarios (content_base64) con roundtrip verificado

## Objetivo

`drive_create_file` del MCP /workspace sube ficheros binarios byte-exactos mediante un parámetro opcional `content_base64`, y lo que se sube se vuelve a bajar con `drive_get_file` con el mismo sha256; hoy el shim codifica en UTF-8 el texto base64 y guarda en Drive un fichero corrupto (PDF de 48.918 B convertido en 65.224 B, sesión ses_f171fa8e2ffeajrw1dvQ2mJQjt, 2026-09-28). No solapa con ninguna épica abierta: `drive_trash_file` y la subida multipart por encima de 16 MiB quedan fuera de alcance.

Repo: k8s-agentgateway-pocharlies

- Fichero: `backends/workspace/gws-shim.py` (trunk `origin/main`, HEAD medido `be165d7`). Función `drive_create_file` líneas 1206-1217 (`MediaInMemoryUpload(args.get("content", "").encode("utf-8"), ...)` en la 1210); schema en `TOOLS` líneas 1348-1351 (`required: ["name"]`); constantes `DRIVE_DEFAULT_MAX_BYTES = 4 MiB` y `DRIVE_MAX_BYTES_CEILING = 16 MiB` en 1120-1121; patrón de decodificado ya usado en el mismo fichero para adjuntos de gmail (línea 649, `base64.b64decode(att["content_base64"])`).
- Despliegue: el shim NO viaja en la imagen. El pod `deployment/workspace-mcp` (ns `workspace-mcp`, imagen genérica `harbor.e-dani.com/homelab/mcp-stdio-pool-bridge:v0.1.9`) monta `/mcp/gws-shim.py` desde el ConfigMap `gws-shim-src`, generado desde `backends/workspace/configmap.yaml` por kustomize. Camino: PR contra `main` → merge → ArgoCD app `agentgateway-mcp` (path `k8s/overlays/prod`, `targetRevision: main`) aplica el ConfigMap → el bridge relanza el hijo stdio tras `BACKEND_IDLE_TIMEOUT_MS` (2 min sin uso) y el hijo nuevo lleva el código nuevo, sin roll de pod. Esto corrige el criterio 7 del borrador («imagen del pod actualizada» no es el mecanismo).

## Criterios de aceptación

Variables usadas en los comandos vivos: `WS_TEST_TOKEN_OPERATOR` = token client_credentials del auth-proxy local (`curl -s http://127.0.0.1:8790/healthz` debe responder; se acuña contra Keycloak como hace `clients/agentgateway-auth-proxy.js`, igual que `scripts/test-workspace-identity.py --live`); `WS_TEST_DRIVE_FOLDER` = id de una carpeta de pruebas de Drive de `info@e-dani.com`; `MERGE_SHA` = commit de merge del PR en `main`. Nombres de fichero de test fijados aquí: `backends/workspace/test_drive_create_binary.py` (unitario) y `scripts/test-workspace-drive-binary.py` (smoke vivo).

- [ ] **C1 — Decodificado byte-exacto y precedencia.** Con `content_base64` el shim decodifica (base64 estándar, validación estricta) y sube exactamente esos bytes; con solo `content` sube su UTF-8 como hoy; si llegan ambos gana `content_base64`; base64 inválido devuelve un error claro (texto que nombra `content_base64`) y NO llama a `files().create`. La descripción de la herramienta y del parámetro dicen las tres cosas (binario vía `content_base64`, `content` = texto UTF-8, precedencia).
  - Comando: `cd k8s-agentgateway-pocharlies && python3 -m pytest -q backends/workspace/test_drive_create_binary.py`
  - Salida esperada: `N passed` con 0 failed, incluyendo como mínimo los casos: base64 válido (bytes subidos == bytes originales, comparados por sha256), base64 inválido (error + `files().create` llamado 0 veces), ambos campos (se suben los bytes de `content_base64`), solo `content` con texto no ASCII (se suben sus bytes UTF-8, sin cambio frente a hoy).
  - Comando: `git -C k8s-agentgateway-pocharlies show origin/main:backends/workspace/gws-shim.py | grep -n -A4 '"name": "drive_create_file"'` (tras el merge)
  - Salida esperada: la descripción de `drive_create_file` / de `content_base64` en `TOOLS` menciona que `content_base64` es para binarios y que prevalece sobre `content`.

- [ ] **C2 — parent_folder_id sigue valiendo con binarios.** Un binario subido con `parent_folder_id` queda dentro de esa carpeta.
  - Comando (unitario): mismo `pytest` de C1, caso `content_base64` + `parent_folder_id`.
  - Salida esperada: el `body` pasado a `files().create` contiene `parents: [parent_folder_id]`.
  - Comando (vivo): `WS_TEST_TOKEN_OPERATOR=... WS_TEST_DRIVE_FOLDER=... python3 scripts/test-workspace-drive-binary.py --live`
  - Salida esperada: línea `PASS parent_folder_id` (el `drive_get_file` del fichero creado devuelve `parents` que contiene `WS_TEST_DRIVE_FOLDER`).

- [ ] **C3 — Roundtrip de un PDF real de ~5 MB.** Un PDF válido de ~5 MB generado con Python (cabecera `%PDF-`, stream no compresible, `%%EOF`) se sube con `tools/call drive_create_file` (`content_base64`, `mime_type: application/pdf`, `parent_folder_id: WS_TEST_DRIVE_FOLDER`) y se baja con `tools/call drive_get_file` (`include_content: true`, `max_bytes: 16777216` — el default de 4 MiB no alcanza para 5 MB); el sha256 de `base64.b64decode(content_base64)` es idéntico al del PDF local y `content_bytes` es igual al tamaño local.
  - Comando: `WS_TEST_TOKEN_OPERATOR=... WS_TEST_DRIVE_FOLDER=... python3 scripts/test-workspace-drive-binary.py --live`
  - Salida esperada: `PASS roundtrip size=LOCAL_BYTES sha256=HASH_LOCAL == HASH_DRIVE` con `LOCAL_BYTES` entre 4.500.000 y 5.500.000 y los dos hashes iguales; exit code 0. Un `MISMATCH` o un tamaño distinto es NO CUMPLE.

- [ ] **C4 — Límite coherente con la descarga: hasta 16 MiB.** Bytes decodificados de `content_base64` de hasta `DRIVE_MAX_BYTES_CEILING` (16.777.216 B) se aceptan; por encima, error claro que nombra el límite (`16777216`) sin truncar y sin crear fichero. `content` (texto) conserva su comportamiento actual.
  - Comando (unitario): mismo `pytest` de C1, casos 16.777.216 B y 16.777.217 B.
  - Salida esperada: 16.777.216 B → `files().create` llamado una vez con exactamente esos bytes; 16.777.217 B → respuesta con error que contiene `16777216` y `files().create` llamado 0 veces.
  - Comando (vivo): `python3 scripts/test-workspace-drive-binary.py --live` (caso sobre-límite: ~16,5 MiB).
  - Salida esperada: línea `PASS over-limit error` — la respuesta de `tools/call` trae el error con `16777216` y no trae `file`/`id`.

- [ ] **C5 — El parámetro aparece en tools/list.** En vivo, tras el sync, `tools/list` de https://agentgateway-mcp.e-dani.com/workspace devuelve `drive_create_file` con `inputSchema.properties.content_base64` (tipo `string`) y `required` sigue siendo `["name"]`.
  - Comando: `python3 scripts/test-workspace-drive-binary.py --live` (paso `tools/list`) o JSON-RPC `initialize` + `tools/list` con `Authorization: Bearer $WS_TEST_TOKEN_OPERATOR` y `jq '.result.tools[] | select(.name=="drive_create_file") | .inputSchema'`
  - Salida esperada: `PASS tools/list content_base64` / el objeto contiene `"content_base64": {"type": "string", ...}` y `"required": ["name"]`.

- [ ] **C6 — Tests en el repo y conectados al CI.** Existe el unitario `backends/workspace/test_drive_create_binary.py` (sin llamadas reales a Google: `googleapiclient` y `_service` stubbeados, como `test_gws_identity.py`) y el smoke vivo `scripts/test-workspace-drive-binary.py --live` (sube el PDF generado a la carpeta de pruebas, comprueba hash, prueba el sobre-límite y manda a la papelera lo que creó al terminar, también si un paso falla). El unitario corre en `.github/workflows/ci.yml` (hoy el paso pytest solo cubre `k8s/base/atlassian-mcp`).
  - Comando: `cd k8s-agentgateway-pocharlies && grep -n 'backends/workspace' .github/workflows/ci.yml`
  - Salida esperada: al menos una línea `python3 -m pytest ... backends/workspace...` en un paso del job de CI.
  - Comando: `gh pr checks PR_NUMBER -R pocharlies-org/k8s-agentgateway-pocharlies`
  - Salida esperada: el job que ejecuta ese paso en `pass` (log con `N passed` de `test_drive_create_binary.py`).
  - Comando: `python3 scripts/test-workspace-drive-binary.py --live` (final)
  - Salida esperada: línea `PASS cleanup trashed=IDS` con todos los ids creados en la ejecución; después, en Drive, esos ids tienen `trashed: true` (comprobado por `files().get`/`files().list` con `trashed=false`, NO con `drive_search`, que tiene caché de varios minutos — GOTCHA del brain 2026-09-29).

- [ ] **C7 — Desplegado por GitOps y visible en el pod.** El cambio llega por PR contra `main` mergeado; ArgoCD `agentgateway-mcp` está Synced a `MERGE_SHA` y Healthy; el fichero montado en el pod es byte-igual al del trunk.
  - Comando: `kubectl get application -n argocd agentgateway-mcp -o jsonpath='{.status.sync.status} {.status.sync.revision} {.status.health.status}{"\n"}'`
  - Salida esperada: `Synced MERGE_SHA Healthy`.
  - Comando: `kubectl -n workspace-mcp exec deploy/workspace-mcp -- sha256sum /mcp/gws-shim.py` y `git -C k8s-agentgateway-pocharlies show origin/main:backends/workspace/gws-shim.py | sha256sum`
  - Salida esperada: los dos hashes idénticos, y distintos del anterior `ccbc6570...fc1d`; `kubectl -n workspace-mcp exec deploy/workspace-mcp -- grep -c content_base64 /mcp/gws-shim.py` devuelve un número mayor que el de hoy.
  - Nota: si el hijo stdio aún corre el código viejo (menos de 2 min de inactividad), C5 falla hasta que se relanza; no se reinicia el pod a mano para forzarlo.

- [ ] **C8 — Contratos: cambio aditivo, sin entrada nueva.** Parámetro opcional = aditivo: ni `CONTRACTS.yaml` ni ninguna entrada `.vN` cambian, y el commit no lleva trailer `Contract-Change`. /chat-workspace (contrato `mcp.chat-workspace.route`) sirve el MISMO shim (`scripts/check-mcp-coverage.py` hace `EXPECTED["chat-workspace"] = EXPECTED["workspace"]`, línea 641) y refleja el cambio sin acción extra.
  - Comando: `git -C k8s-agentgateway-pocharlies diff --stat origin/main~1..MERGE_SHA -- CONTRACTS.yaml` (o `gh pr diff PR_NUMBER --name-only | grep -c CONTRACTS.yaml`)
  - Salida esperada: vacío / `0`.
  - Comando: `cd k8s-agentgateway-pocharlies && python3 scripts/check-mcp-coverage.py`
  - Salida esperada: exit code 0, sin diferencias nuevas para `workspace` ni `chat-workspace`.

## Restricciones

- Sin camino manual directo al clúster: nada de `kubectl apply/edit/patch` del ConfigMap, `kubectl cp` del shim ni reinicio a mano del pod. Solo PR → merge → ArgoCD.
- No romper a los consumidores de `content`: su semántica (texto UTF-8, default `text/plain`) no cambia; `required` sigue siendo `["name"]`; la respuesta (`user`, `created`, `file`) mantiene su forma.
- No tocar `CONTRACTS.yaml` (C8).
- El smoke vivo manda a la papelera todo lo que crea al terminar, pase o falle; solo en la carpeta `WS_TEST_DRIVE_FOLDER`.
- No usar el bypass `kubectl exec` + `token.json` para hablar con Drive (ni para subir, ni para verificar, ni para limpiar). Leer `/mcp/gws-shim.py` con `kubectl exec ... sha256sum`/`grep` para C7 sí vale: no toca credenciales.
- Riesgo conocido, no criterio: 16 MiB decodificados son ~21,3 MiB de base64 dentro de una línea JSON-RPC (stdio → bridge → HTTP → gateway, `requestTimeout` 120 s, límite del pod 1Gi). C4 se verifica en unitario en el borde exacto y en vivo solo por encima; si qa prueba una subida viva cerca de 16 MiB y el transporte falla, es un hallazgo para el CTO, no se sube ni se baja el límite en esta épica.
- Limpieza sin `drive_trash_file` (fuera de alcance): el smoke manda a la papelera por un camino autorizado que no sea el bypass anterior (p. ej. `files().update(trashed=true)` con las credenciales del propio test si las tiene, o el conector de Drive de la sesión si cubre la cuenta). Si ningún camino autorizado alcanza la cuenta, es `DUDA:` del developer en `50-entrega.md`, no un atajo.

## Trabajo reciente (24 h)

- 2026-09-30 (PM): trunk `origin/main` = `be165d7`; `git ls-remote --symref origin HEAD` → `refs/heads/main`; ArgoCD `agentgateway-mcp` Synced Healthy, `targetRevision: main`, path `k8s/overlays/prod`.
- 2026-09-30 (PM): `sha256sum /mcp/gws-shim.py` en el pod == sha256 de `origin/main:backends/workspace/gws-shim.py` (`ccbc6570...fc1d`): lo desplegado es el trunk.
- 2026-09-30 (PM, sesión e59328f8): confirmado en el trunk que `drive_create_file` (1206-1217) solo acepta `content`/`mime_type`/`parent_folder_id` y codifica en UTF-8; `drive_get_file` ya devuelve `content_base64` para binarios (1202) y ya rechaza por encima de `max_bytes` con error claro; `deployment/workspace-mcp` y `configmap/gws-shim-src` existen en ns `workspace-mcp`.
- 2026-09-30 (PM): `git log --since=36h origin/main -- backends/workspace/` vacío; única PR abierta en el repo es #78 (trello), no relacionada; sin sesiones vivas en esto; ninguna épica abierta solapa.
- 2026-09-29 (brain, GOTCHA): `drive_search` tiene caché de varios minutos; para el estado real de Drive, `files().list` con `trashed=false`.
- 2026-09-28 (sesión ses_f171fa8e2ffeajrw1dvQ2mJQjt): incidente origen — PDF de 48.918 B guardado como 65.224 B (texto base64 doble-codificado), sha256 MISMATCH.

## Diseño

Diseñador: no — cambio de API/schema MCP, sin interfaz de usuario nueva ni cambiada

## Historias previstas

- **S1 — código + schema + unitario en CI** (dueño: developer): `content_base64` en `drive_create_file` (decodificado estricto, precedencia, límite 16 MiB antes de subir, error claro), schema y descripciones en `TOOLS`, `backends/workspace/test_drive_create_binary.py`, paso en `.github/workflows/ci.yml`, y el script `scripts/test-workspace-drive-binary.py --live`. Cubre C1, C2 (unitario), C4 (unitario), C6, C8. Entrega: PR contra `main` con CI en verde + `50-entrega.md`.
- **S2 — despliegue GitOps y verificación en vivo** (dueño: devops): tras el merge, ArgoCD Synced a `MERGE_SHA`, hash del fichero montado == trunk, `tools/list` en vivo con `content_base64` (/workspace y /chat-workspace). Cubre C5, C7. Depende de S1.
- **S3 — smoke vivo** (dueño: qa): `scripts/test-workspace-drive-binary.py --live` con PDF generado de ~5 MB (roundtrip sha256), sobre-límite por encima de 16 MiB (error, sin fichero), `parent_folder_id`, papelera al terminar comprobada con `files().list trashed=false`. Cubre C2 (vivo), C3, C4 (vivo), C6 (limpieza). Depende de S2. `70-qa.md` con la salida real.

Orden: S1 → S2 → S3 (cada una necesita lo que entrega la anterior).

## Tamaño

S — un solo fichero de código (`gws-shim.py`, ~20 líneas de lógica más schema), un unitario, un script de smoke y una línea de CI en un único repo; el patrón de decodificado ya existe en el mismo fichero y el despliegue es un ConfigMap que ArgoCD ya gestiona, sin imagen nueva.

## Dificultad

Dificultad: media — funcionalidad nueva con lógica dentro de un solo repo, sin decisión de arquitectura; un revert la deshace.
