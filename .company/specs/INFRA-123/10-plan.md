Rol: tech-lead · Fecha: 2026-09-18 · Sesión: 35035e87-08d8-4266-9326-e6483e75430b · Estado: LISTO

# 10-plan · INFRA-123 · objetivo despachado el 18-09: cp-2 de vuelta a ≤85 % (≤6800m) por PR GitOps

## Baseline medido 18-09 (CTO)

cp-1 3215m (40 %) OK · cp-2 6950m (86 %) FUERA · cp-3 5830m (72 %) OK.
Causa del repunte de cp-2: carga nueva desde el rebalanceo del 13-09 — `langfuse langfuse-clickhouse-shard0-0` pide 1000m (no existía el 13-09). Topes restantes en cp-2: longhorn instance-manager 960m (no tocar, global), argocd-application-controller 800m (dejar, decisión 13-09), aiops-falkordb 260m, postgres-shared-2 200m (ya aplicado), shared-rabbitmq 200m.

## Partes y orden (reutiliza las stories creadas el 13-09, en Backlog)

1. **Medición** — INFRA-170 (sre): p95 14d vía VictoriaMetrics de toda carga de cp-2 con request >100m; tabla carga/request/p95/veredicto + flag PVC RWO Longhorn. Spec: `00-spec.md` adjunta. Cubre criterios 1 y 5.
2. **PRs GitOps** — INFRA-171 (devops): por cada carga cuya request supere claramente su p95, bajar la request por PR en el repo que la posee (langfuse: pocharlies-org/k8s-langfuse-pocharlies, trunk main, k8s/values.yaml). Spec se concreta con la tabla de la parte 1 antes del dispatch. Cubre criterios 2 y 3 (cálculo).
3. **qa** — veredicto por PR (diff contra la tabla), `70-qa.md` en INFRA-171.
4. **pm** — veredicto funcional del criterio 3, `80-validacion-pm.md`.

## No tocar

longhorn instance-manager (960m) · argocd-application-controller (800m) · cargas con PVC RWO de Longhorn (no mover nodos) · Sparks. Nada contra el clúster vivo (ni apply/patch/scale): todo por PR, el merge lo pulsa el CTO y aplica ArgoCD. El Job de prueba del criterio 4 lo gestiona el CTO aparte.

## Hecho significa

cp-2 calculado ≤6800m tras los PRs (cálculo entregado al CTO con los números), PR con qa CUMPLE y pm met sobre el criterio 3. La verificación viva del nodo (`kubectl describe node`) va en el cierre de la épica, tras el merge.

## Riesgos

- Bajar por debajo del uso real → throttling: margen mínimo 1.5× p95, qa revisa el diff contra la tabla.
- Docs: cada PR nombra el documento actualizado o declara en una línea que no hacía falta (criterio 6).
