# INFRA-42 criterio 1 — PromQL exacta usada (funcionó en vmsingle de monitoring)

p95 de uso CPU por pod, últimos 14 días, por nodo (cambiar el valor de node= por nodo):

quantile_over_time(0.95, sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{node="ks5-cp-2",container!="",container!="POD"}[10m]))[14d:10m])

Total real por nodo (todos los contenedores, incluye CronJob terminados):

quantile_over_time(0.95, sum(rate(container_cpu_usage_seconds_total{node="ks5-cp-2",container!="",container!="POD"}[10m]))[14d:10m])

Ejemplo de salida real:

{"metric":{"namespace":"agentgateway","pod":"agentgateway-mcp-79f7ffdfbb-vwrbr"},"value":[1789281853,"0.004196165000000001"]}  -> 4.2m

Notas: p95max = máximo del p95 por pod entre los pods del workload en la ventana. La serie no lleva labels de owner (deployment/owner_name); el mapeo pod a workload se hizo en cliente quitando el hash del nombre de pod. Acceso al endpoint: kubectl -n monitoring port-forward svc/vmsingle-vm-victoria-metrics-k8s-stack 8428:8428 y API /api/v1/query (compatible Prometheus).
