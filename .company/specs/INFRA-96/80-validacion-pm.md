Rol: pm · Fecha: 2026-09-30T20:56:23Z · Sesión: cb083c2e-1f9e-4703-8159-7b91f22ff825 · Estado: CUMPLE

# INFRA-96 — validación pm: CUMPLE (caso ENTREGADA, cerrada con evidencia medida hoy)

Veredicto: la épica no requiere desarrollo. Su trabajo está mergeado desde el 07-09 (PR #280 de
dgx-infra, vida anterior SC-318) y verificado hoy en producción. Una fila por criterio, con el
comando y la salida medidos hoy (30-09-2026 ~20:56 UTC):

| Criterio | Veredicto | Comando medido hoy | Salida |
|---|---|---|---|
| App `chat` Synced/Healthy sin OutOfSync | CUMPLE | `kubectl get application chat -n argocd` + scan de `status.resources` | `chat Synced Healthy d1b588f94061…` (project default); OutOfSync/recursos no sanos: NINGUNO |
| Los 6 defaults del CRD en git | CUMPLE | `git -C ~/k8s/dgx-infra fetch && git show origin/master:k8s/apps/chat/externalsecret-harbor-pull.yaml \| grep -E 'conversionStrategy\|decodingStrategy\|metadataPolicy\|nullBytePolicy\|engineVersion\|mergePolicy'` | 29 `engineVersion: v2`, 30 `mergePolicy: Replace`, 35 `conversionStrategy: Default`, 36 `decodingStrategy: None`, 37 `metadataPolicy: None`, 38 `nullBytePolicy: Ignore` — los 6 |
| `harbor-pull` sirve el pull secret, sin ImagePullBackOff | CUMPLE | `kubectl -n chat get deploy chat -o jsonpath='{.spec.template.spec.imagePullSecrets}'`; `kubectl -n chat get pods`; `kubectl -n chat get secret harbor-pull`; `kubectl -n chat get externalsecret harbor-pull` | `[{"name":"harbor-pull"}]`; `chat-5c785f4774-q9qp6 2/2 Running 0 47h`; `harbor-pull kubernetes.io/dockerconfigjson`; `SecretSynced True` |
| AC2 de SC-280 (hoy SC-934) single-arch | CUMPLE | `jira_get_issue SC-934` | `Done` |

Hijos (verificados hoy en Jira, claves reales tras las renumeraciones): SC-957 `Done`,
SC-958 `Done`, SC-959 `Done`. Ningún hijo abierto; no hay nada que cerrar aparte de la épica.

Trabajo reciente (24 h): las sesiones de SC-1334/SC-1358 del 30-09 mencionan `harbor-pull` pero es
el bootstrap de traefik en la app `k8s-infra`, otro recurso; nada toca el ExternalSecret de `chat`.
