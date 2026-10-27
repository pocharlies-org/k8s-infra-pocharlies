Rol: pm · Fecha: 2026-09-30T20:56:23Z · Sesión: cb083c2e-1f9e-4703-8159-7b91f22ff825 · Estado: CERRADA

# INFRA-96 — chat: cerrar el OutOfSync cosmético de ExternalSecret/harbor-pull (defaults del CRD ausentes en git)

## Objetivo
Que la Application `chat` esté `Synced` / `Healthy` sin recursos `OutOfSync`, con los seis defaults
que el CRD de external-secrets rellena solos escritos en git en `ExternalSecret/harbor-pull`.
Medido hoy 30-09-2026 en vivo, eso es verdad: el trabajo se entregó el 07-09 como la vida anterior
de esta misma épica (SC-318 → INFRA-6 → INFRA-96, renumerada por los cambios de proyecto), PR #280
de dgx-infra mergeado a `master`.

Repo: dgx-infra (pocharlies-org/dgx-infra, tronco `master`, path `k8s/apps/chat/`)

## Criterios de aceptación
Todos medidos HOY (30-09-2026 ~20:56 UTC, estado vivo, no de memoria):

- [x] `kubectl get application chat -n argocd` devuelve `Synced` / `Healthy`, sin recursos `OutOfSync`.
  Comando: `export KUBECONFIG=~/.kube/config && kubectl get application chat -n argocd`
  Salida hoy: `chat   Synced   Healthy   d1b588f94061…` (project default). Lista de recursos
  OutOfSync/sanos-rotos sobre `status.resources`: NINGUNO.
- [x] Los seis defaults del CRD están escritos en `k8s/apps/chat/externalsecret-harbor-pull.yaml`.
  Comando: `git -C /home/dibanez/k8s/dgx-infra fetch && git show origin/master:k8s/apps/chat/externalsecret-harbor-pull.yaml | grep -E 'conversionStrategy|decodingStrategy|metadataPolicy|nullBytePolicy|engineVersion|mergePolicy'`
  Salida hoy (tras fetch): línea 29 `engineVersion: v2`, 30 `mergePolicy: Replace`,
  35 `conversionStrategy: Default`, 36 `decodingStrategy: None`, 37 `metadataPolicy: None`,
  38 `nullBytePolicy: Ignore` — los 6. Merge original: PR #280 (07-09); el PR #327 (11-09,
  migración Vault → 1Password) conservó los defaults.
- [x] El `harbor-pull` sigue sirviendo el pull secret, sin `ImagePullBackOff`.
  Comandos (ns `chat`): `kubectl -n chat get deploy chat -o jsonpath='{.spec.template.spec.imagePullSecrets}'`
  → `[{"name":"harbor-pull"}]`; `kubectl -n chat get pods` → `chat-5c785f4774-q9qp6 2/2 Running 0 47h`;
  `kubectl -n chat get secret harbor-pull` → `harbor-pull kubernetes.io/dockerconfigjson`;
  `kubectl -n chat get externalsecret harbor-pull` → `SecretSynced  True`.
- [x] AC2 de SC-280 (hoy SC-934) corregido a single-arch: SC-934 está `Done` (verificado hoy).

## Restricciones
- No re-pinear el digest de la imagen de `chat` (rollout = ~1 min de HTTP 500 en chat.e-dani.com,
  `strategy: Recreate` + `replicas: 1`).
- No tocar `k8s/apps/chat/networkpolicy.yaml` (load-bearing).
- GitOps: PR contra `master` (el tronco que lee ArgoCD para dgx-infra), nunca push directo.

## Trabajo reciente (24 h)
- Sesiones del 30-09 sobre SC-1334/SC-1358 (traefik-edge, `web/harbor-pull` de la app `k8s-infra`)
  mencionan "harbor-pull" pero es otro recurso (el bootstrap de traefik), sin relación con el
  OutOfSync de `chat`: no toca este objetivo.
- Ninguna sesión viva tocando el ExternalSecret de `chat`. El manifiesto no se ha movido desde el
  PR #327 (11-09).

## Diseño
Diseñador: no — sin superficie de UI

## Historias previstas
Ninguna. El trabajo está mergeado y medido en producción; no hay CTO que lanzar.

## Tamaño
S (cero historias): es un cierre con evidencia, no un desarrollo.

## Cierre
Caso ENTREGADA. Motivo: entregada como SC-318 (PR #280 de dgx-infra, 07-09-2026); esta épica es
ella misma renumerada (SC-318 → INFRA-6 → INFRA-96). Evidencia de hoy: app `chat` Synced/Healthy
sin OutOfSync, los 6 defaults en `origin/master`, pod `chat` 2/2 Running con el pull secret
sirviéndose (ExternalSecret SecretSynced=True). Hijos: SC-957, SC-958 y SC-959 ya `Done` (verificado
hoy); ningún hijo abierto.
