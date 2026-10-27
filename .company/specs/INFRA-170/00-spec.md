Rol: tech-lead · Fecha: 2026-09-18 · Sesión: 35035e87-08d8-4266-9326-e6483e75430b · Estado: LISTO

# INFRA-170 · Medición real vs requests en ks5-cp-2 (criterios 1 y 5, baseline 18-09)

## Qué

Medir el uso real de CPU (p95, 14 días) de TODAS las cargas alojadas hoy en el nodo `ks5-cp-2` cuya request supere 100m, y devolver la tabla: carga, request actual (m), p95 (m), ratio request/p95, veredicto (bajar request a X / dejar / no tocar), y flag de si la carga tiene PVC RWO de Longhorn.

## Por qué

cp-2 está hoy (18-09) a 6950m de 8000m allocatable (86 %), fuera del límite del 85 % del criterio 3. El repunte viene de carga nueva desde el rebalanceo del 13-09 — `langfuse langfuse-clickhouse-shard0-0` pide 1000m y no existía en la medición del 13-09. Antes de tocar ninguna request hay que medir cuál está inflada de verdad. Esta tabla es la evidencia del criterio 1 y la entrada de la story INFRA-171 (los PRs).

## Fuente y método

- VictoriaMetrics: `vmsingle-vm-victoria-metrics-k8s-stack.monitoring.svc:8428`, accesible con `export KUBECONFIG=~/.kube/config && kubectl -n monitoring port-forward svc/vmsingle-vm-victoria-metrics-k8s-stack 8428:8428` (u otro puerto local).
- PromQL por contenedor, la forma pedida por el CTO:
  `quantile_over_time(0.95, sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{container!="", container!="POD"}[10m]))[14d:5m])`
  - Comprueba primero qué etiqueta de nodo exponen las métricas en este cluster (`node`, `kubernetes_node`, …) y filtra por `ks5-cp-2`; si las pods se movieron de nodo dentro de la ventana, mide por pod actual de cp-2 sin filtro de nodo y dilo en la tabla.
- Requests actuales: `kubectl get pods -A --field-selector spec.nodeName=ks5-cp-2 -o json`, sumar `resources.requests.cpu` por pod (todas las contenedores).
- Flag storage: para cada carga de la tabla, si monta PVC con `accessModes: ReadWriteOnce` y storageClass longhorn (mirar PVC/PV).

## Criterios de aceptación

- [ ] Tabla con una fila por carga de cp-2 con request >100m: carga (namespace/pod), request actual (m), p95 14d (m), ratio, veredicto, flag PVC RWO Longhorn.
- [ ] `langfuse/langfuse-clickhouse-shard0-0` (1000m) presente en la tabla.
- [ ] Pegada la PromQL exacta usada y la fuente (endpoint de VictoriaMetrics).
- [ ] Veredicto por carga según margen: request > 2× p95 → bajar request (propón valor ≈1.5–2× p95 redondeado); request ≤ 2× p95 → dejar. Marca explícitamente `no tocar` a longhorn instance-manager y argocd-application-controller.
- [ ] Resultado adjunto a esta issue como `nota-sre-medicion-cp2.md` (con el header de rol), vía `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py attach INFRA-170 nota-sre-medicion-cp2.md`.

## Restricciones

- Solo lectura contra el clúster vivo: nada de `kubectl apply/patch/scale/delete`, nada de escribir en repos.
- No tocar los Sparks (gx10-ec3d, nvidia-dgx).

## Verificación

El tech lead y qa contrastan la tabla con `kubectl describe node ks5-cp-2` (sección Allocated resources) y con los manifiestos de cada repo.
