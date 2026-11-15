Rol: tech-lead · Fecha: 2026-09-18 · Sesión: 35035e87-08d8-4266-9326-e6483e75430b · Estado: LISTO

# INFRA-171 · Bajar requests de ks5-cp-2 por PR GitOps (criterios 2 y 3)

## Qué

Bajar las requests de CPU infladas de las cargas alojadas en ks5-cp-2, cada una por PR en el repo que la posee, hasta dejar el total de requests del nodo calculado en <=6800m (85 % de 8000m). La lista exacta de cargas y valores sale de la tabla de medición `nota-sre-medicion-cp2.md` adjunta a INFRA-170 (p95 real 14d vía VictoriaMetrics, margen sano 1.5–2x).

## Punto de partida (baseline 18-09)

cp-2 a 6950m (86 %). Carga principal a right-sizear: `langfuse/langfuse-clickhouse-shard0-0`, request 1000m, no existía en la medición del 13-09. Su repo: `pocharlies-org/k8s-langfuse-pocharlies`, tronco `main`, requests en `k8s/values.yaml`. El valor nuevo manda de la tabla de INFRA-170 (proposta del SRE ≈1.5–2x su p95). Si la tabla propone bajar alguna otra carga de cp-2 además de langfuse, cada una va por PR en su propio repo contra el tronco que lee ArgoCD de ese repo.

## Criterios de aceptación

- [ ] Un PR por carga en el repo que la posee, contra el tronco que lee ArgoCD (langfuse: main en k8s-langfuse-pocharlies). Nada de kubectl apply/patch/scale contra el clúster vivo.
- [ ] El diff de cada PR coincide con el valor propuesto en la tabla de INFRA-170 (o justifica el redondeo en la memoria del PR).
- [ ] No tocadas: longhorn instance-manager (960m, ajuste global), argocd-application-controller (800m, decisión del rebalanceo 13-09), ninguna carga marcada "dejar" o "no tocar" en la tabla.
- [ ] Ninguna carga con PVC RWO de Longhorn se mueve de nodo (ni nodeSelector/affinity nuevo que la desplace): solo se baja request en el sitio.
- [ ] Suma aritmética: total de requests de cp-2 tras aplicar los PRs <=6800m. El cálculo (tabla antes/después) va en `50-entrega.md`.
- [ ] `50-entrega.md` adjunto a esta issue (header Rol: developer o devops, Estado: LISTO) con: enlaces de PR, diff exacto de cada request, cálculo antes/después, y una línea de documentación (qué doc actualiza o "no hacía falta actualizar ninguno").
- [ ] Cada PR abre contra su tronco con la atribución habitual; nada se mergea (el merge lo pulsa el CTO).

## Verificación

qa revisa el diff de cada PR contra la tabla de INFRA-170 y contra este spec, y adjunta `70-qa.md` (Estado: PASA / NO PASA) a esta issue.

## Restricciones

- No tocar los Sparks (gx10-ec3d, nvidia-dgx).
- Repo langfuse: leer `k8s/values.yaml` justo antes de editar (sesiones paralelas); rama propia + PR, nunca push al tronco.
