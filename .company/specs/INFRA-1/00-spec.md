Rol: pm · Fecha: 2026-09-21T03:35:00+00:00 · Sesión: c9f2ceaf-bb14-484d-ae5f-26c9debc57b8 · Estado: LISTO

# INFRA-1 — cluster-verde: ArgoCD y jobs

## Objetivo
Dejar las 95 Applications de ArgoCD en `Synced`+`Healthy` y los dos CronJobs que fallan cada noche (`langfuse-retention`, `rag-nl-llm-matcher`) completando, con la causa raíz de cada item escrita y el fix por GitOps. La épica envuelve SC-86/SC-797 (Done 17-09): el inventario de arriba se midió HOY 21-09 y es en parte nuevo o reincidente.

Repo: k8s-gitops-pocharlies
(tronco `deploy/prod` — medido: `kubectl get application root -n argocd -o jsonpath='{.spec.source.targetRevision}'` → `deploy/prod`. Los fixes de cada app van como PR al repo dueño de esa app — así funciona el GitOps aquí —; este repo es el plano de coordinación: las Applications viven en `apps/` e `infra/`.)

## Inventario medido en vivo (2026-09-21 ~03:20Z, `export KUBECONFIG=~/.kube/config`)
Degraded (3):
- `langfuse` — CronJob `langfuse-retention` (04:00Z diario) falla desde el 20-09; job `langfuse-retention-29831280` con 2 pods `Error`.
- `skirmshopshopifyapp` — CronJob `rag-nl-llm-matcher` (ns skirmshop, 06:30Z diario) falla 3 noches seguidas (18/19/20-09), 2 pods `Error` cada una.
- `skirmshop-brain-prod` — `Degraded` desde el 14-09 con sync correcto; el hijo degradado está anidado en el resource tree (los `status.resources` de nivel 1 no lo listan — ver trabajo reciente 19-09).

Progressing (2): `dashboard-ui`, `k8s-infra` (puede ser rollout en curso: verificar antes de tocar).

OutOfSync (6): `k8s-observability`, `restore-drill`, `root`, `synapse`, `synapse-sre-foundation`, `shopify-back-in-stock`. Los cuatro primeros tienen `automated`+`selfHeal` (git adelantado o self-heal bloqueado); `shopify-back-in-stock` y `synapse-sre-foundation` NO tienen sync automático (necesitan policy en git o sync manual justificado).

## Criterios de aceptación
- [ ] C1 — Cero apps fuera de verde. Comando:
      `kubectl get applications -n argocd --no-headers | awk '$2!="Synced" || $3!="Healthy"'`
      Salida esperada: vacío (hoy devuelve las 11 filas del inventario).
- [ ] C2 — `langfuse-retention` vuelve a completar sin borrar los jobs fallidos para fingir verde. Comando (evidencia, no fix):
      `kubectl create job langfuse-retention-plan-check --from=cronjob/langfuse-retention -n langfuse && kubectl wait --for=condition=complete job/langfuse-retention-plan-check -n langfuse --timeout=20m`
      Salida esperada: `condition met`. Precedente de método: SC-228 (job manual desde el CronJob como evidencia).
- [ ] C3 — `rag-nl-llm-matcher` idem:
      `kubectl create job rag-nl-llm-matcher-plan-check --from=cronjob/rag-nl-llm-matcher -n skirmshop && kubectl wait --for=condition=complete job/rag-nl-llm-matcher-plan-check -n skirmshop --timeout=30m`
      Salida esperada: `condition met`.
- [ ] C4 — Ningún job NUEVO falla tras el fix. Comando:
      `kubectl get jobs -A -o json | python3 -c "import json,sys; [print(j['metadata']['namespace'], j['metadata']['name']) for j in json.load(sys.stdin)['items'] if j['status'].get('failed') and not j['status'].get('succeeded')]"`
      Salida esperada: vacío, o solo los objetos fallidos ANTERIORES a la fecha del fix (pendientes de TTL), nunca ninguno creado después.
