# DGX-796 evidence (P2 de DGX-787, builder en dgx3), 2026-10-10

Estado leído antes (C-1, solo lectura; no se toca ningún nodo ni Application):
`gpu-arbiter-state.compute_mode` = `effective_mode llm-tp`, `phase sync-paused`
(`sync_pause.by ai-presync`), `transition_id 4d5df81250184cc49bad32b6925d59e4`, sin blockers.
La app `k8s-infra` lee `.` en `main` y el `kustomization.yaml` raíz lista `- buildkit` (línea 77).

## 1. Render de la raíz (lo que lee ArgoCD) -- PASS
Command: `kubectl kustomize .` + comprobación en Python sobre los Deployment/Service del ns `buildkit`
```
buildkitd-amd64 selects dgx3 pod: False
buildkitd-arm64 selects dgx3 pod: False
buildkitd-arm64-dgx3 selects dgx3 pod: True
replicas 0 | nodeSelector {'kubernetes.io/hostname': 'dgx3'}
resources {'limits': {'cpu': '10', 'memory': '64Gi'}, 'requests': {'cpu': '8', 'memory': '32Gi'}}
misma imagen (digest) que buildkitd-arm64: True | nvidia.com/gpu: ausente
```

## 2. kubectl apply --dry-run=server de los 4 objetos nuevos (nada se guarda) -- PASS
```
configmap/buildkitd-arm64-dgx3-config created (server dry run)
service/buildkitd-arm64-dgx3 created (server dry run)
persistentvolumeclaim/buildkitd-arm64-dgx3-cache created (server dry run)
deployment.apps/buildkitd-arm64-dgx3 created (server dry run)
```

## Criterios de DGX-796 que cubre esta PR
- C3 (builder a `replicas: 0`, fijado a dgx3, con requests): secciones 1 y 2.
