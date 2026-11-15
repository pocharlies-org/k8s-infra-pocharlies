Rol: pm · Fecha: 2026-10-08T17:41:14Z · Sesión: 656f42ef-c5c4-4d23-b760-b3ea6e6cfecc · Estado: LISTO

# INFRA-123 — ks5-cp-1/2/3 al límite de CPU solicitada: rebalancear requests para que hooks y pods nuevos se programen

## Dificultad

Dificultad: media — rebalanceo de requests en nodos de control-plane: hay que medir qué existe (p95, colocaciones, decisiones previas) antes de tocar, sin decisión de arquitectura nueva

Propuesta de subir a ALTA (no aplicada; la decide el analista): desde el 06-10 06:41 los instance-manager de Longhorn v1.13.0 de ks5-cp-2 y ks5-cp-3 quedaron en error por OutOfcpu. Dejó 5 volúmenes degraded y el dashboard sin volumen (INFRA-628, Done el 07-10). Hoy la actualización de Longhorn sigue a medias y la capa de almacenamiento del control-plane es la que se toca. Un movimiento mal hecho ahí (detach/attach) rompe volúmenes. Por eso, sin P5 autorizado, la épica no toca volúmenes.

## Objetivo

Que ningún nodo ks5-cp-* supere el 85 % de CPU requestada (<= 6800m de 8000m allocatables) en estado normal, con margen real, y que un pod pequeño con afinidad obligatoria a un nodo cp se programe a la primera. Hoy los hooks de safe-deploy y los pods nuevos con afinidad arriesgan quedar Pending porque el nodo ancla no tiene margen.

## Estado medido HOY (2026-10-08 17:41 UTC, kubectl describe node, allocatable 8 cpu por nodo)

| nodo | CPU requests | % | vs objetivo | qué pesa (>= 250m) |
|---|---|---|---|---|
| ks5-cp-1 | 6145m | 76 % | OK, cumple <= 6600m (margen 455m) | IM Longhorn v1.11.2 960m, IM v1.13.0 960m, aiops-falkordb 260m |
| ks5-cp-2 | 6810m | 85 % | FUERA por 10m del tope 6800m; faltan >= 210m para <= 6600m | IM v1.11.2 960m, vmsingle 700m, vmagent 400m, IM v1.13.0 400m, keycloak 250m, qdrant 250m |
| ks5-cp-3 | 6395m | 79 % | OK, cumple <= 6800m (margen 405m; no entra en la regla 6600m) | IM v1.11.2 960m, argocd-application-controller 800m, clickhouse 600m, hermes-gateway 565m, IM v1.13.0 400m |

Fluctuación medida en cp-2 en la última hora: 7360m (16:30) → 6810m (17:41). La diferencia es carga transitoria (CronJob skirmshop-brain de 250m y Jobs sueltos que entran y salen). El criterio 1 ya exige medir «sin Jobs ajenos en curso»; el fondo real de cp-2 ronda los 6800m.

