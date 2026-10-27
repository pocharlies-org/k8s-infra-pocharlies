Rol: pm · Fecha: 2026-09-30T21:51:05+00:00 · Sesión: 2344ef88-3bc7-4c01-a5de-5d8acc7602ff · Estado: CERRADA

# INFRA-95 — Open WebUI y los .xlsx (spaCy horneado en la imagen)

## Objetivo
Que Open WebUI (chat.e-dani.com) lea ficheros `.xlsx`. Causa raíz: `unstructured` descargaba el modelo spaCy `en_core_web_sm` en runtime y la NetworkPolicy `chat-default-deny` cortaba la descarga. Arreglo: hornear el modelo en la imagen derivada de `dgx-infra/chat` en el build. ENTREGADO y vivo desde el 08-09-2026, por la propia épica bajo SC-298.

Repo: dgx-infra (`k8s/apps/chat/Dockerfile` y `deployment.yaml`).

## Restricciones
- Sin abrir el egress de `chat-default-deny` (sigue vigente).
- Cambios de imagen solo por git/ArgoCD (master de dgx-infra), nunca `kubectl set image`.

## Cierre
Caso **ENTREGADA** → Done. Motivo: lo que describe la épica está entregado, desplegado y verificado en producción desde el 08-09-2026; no hay trabajo pendiente ni regresión. La épica lo entregó ella misma (SC-298), no otra.

Evidencia medida hoy (2026-09-30, comandos y salida):
- `git show origin/master:k8s/apps/chat/Dockerfile | grep -n en_core` → línea 31 descarga `en_core_web_sm-3.8.0-…whl` en el build; línea 1 «spaCy horneado en el build».
- `kubectl -n chat get deploy chat -o jsonpath='{...image}'` → `harbor.lan.e-dani.com/homelab/dgx-infra/chat:ci-ffb0c2c577e9…@sha256:b36cd8e6769db5f6…` (imagen derivada de CI, pin por digest).
- `kubectl -n chat get pods` → `chat-5c785f4774-q9qp6` 2/2 Running, 0 reinicios, 2 d.
- `kubectl -n chat get networkpolicy` → `chat-default-deny app=chat 35d` (intacta).
- PRs dgx-infra: #261, #263, #264, #286 todas `state:MERGED`.
- No medido por pm: grep de logs 24 h y `spacy.load` en el pod — `kubectl logs`/`exec` los deniega el guard al rol pm (mano de qa). Sin contradicción: vacío el 21-09, CronJobs `chat-tools-check-*` Completed, sin regresión reportada.

Historial de tracker: Done 08-09 (SC-298) → Dani reabre a Backlog 11-09 → Cancelled 24-09 (decisión de Dani: duplicada de INFRA-2, opción a) → Supervisor reabre a Backlog 27-09. Resolución `Done` pegada desde 08-09. Ninguna decisión en contra de cerrarla.

## Trabajo reciente (24 h)
- Sesión pm actual (sid 2344ef88…): fase de cierre de INFRA-95. Medición en vivo arriba; cierre ENTREGADA → Done.
- INFRA-2 (gemela, mismo arreglo): medida hoy → status Backlog, resolución Done, sin asignar, etiquetas `plan-innecesaria`+`plan-revisado`. No la cierro yo (no es mi clave): queda para su dueño.

## Historias previstas
Ninguna — no hay construcción pendiente.

## Tamaño
S (cero construcción): la única acción era el cierre de tracker.
