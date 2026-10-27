Rol: tech-lead · Fecha: 2026-10-07 · Sesión: en-vivo-INFRA-628 · Estado: LISTO

# INFRA-628 · P1 · Liberar CPU de ks5-cp-3 bajando el request de ClickHouse de Langfuse

## Qué y por qué
Los instance-manager v1.13.0 de Longhorn en ks5-cp-2/cp-3 están en `error` por OutOfcpu (piden 960m y los nodos van a 7,9/8 de requests). En cp-3 faltan ~475m. El pod `langfuse-clickhouse-shard0` (cp-3) pide 1000m y usa ~276m: bajar su request a 300m libera 700m y el IM v1.13 de cp-3 arranca solo. Con eso el PVC `pvc-523d9aa1-4bbc-46f6-8822-398a8de29acc` (control-nexus/dgx-dashboard-backend) recupera una réplica y el dashboard DGX vuelve.

## Dónde corre / tronco
Repo `pocharlies-org/k8s-langfuse-pocharlies`. La Application ArgoCD `langfuse` lee `targetRevision: main` (source 2, path `k8s/platform`, `ref: values`; el chart externo toma `$values/k8s/values.yaml`). Revisión sincronizada hoy: fd8c5b1 = `origin/main`. NO es `deploy/prod` (obsoleta) ni `it/scold-639-retention-retry` (rama de otra sesión: no se toca). La PR sale de `origin/main` y va contra `main`.

## Cambio (mínimo)
`k8s/values.yaml`, bloque `clickhouse.resources`: `requests.cpu: "1"` -> `"300m"`. Nada más (limits, memoria y PVC igual). Actualiza el comentario del bloque (línea "la CPU se deja igual porque ks5-cp-3 va al 78%") para decir que el request baja a 300m por INFRA-628 (uso real ~276m, el límite 1500m permite ráfagas).

## Criterios de aceptación
- [ ] `git diff origin/main --stat` toca solo `k8s/values.yaml`, y el diff cambia únicamente `requests.cpu` (y el comentario).
- [ ] `helm template` del chart langfuse 1.5.38 con ese values (o la comprobación equivalente que el repo permita) muestra el StatefulSet `langfuse-clickhouse-shard0` con `requests.cpu: 300m` y `limits.cpu: 1500m`.
- [ ] PR contra `main` con título que lleve `INFRA-628`; CI/`duplicados` verdes; veredictos qa y architect registrados con `company-aprobar` y `estado` = LISTA.
- [ ] `50-entrega.md` en INFRA-628 con rama, PR, head sha y la salida del helm template.

## Prohibido
`kubectl edit/patch/apply` en el vivo (langfuse tiene selfHeal), borrar pods/PVC, tocar otras ramas, merge. Solo rama + PR. No esperar a CI: acabar con la PR y el run id.

## Verificación post-merge (la hace el CTO y luego IT, no tú)
IM v1.13 de cp-3 `running`, PVC del dashboard con attach, `dgx-dashboard-backend` Ready, `/api/model-routing/config` sirviendo `alibaba_account_weights`.
