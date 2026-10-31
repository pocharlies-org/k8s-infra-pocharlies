# Plan INFRA-41 — Longhorn zombie pods tras reinicio de k3s

Tech-lead: agent-abd9f7e7cbae8a9d3 · Sesión CTO: a3f4f554-1272-44bb-83a4-fe1092df119e

## Bug
Tras reiniciar k3s, kubelet reintenta MountVolume.SetUp sobre pods ya Running; Longhorn
rechaza NodePublishVolume ("no Pending workload pods") → bucle eterno 0/N Ready. v1.11.2.

## Partes
1. A — Upstream (developer, read-only): issue/PR longhorn-manager csi/node_server +
   release notes v1.11.3+/v1.12.x. Veredicto: versión que lo arregla o ajuste.
   Publica comentario diagnóstico en INFRA-41 (criterio 1). Si el fix exige acción
   disruptiva (upgrade offline), PARA y reporta antes de construir.
2. Recon (devops, read-only, paralelo a A): superficie GitOps real del app longhorn
   (manifest Application en k8s-gitops@deploy/prod?, qué source aporta values, si
   k8s-infra storage/longhorn/values.yaml está vivo o muerto) + evidencia de backup
   (velero schedules + último backup sano, system-backup-cron Longhorn, backup-pvc-hub).
3. PM: historias bajo INFRA-41 (INFRA) por criterios, asignadas "Daniel Ibanez Fernandez",
   rol en descripción, Rescate con sesión CTO + agent id.
4. B — Fix (devops, tras A+Recon): PR al tronco que lee ArgoCD (k8s-gitops: deploy/prod;
   k8s-infra: main) con bump chart/ajuste settings + manifiesto GitOps pod de prueba
   (ns pruebas, PVC RWO, nodeSelector ks5-cp-3, NO auto-desplegado, NO tocar kustomization
   raíz de k8s-infra) + runbook. Nunca imperativo, nunca merge, nunca reinicio.
5. QA: veredicto con evidencia de lo verificable sin reinicio; comentario en INFRA-41.
6. PM: veredicto funcional criterio a criterio; comentario en INFRA-41.

## Done
Comentario diagnóstico (criterio 1), PR en repo/rama correctos con fix+pod prueba+runbook
(criterios 2 y 4), backup citado (criterio 5), verdictos qa+pm, reproducción pendiente de
ventana operador (criterio 3, declarado), merge del CTO.

## Riesgos
- App k8s-infra OutOfSync/Degraded (sesión paralela): no cabalgar; si bloquea, reportar.
- Upgrade de chart = plano de almacenamiento de todo el clúster: si A dice que exige
  acción disruptiva, se para y sube al CTO.