Cambios contra el 02-10 (medido ese día: cp-1 6755m, cp-2 7065m, cp-3 4910m):
- langfuse-clickhouse-shard0-0 bajó a 600m (langfuse#17, merged 07-10) y se movió de cp-1 a cp-3 (07-10 07:29). Cp-1 bajó y cp-3 subió.
- Longhorn 1.13 a medias: en cp-1, cp-2 y cp-3 conviven dos instance-manager: v1.11.2 (960m, con los engines de volúmenes vivos) y v1.13.0 (400m en cp-2/cp-3, 960m en cp-1). Esto es lo que más pesa hoy.
- El namespace openclaw-qwen36 sigue sin existir (medido el 02-10 y hoy).

## Premisas que cambiaron (aplicadas con evidencia de hoy)

- «clickhouse 1000m vive en cp-1» ya no es verdad: 600m en cp-3.
- «IM Longhorn 960m por nodo» ya no es verdad: dos IM por nodo mientras dure la actualización a 1.13. Los 960m de v1.11.2 solo desaparecen cuando sus volúmenes salgan de esa versión. Eso exige P5 (detach/attach de 43 volúmenes), que el CTO no ha autorizado (comentario de INFRA-628, 07-10 09:35: «P5 NO autorizado; se revalúa con cp-2 en marcha»).
- INFRA-628 (incidente Longhorn, Done 07-10) ya aplicó parte de lo que este spec preveía: clickhouse 600m, KEDA admission-webhooks y NFD master a 10m, y `guaranteed-instance-manager-cpu` en v1 5 / v2 12. S2 no los rehace.

## Qué está ya hecho

- Rebalanceo del 13-09 (13 apps, Synced).
- INFRA-628 (Done 07-10): langfuse#17 merged (clickhouse 600m, 1,5× p95 de 404m); gitops#516 y #517 merged (IM guaranteed cpu y KEDA/NFD a 10m).
- infra#257 (keycloak 250m → 50m, −200m): OPEN. Su ventana 08-10 05:00–05:30 Madrid pasó sin fusionarse. Keycloak sigue en 250m en vivo. Siguiente ventana permitida: 09-10 05:00–05:30 Madrid (no domingo).
- INFRA-170 (medición p95, sre): tiene spec LISTO (id 10785). Sigue sin tabla p95 de los tres nodos.
- INFRA-171 (PRs GitOps, devops): tiene spec LISTO (id 10789). Sin PR propio abierto a fecha de hoy.

## Diseño

Diseñador: no — infraestructura pura: requests de CPU, GitOps y un Job de prueba; ninguna interfaz nueva ni cambiada.

## Criterios de aceptación

- [ ] 1. Margen en los tres nodos. En estado normal los tres nodos <= 6800m (85 %) y cp-1 y cp-2 <= 6600m, medido dos veces con >= 10 min de separación tras el último Sync y sin Jobs ajenos en curso:
  `export KUBECONFIG=~/.kube/config; for n in ks5-cp-1 ks5-cp-2 ks5-cp-3; do kubectl describe node $n | grep -A6 'Allocated resources' | grep -E '^\s+cpu'; done`
  Esperado: fila cpu <= 6800m en los tres nodos y <= 6600m en cp-1 y cp-2, en las dos medidas.
  Hoy 17:41: cp-1 cumple (6145m), cp-3 cumple (6395m), cp-2 NO cumple (6810m, fuera por 10m del 6800m y por 210m del 6600m).
- [ ] 2. Todo el cambio por GitOps, cero kubectl imperativo. Cada bajada de request o cambio de colocación llega por PR al repo que posee la carga (keycloak: pocharlies-org/k8s-infra-pocharlies, infra#257; vmsingle/vmagent: el repo que despliega el stack de monitoring, devops comprueba .spec.source.targetRevision del Application antes de abrir el PR) y el Application queda Synced. Evidencia por carga: URL del PR mergeado + `kubectl get application -n argocd <app> -o jsonpath='{.status.sync.status}'` = Synced + `kubectl get pod ... -o jsonpath='{.spec.containers[*].resources.requests.cpu}'` igual al valor del repo.
- [ ] 3. Bajadas justificadas por p95. Ninguna request baja de 1,5 x el p95 real de 14 días (VictoriaMetrics). Evidencia: tabla de INFRA-170 con la PromQL usada (incluye keycloak, vmsingle y vmagent) y, en cada PR, la fila que justifica el número.
- [ ] 4. Colocación fija, no a la suerte. vmsingle y vmagent (hoy juntos en cp-2, nodeSelector node-pool: ks5-nvme que admite cualquier cp) quedan con restricción declarativa en su chart/values (topologySpreadConstraint o anti-afinidad) que impida que coincidan en el nodo más cargado. Evidencia: diff del PR + `kubectl get pod -n monitoring <pod> -o jsonpath='{.spec.topologySpreadConstraints}{.spec.affinity}'` en los pods nuevos tras el rollout.
- [ ] 5. Job de prueba a la primera. Un Job con request de 25m y podAffinity required a hermes/hermes-gateway (hoy en ks5-cp-3) se crea tras cumplirse el criterio 1 y nunca pasa por Pending: programado en < 10 s y `status.succeeded = 1` en < 60 s (se lee `kubectl get pod -l job-name=<job> -o jsonpath='{.items[0].status.conditions}'` y los eventos del Job). El Job es evidencia efímera: se crea con kubectl y se borra al terminar.
- [ ] 6. Sin regresión de servicio. Tras los cambios: pods de monitoring, langfuse, keycloak y hermes en Running sin restarts nuevos; endpoints presentes (`kubectl get endpoints -n monitoring`, `-n langfuse`, `-n keycloak`); Longhorn sin volúmenes degraded (`kubectl get volumes.longhorn.io -n longhorn-system`); VictoriaMetrics responde `/api/v1/query?query=up` con series.

## Camino hacia el criterio 1 en cp-2 (hipótesis, la confirma S1)

- Keycloak 250m → 50m (infra#257, sigue OPEN a 17:41): −200m sobre el fondo de 6810m → 6610m. Con eso cp-2 cumpliría <= 6800m, pero se quedaría 10m por encima del margen de 6600m.
- Para el 6600m hace falta un recorte extra pequeño además de keycloak (vmsingle o vmagent, solo si el p95 de 14 días lo justifica con 1,5×). Candidatos: vmsingle (700m) y vmagent (400m).
- Si S1 no justifica ese recorte: el criterio 1 en cp-2 solo se cumple cuando salgan los 960m de IM v1.11.2, es decir con P5. P5 no está autorizado: queda como decisión del CTO / de Dani, fuera de esta épica.
- qdrant y loki no se tocan (decisión del CTO, INFRA-628).

## Restricciones

- GitOps obligatorio: prohibido kubectl apply/patch/scale/edit sobre cargas; el merge lo pulsa el CTO.
- Prohibido detach/attach de volúmenes (P5) sin autorización explícita. No está autorizado.
- No tocar longhorn-system/instance-manager-* ni su ajuste global (`guaranteed-instance-manager-cpu`); ya quedó fijado en INFRA-628.
- No tocar argocd-application-controller (800m, decisión del 13-09), qdrant ni loki.
- Cargas con PVC RWO de Longhorn: nada de mover volúmenes a mano.
- No tocar los Sparks (gx10-ec3d, nvidia-dgx) ni los perfiles de cómputo.
- No cambiar configuración de k3s/etcd ni los allocatables de los nodos.
- Las ventanas de cambio de keycloak son 05:00–05:30 Madrid, no domingo.

## Historias previstas

| # | historia | dueño | criterios |
|---|---|---|---|
| S1 | INFRA-170 (existe, Backlog): tabla p95 14 días de keycloak, vmsingle, vmagent y de las cargas >= 250m de cp-1, cp-2 y cp-3, con veredicto por carga y flag RWO. Es la puerta de S2 | sre | 3 |
| S2 | INFRA-171 (existe, To Do): PRs GitOps que faltan: keycloak (infra#257 ya abierto, reprogramar ventana), vmsingle/vmagent con el recorte que S1 justifique, colocación del stack de monitoring. No rehace lo de INFRA-628 | devops | 1, 2, 4 |
| S3 | Job de prueba con podAffinity a hermes-gateway + no-regresión | devops | 5, 6 |
| S4 | Verificación end-to-end en producción de los 6 criterios | qa | todos |

Si S1 no justifica el recorte que necesita cp-2: S2 queda bloqueada en criterio 1 y se devuelve al CTO para decidir P5.

## Tamaño

M.

## Bloqueantes

- S2 espera a S1 (tabla p95).
- Criterio 1 en cp-2 depende de S1. Si S1 es negativo, depende de la decisión sobre P5 (CTO / Dani).

## Trabajo reciente (24 h)

- langfuse#17 merged 07-10 07:28: clickhouse 1000m → 600m; el pod se movió a cp-3 el 07-10 07:29.
- gitops#516/#517 merged (INFRA-628): IM guaranteed cpu v1 5 / v2 12; KEDA admission-webhooks y NFD master a 10m.
- Longhorn 1.13 a medias: dos IM por nodo en cp-1/2/3; el de 1.13 de cp-2 y cp-3 estuvo en OutOfcpu desde el 06-10 06:41.
- infra#257 (keycloak 50m) OPEN: ventana del 08-10 perdida; siguiente 09-10 05:00–05:30 Madrid.
- CronJob skirmshop-brain-personal-payload-normalization (cada hora en :07) pasa por cp-2 con 250m; transitorio, no cuenta en criterio 1.
- INFRA-628 Done 07-10 (decisión CTO: P5 no autorizado).
- 17:41 re-check: infra#257 sigue OPEN; Longhorn sigue con dos IM (v1.11.2 + v1.13.0) en cada cp; cp-2 baja a 6810m al salir la carga transitoria (fondo real ~6800m, no 7360m).
