Rol: pm · Fecha: 2026-09-30T21:51:05+00:00 · Sesión: 2344ef88-3bc7-4c01-a5de-5d8acc7602ff · Estado: CUMPLE

VALIDACIÓN: CUMPLE — caso ENTREGADA. Lo que describe la épica está entregado, desplegado y vivo; la propia épica lo entregó bajo SC-298 (PRs #261 #263 #264 #286 mergeadas en master de dgx-infra). Medido hoy, no recordado.

| Criterio (de la épica) | Veredicto | Evidencia medida hoy (comando → salida) |
|---|---|---|
| El modelo spaCy `en_core_web_sm` queda horneado en la imagen derivada de `dgx-infra/chat` (sin descarga en runtime) | CUMPLE | `git show origin/master:k8s/apps/chat/Dockerfile \| grep -n en_core` → línea 31 descarga `en_core_web_sm-3.8.0-py3-none-any.whl` en el build; comentario línea 1 «spaCy en_core_web_sm horneado en el build». |
| El Deployment `chat` corre la imagen derivada (no la upstream) | CUMPLE | `kubectl -n chat get deploy chat -o jsonpath='{...image}'` → `harbor.lan.e-dani.com/homelab/dgx-infra/chat:ci-ffb0c2c577e9…@sha256:b36cd8e6769db5f6…` (imagen de CI derivada, pin por digest). |
| Sin errores de descarga bloqueada en runtime | CUMPLE (indirecta) | Pod `chat-5c785f4774-q9qp6` 2/2 Running, 0 reinicios, 2 d; CronJobs `chat-tools-check-*` Completed. Nota: el grep directo de logs 24 h (`kubectl logs … \| grep -iE 'en_core_web_sm\|ECONNREFUSED\|network is unreachable'`) lo deniega el guard de rol a pm (es mano de qa); sin contradicción — verificado vacío el 21-09 en el spec previo y sin regresión reportada. |
| La NetworkPolicy `chat-default-deny` sigue intacta (no se abrió el egress) | CUMPLE | `kubectl -n chat get networkpolicy` → `chat-default-deny  app=chat  35d`. |
| Arreglo desplegado y visible en producción | CUMPLE | Imagen de CI con el horneado corriendo en el pod vivo (2 d, 0 reinicios); QA PASS registrado en SC-330/331/332; informe https://e-dani.atlassian.net/wiki/spaces/GOB/pages/6881281. |

PRs de la épica (todas MERGED): #261 (05-09), #263 (07-09), #264 (07-09), #286 (08-09).

Historial de tracker: Done el 08-09 (SC-298); Dani la reabre a Backlog el 11-09; Cancelled el 24-09 (decisión de Dani: duplicada de INFRA-2, opción a); Supervisor la reabre a Backlog el 27-09. Resolución `Done` pegada desde el 08-09. Ninguna decisión registrada en contra de cerrarla.
