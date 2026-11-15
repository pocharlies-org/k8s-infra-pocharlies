# Plan INFRA-42 — margen de CPU solicitada en ks5-cp-1/2/3

Sesión CTO: 35035e87-08d8-4266-9326-e6483e75430b · Tech lead: agent-a224d1399439d296e

## Verdad cuando está hecho
- Ninguno de ks5-cp-1/2/3 supera 85% de CPU requests sobre allocatable (8000m c/u) en estado normal.
- Job de prueba 25m con podAffinity obligatoria al pod openclaw-qwen36 → Running < 60 s, sin intervención.

## Estado vivo (CTO, 13-09-2026, a re-verificar por sre)
cp-1 3350m (41%) · cp-2 7875m (98%) · cp-3 8000m (100%) — el baseline de la épica (12-09) está obsoleto; el problema hoy son cp-2 y cp-3.

## Partes
1. HISTORIAS (pm): 4 historias bajo INFRA-42, proyecto INFRA, derivadas de los 6 criterios:
   medición / rebalanceo GitOps / verificación (margen + job) / documentación. Asignadas a me+carla.
2. MEDICIÓN (sre, read-only): por nodo cp-1/2/3, tabla por carga: request m, p95 14 d (VictoriaMetrics),
   nodo actual, PVC Longhorn RWO sí/no, veredicto (bajar request / mover / dejar). PromQL pegada.
   ubuntu y sauvage como destino: margen y cargas actuales. Nodo del pod openclaw-qwen36.
   La tabla va como comentario en INFRA-42 (la pega el tech lead). Cubre criterios 1 y 5 (evidencia).
3. REBALANCEO (developer/devops, un maker por repo, paralelo entre repos): con la medición, bajar
   requests infladas y/o nodeSelector/affinity a ubuntu/sauvage solo de cargas sin PVC RWO Longhorn.
   Tronco = .spec.source.targetRevision de la Application. PR, nunca merge, nunca kubectl patch/scale.
   k8s-infra-pocharlies: rama propia + fetch/rebase (sesión paralela a3f4f554 en Longhorn), nunca --force.
4. QA: revisión de cada PR (diff vs veredicto de medición, GitOps puro, tronco correcto).
   Tras el merge del CTO y sync de ArgoCD: describe node de los 3 (≤85%) y job 25m podAffinity → Running <60 s,
   borrar job. [Post-merge: fuera del alcance de este turno del tech lead.]
5. PM: veredicto funcional criterio a criterio.
6. DOC: cada PR nombra el doc actualizado o "no hacía falta". Cierre final en Confluence (lo hace el CTO).

## Fuera de scope
- Rediseño de la podAffinity de los hooks safe-deploy de openclaw (candidato a épica DGX).
- Sparks gx10-ec3d/nvidia-dgx. Cargas SKIRM (skirmshop-brain, aiops-qdrant) solo si la medición lo exige.
