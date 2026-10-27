Rol: pm · Fecha: 2026-09-21T08:25:22+00:00 · Sesión: 05c41e7d-bde0-4580-bf8e-2262a19f9590 · Estado: FALTA INFO

# INFRA-2 — chat: imagen derivada con spaCy en_core_web_sm horneado (lectura de Excel en Open WebUI)

## Objetivo
Restaurar la subida de .xlsx en chat.e-dani.com horneando el modelo spaCy `en_core_web_sm` en una imagen derivada de Open WebUI, publicada en Harbor y fijada por digest. **El trabajo ya está entregado y verificado en producción** (PR 261 de dgx-infra, mergueado el 2026-09-05; producción pinneada por digest hoy mismo); no queda nada que ejecutar. La épica es el registro de ese trabajo, igual que su gemela INFRA-95 ("Open WebUI y los .xlsx: la causa era la descarga de spaCy… arreglado horneando el modelo en la imagen", también en Backlog). Se propone cerrar ambas como ya entregadas — decisión de Dani, en `## Pregunta para Dani`.

Repo: dgx-infra

## Criterios de aceptación
Los cinco del alcance de la épica, remedidos por la PM el 2026-09-21 (todos ya CUMPLE — no hay nada que construir):

- [x] PR 261 (feat/chat-unstructured-toolbox contra master) mergeado — comando: `gh pr view 261 --repo pocharlies-org/dgx-infra --json state,mergedAt,mergeCommit` — salida medida hoy: `state: MERGED`, `mergedAt: 2026-09-05T09:04:47Z`, merge commit `dd51911be66088cae452e2efd3b08204acf28517`.
- [x] Producción apunta a la imagen derivada por digest, sin ventana de imagen inexistente — comando: `kubectl get deploy -n chat chat -o jsonpath='{.spec.template.spec.containers[*].image}'` — salida medida hoy: `harbor.lan.e-dani.com/homelab/dgx-infra/chat:ci-c2f791a3770fc559aab862c78ed93ccf5df41054@sha256:0f13e24546b7ff16c41a60ae4aaddbb0ea12f7bf7e108197d9111f543c22aec5`; pod `chat-6cf7bdc854-zb4nd` 2/2 Running 3d5h.
- [x] Git (master) con el mismo digest + `imagePullSecrets: harbor-pull` — comando: `git show origin/master:k8s/apps/chat/deployment.yaml | grep -nE 'image:|imagePullSecrets|harbor-pull'` (en dgx-infra tras fetch) — salida medida hoy: digest `sha256:0f13e245…` en líneas 112 y 137, `imagePullSecrets` → `harbor-pull` en líneas 71-72 (servido por ExternalSecret desde Vault).
- [x] `spacy.load('en_core_web_sm')` funciona dentro del pod sin salida a WAN — evidencia: SC-281 (Fase 3) Done con la salida pegada. La PM no puede re-medirlo: `kubectl exec -n chat deploy/chat -- python3 -c "import spacy; spacy.load('en_core_web_sm')"` está fuera de su mapa de permisos (denegado el 2026-09-17 y hoy).
- [x] Extremo a extremo con .xlsx real — evidencia: SC-332 Done (2026-09-07, verificación viva de subida de .xlsx en chat.e-dani.com) e INFRA-70 Done (2026-09-15, QA de generación de .xlsx). Cierre E2E declarado fuera de la cadena desde el principio (lo hacía el operador, que lo hizo).

## Restricciones
- No se abre la NetworkPolicy `chat-default-deny` (aislamiento intencional y documentado). No se cambian superficies observables: sin contratos, rutas ni esquemas afectados.
- GitOps: cualquier cambio futuro sobre chat va por PR a `master` de dgx-infra (eso lee ArgoCD, app `chat`), nunca push directo.
- Nada de descargas de modelos en runtime; la imagen es reproducible por digest.

## Trabajo reciente (24 h)
- Nada en 24 h que afecte a este plan. Radar: la única sesión viva en este repo es esta misma sesión de plan; la otra activa de 24 h (c9f2ceaf) planifica INFRA-1, ajena. Brain: ningún hallazgo nuevo sobre spaCy/xlsx/chat en 24 h — los hits son el propio encargo original (2026-09-05/08, sesiones ff6cad10, 4401e58d, 740affc0, 7534ed14, 14a87663) y INFRA-40 (generación de .xlsx, épica aparte ya cerrada, que citó este patrón como precedente).
- Terreno verificado hoy por la PM: producción sigue pinneada al mismo digest (criterios de arriba, remedidos en vivo). Adyacente, no en alcance: INFRA-96 (cerrar OutOfSync cosmético del ExternalSecret harbor-pull) sigue abierta y es otra épica.

## Historias previstas
Ninguna — no hay trabajo que despachar. Si Dani responde que no se cierre, la única historia posible sería "re-verificar y cerrar" (rol: pm), y se reescribiría este spec a partir de su respuesta.

## Tamaño
S — cero ejecución: verificación ya realizada y remedida; la única acción pendiente es administrativa (cerrar la épica, y su gemela INFRA-95).

## Pregunta para Dani
INFRA-2 está entregada íntegramente y verificada en producción (remedido hoy: PR 261 mergueado el 05-09, producción fijada al digest `sha256:0f13e245…` con el secret de Harbor, subida de .xlsx funcionando desde SC-332/INFRA-70). ¿La cierro como ya entregada, junto con su gemela INFRA-95, que cuenta el mismo arreglo? Opciones: (a) cerrar ambas — coste: ninguno, solo dos transiciones a Done; (b) dejarlas abiertas como registro — coste: dos épicas fantasma en Backlog que volverán a la cola de plan en cada pasada.