- [ ] C5 — Causa raíz y fix documentados por item: cada uno de los 11 items del inventario tiene en la entrega una línea con la causa y el PR/commit que lo arregla, o la línea explícita "no hizo falta cambio en git" con el motivo (p. ej. sync pendiente de git adelantado). Silencio no es respuesta.
- [ ] C6 — Durabilidad: 24 h después de ver C1 en verde, repetir C1 (vacío) y comprobar que las ejecuciones programadas de los dos CronJobs completan solas:
      `kubectl get jobs -n skirmshop -o wide | grep rag-nl-llm-matcher-298 | tail -2` y
      `kubectl get jobs -n langfuse -o wide | grep langfuse-retention-298 | tail -1`
      Salida esperada: `Complete 1/1` en las ejecuciones posteriores al fix.

## Restricciones
- Fix SOLO por GitOps: commit+push+PR al repo que lee ArgoCD y sync. Prohibido `kubectl patch/apply` manual como fix y prohibido borrar jobs/Application para fingir verde (regla del gate SC-86, sigue vigente).
- Nunca `kubectl delete` de una Application ArgoCD (finalizer → cascada).
- PRs contra el tronco que lee ArgoCD de cada repo (check `.spec/source/targetRevision`): gitops = `deploy/prod`.
- No tocar el arbiter de los Sparks ni perfiles de cómputo; no hay dinero ni borrados irreversibles.
- `dashboard-ui`/`k8s-infra` pueden estar Progressing por rollout legítimo en curso: verificar y no "arreglar" lo que se cura solo.
- No duplicar épicas hermanas: SKIRM-29 (skirmbooks), SKIRM-30 (shopify-sync), SKIRM-31 (labels) y INFRA-96 (chat OutOfSync) — hoy 21-09 esos apps están Synced+Healthy medido; si sus dueños las cierran, no reabrir aquí.

## Trabajo reciente (24 h)
- Ninguna sesión viva ni transcript de 24 h toca esta épica (radar: solo la mía; grep de transcripts 24 h por `cluster-verde|argocd degraded|INFRA-1|rag-nl-llm|langfuse-retention`: vacío).
- Dentro de 24 h: la última ejecución nocturna de los dos CronJobs TAMBIÉN falló (`langfuse-retention-29831280` 20-09 04:00Z, pods con 23 h; `rag-nl-llm-matcher-29831310` 20-09, 22 h) → la rotura está activa, los criterios C2/C3 son obligatorios, no opcionales.
- Contexto inmediato (fuera de 24 h, afecta al método): sesión 19-09 (DGX-182, cwd dgx-infra) midió que el resource tree de apps grandes degrada en hijos anidados invisibles en `status.resources` nivel 1 — para `skirmshop-brain-prod` hay que mirar por la API de argocd-server o `kubectl get <kind> -n <ns>` directo. Sesión 17-09 (cwd dgx-infra) cerró `backup-logical-dumps` por la misma vía (job manual como evidencia). SC-86/SC-797 Done 17-09: los 7 apps de aquel encargo CEO están verdes hoy salvo los reincidencias de este inventario.

## Historias previstas
1. langfuse Degraded: causa raíz y fix del CronJob `langfuse-retention` — owner devops (repo dueño: k8s-langfuse-pocharlies).
2. skirmshopshopifyapp Degraded: causa raíz y fix de `rag-nl-llm-matcher` (3 noches) — owner devops.
3. skirmshop-brain-prod Degraded desde 14-09: localizar el hijo degradado del tree y fix — owner devops.
4. Progressing → Healthy: `dashboard-ui` y `k8s-infra` (verificar si es rollout legítimo) — owner devops.
5. Los 6 OutOfSync: sync y, donde falte, política de sync en git (`shopify-back-in-stock`, `synapse-sre-foundation`) — owner devops (repo principal: k8s-gitops-pocharlies).
6. Barrido de durabilidad C1/C4/C6 con salida real + veredicto — owner qa.

## Tamaño
M — 11 items pero cada uno acotado (la mayoría sync o un CronJob roto), un CTO, menos de una semana. No se divide: es un barrido de diagnóstico y partirlo por repo rompería el barrido sin reducir trabajo (cada hija sería una historia); los fixes multi-repo son PRs normales del maker dueño.
