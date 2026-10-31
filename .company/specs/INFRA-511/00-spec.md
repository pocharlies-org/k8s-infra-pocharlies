Rol: pm · Fecha: 2026-10-04T20:38:00Z · Sesión: 62004011-5dcb-403f-80d3-d4ffbdf1fc7a · Estado: LISTO

# INFRA-511 — Los ExternalSecret leen 1Password por un 1Password Connect propio

## Objetivo

Que ESO lea el vault k8s-pocharlies a través del servidor 1Password Connect desplegado en el clúster, de modo que relecturas, reinicios y force-sync no gasten el cupo de 1000 peticiones/24 h de la cuenta Families. **El núcleo YA está entregado y vivo** (PR k8s-infra-pocharlies#236 y k8s-gitops-pocharlies#492 mergeadas el 04-10 con qa PASA y architect APROBADA, más PR #238 de P0 mergeada; migración ejecutada por Dani en su sesión bajo INFRA-523): lo que queda es la verificación viva formal (P6), la documentación pendiente (P7 runbook y nota de brain), el arreglo del sync Degraded de k8s-infra (INFRA-533), cerrar las historias ya cubiertas y no duplicar nada.

Relación con **DGX-188** (programa cuota, bajar el suelo ESO de 966/día): esta épica la **sustituye en lo estructural** — con Connect, las lecturas de ESO cuestan 0 cupo, así que el criterio (a) «suelo ESO» de DGX-188 pierde sentido para lecturas y su hueco (d) «consumidor no-ESO» lo cubre aquí INFRA-528 (agent-jake, op-secret y MCP a Connect, la hace Dani). Ninguna historia de este plan toca el ámbito de DGX-188; al cerrar INFRA-511 procede reevaluar/cerrar DGX-188 contra esta realidad (decisión de su pm/CTO, no de esta épica).

Repo: k8s-infra-pocharlies (tronco `main`, ArgoCD app `k8s-infra`, selfHeal, `prune: false`). Repos colaterales ya resueltos: k8s-gitops-pocharlies#492 (ignoreDifferences) y, para P5b/P7, k8s-openclaw-qwen36-pocharlies (chart hermes, tronco `deploy/prod`).

## Criterios de aceptación

Estado medido el 04-10 20:2x-20:3xZ desde esta sesión de plan (KUBECONFIG=~/.kube/config). Los marcados CUMPLE-EN-VIVO siguen necesitando la evidencia formal de su historia (70-qa.md) para el cierre.

- [ ] 1. Pod de Connect Ready y store `onepassword-connect` en Valid. **(CUMPLE EN VIVO)**
  Comando: `kubectl get pods -n onepassword-connect && kubectl get clustersecretstore onepassword-connect`
  Esperado: `onepassword-connect-… 2/2 Running` y `onepassword-connect Valid ReadWrite True`.
  Medido: 2/2 Running (4h51m), store Valid. Falta adjuntar la evidencia en la historia que lo cierre (INFRA-513/523).

- [ ] 2. Prueba previa de equivalencia: un ES `data` y un ES `dataFrom.extract` contra Connect producen el mismo hash que el Secret actual. **(pendiente del veredicto de qa en INFRA-514, Review)**
  Comando: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py get INFRA-514 70-qa.md /tmp/qa514.md --rol pm && head -1 /tmp/qa514.md`
  Esperado: cabecera con `Estado: PASA` y dentro la tabla clave/hash de los ES de prueba (los `*-infra511` vivos ya se borraron, la evidencia queda en los adjuntos).

- [ ] 3. Todos los ES que usaban `onepassword` leen de `onepassword-connect` y están Ready=True. **(CUMPLE EN VIVO)**
  Comando: `kubectl get es -A -o json | python3 -c "import json,sys,collections; d=json.load(sys.stdin); c=collections.Counter(i['spec'].get('secretStoreRef',{}).get('name','(sin store)') for i in d['items']); r=[i['metadata']['name'] for i in d['items'] if not any(x['type']=='Ready' and x['status']=='True' for x in i.get('status',{}).get('conditions',[]))]; print(dict(c)); print('no Ready:', r)"`
  Esperado: `onepassword-connect: 260`, cero ES en el store `onepassword`, `no Ready: []`.
  Medido: exactamente eso (los 15 «sin store» son ES de generador Password de hermes/control-nexus, no leen 1Password; 1 ES en kubernetes-cnpg).

- [ ] 3b. PushSecret: las 13 de hermes están Ready=True. **Criterio reescrito por decisión de architect** (comentario 22267 del 04-10 y nota-architect-pr236.md): Connect no implementa SecretExists, así que las PushSecret **se quedan en el store SDK `onepassword`** (escriben, gasto mínimo, updatePolicy IfNotExists); el P5b original (INFRA-518, pasarlas a Connect) se cancela o reescribe como «documentar la permanencia en SDK y medir su gasto residual».
  Comando: `kubectl get pushsecret -A -o json | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(1 for i in d['items'] if any(c['type']=='Ready' and c['status']=='True' for c in i.get('status',{}).get('conditions',[]))), '/', len(d['items']))"`
  Esperado: `13 / 13`. Medido: 13/13 Ready=True, store SDK `onepassword`.

- [ ] 4. `control-nexus`, `k8s-infra` y `hermes` sincronizan en ArgoCD sin errores de ExternalSecret. **(PARCIAL — falta k8s-infra)**
  Comando: `kubectl get applications -n argocd control-nexus k8s-infra hermes`
  Esperado: las tres `Synced Healthy`.
  Medido: control-nexus Synced/Healthy, hermes Synced/Healthy, **k8s-infra Synced/Degraded** (operationState Failed, «one or more synchronization tasks completed unsuccessfully (retried 5 times)», 0 recursos no sanos). Causa diagnosticada por sre (nota-sre-cupo.md): el store SDK `onepassword` en wave 0 nunca llega a Healthy y bloquea la wave 1. Lo arregla **INFRA-533**; sin eso este criterio no cierra.

- [ ] 5. Un reinicio de ESO y un force-sync masivo no mueven el contador de cupo (account read_write). **(pendiente — INFRA-519, P6)**
  Comando: `T=$(kubectl get secret onepassword-service-account -n external-secrets-operator -o jsonpath='{.data.token}' | base64 -d); OP_SERVICE_ACCOUNT_TOKEN=$T op service-account ratelimit` antes y después de `kubectl rollout restart deploy/external-secrets -n external-secrets-operator` + anotación force-sync en todos los ES.
  Esperado: USED de `account read_write` con delta 0 por las lecturas (las PushSecret en SDK pueden sumar chequeos de existencia residuales; se anotan, no invalidan). 
  Medido ahora: `account read_write 1000 220 780, reset en 21 h` — el cupo se recuperó y no se re-agotó tras la tormenta; sre verificó 0 líneas ratelimit/429 en 7.393 líneas de logs de Connect y ESO desde 15:53Z. Falta la prueba formal con restart+force-sync y su evidencia en 50-entrega/70-qa.

- [ ] 6. Documentado en el ClusterSecretStore y en la memoria del cupo. **(PARCIAL)**
  Hecho: comentario completo en `platform/external-secrets/cluster-secret-store-onepassword-connect.yaml` (sintaxis, bootstrap fuera de banda, rotación) y ARCHITECTURE.md §4 actualizado — ambos en origin/main (PR #236).
  Falta (INFRA-520, P7): `docs/runbook-1password-connect.md` (credenciales fuera de banda, rotación semanal, restauración) y la nota de cupo en brain.
  Comando: `cd ~/k8s/k8s-infra-pocharlies && git fetch origin && git show origin/main:docs/runbook-1password-connect.md | head -5`
  Esperado: el runbook existe en el tronco; hoy da error «path does not exist».

- [ ] 7. Cierre: cero hijos abiertos de la épica, cada historia cerrada con su evidencia o con razón nombrada (las cubiertas por INFRA-523/PR 236/492/238 se cierran como cubiertas; INFRA-518 cancelada o reescrita por 3b; INFRA-525 de seguimiento se desvincula o se deja con razón antes del Done de la épica).
  Comando: búsqueda Jira `parent = INFRA-511 AND statusCategory != Done` más `jira_rest.py attachments` de cada historia con su 70-qa.md.
  Esperado: vacío al cerrar, o cada abierta con su razón escrita.

## Restricciones

- **No abrir PRs que dupliquen lo mergeado**: #236 (Connect + store + policy de traducción + detector), #492 (ignoreDifferences de ArgoCD) y #238 (fuera la regla mutate-existing onchange-existing; ClusterRole borrado) ya están en sus troncos. Verificado en vivo: ClusterPolicy `externalsecret-onepassword-onchange` solo con regla `onchange-at-admission`; policy `externalsecret-onepassword-to-connect` viva con `split-item-field` + `switch-store`.
- **INFRA-528/529/530/531 las hace Dani** en su sesión (agent-jake, op-secret, MCP a Connect): no tocarlas.
- Credenciales de Connect (`op-credentials`) y token (`onepassword-connect-token`) **fuera de banda, nunca en git ni generadas por un ES**. Rotación del token a solo-lectura = SC-1790 (sesión semanal con Dani, etiqueta rotacion-semanal); rotación del SA viejo = SC-1749. Ninguna se hace en esta entrega.
- NetworkPolicy de Connect = SC-1791 (PR #239 abierta, security/it): fuera de este plan, no duplicar.
- No reintroducir mutateExisting sobre los ES: fue la causa del incidente del 03-10 (214 ES reescritos, 467 refs en 2 min, cupo a 0).
- GitOps: PR contra `main` (k8s-infra) o el tronco que lea ArgoCD en cada repo; el merge lo pulsa quien corresponda con los veredictos de qa/architect/pm.
- No borrar el store SDK `onepassword` ni su ClusterSecretStore en esta entrega: queda como respaldo de las PushSecret y por si Kyverno cae; su retirada es INFRA-525.
- Horas en UTC real (`date -u`).

## Trabajo reciente (24 h)

- 04-10 ~15:50-16:20Z, sesión interactiva de Dani (INFRA-523): merge de #236 y #492; migración con el cupo a 0 — 260 ES a onepassword-connect; comentario 22287 con el estado y los seguimientos (INFRA-525, SC-1790, SC-1791).
- 04-10 17:22-18:34Z, sesión tech-lead (10-plan.md, Plan v2 con C1-C9 del architect): historias P0-P7 despachadas; luego reconduce a no duplicar las PRs de Dani (comentario 22258); architect revisa 236 (CAMBIOS → resueltos), 492 (APROBADA) y 238 (APROBADA, mergeada a3b7c20).
- 04-10 18:07-19:50Z, sesión sre 985b9344 (nota-sre-cupo.md): el cupo NO se repitió tras #236; k8s-infra Degraded por store SDK en wave 0 (propone INFRA-533); detector de cupo nunca termina (propone INFRA-534); anexo 5: errores delete de Connect son ruido de doble-borrado.
- 04-10 18:52-20:02Z, INFRA-528 (Dani/developer): 529 y 531 en Review, architect APROBADA en PRs 27 y 646, falta qa.
- 04-10 ~16:51Z: PR #239 (SC-1791, NetworkPolicy de Connect) abierta en k8s-infra-pocharlies.
- 04-10 20:2x-20:3xZ, esta sesión de plan (pm 62004011): medición en vivo de los 7 criterios — 260/260 ES Ready en Connect, 13/13 PushSecret Ready en SDK, store Valid, policies vivas correctas, cupo 220/1000 recuperado, k8s-infra aún Degraded, runbook ausente.
- Sesiones vivas en la máquina ahora: hermes-edani-key y hermes-cb-uncensored (claude-tmux); múltiples transcripts de agentes en ~/k8s tocan INFRA-511/onepassword-connect en las últimas horas.

## Diseño

Diseñador: no — no hay interfaz; es infraestructura de clúster (servidor Connect, stores, policies de Kyverno, verificación y documentación).

## Historias previstas

Todas EXISTEN ya en Jira (no crear ninguna nueva); lo que queda por historia:

- INFRA-512 (P0, devops) — Review: PR #238 mergeada y aplicada en vivo; cerrar con la evidencia (policy viva sin onchange-existing, ClusterRole borrado).
- INFRA-513 (P1, devops) — In Progress: cubierta por PR #236 (Connect y store en GitOps); cerrar como cubierta con la evidencia del criterio 1.
- INFRA-514 (P2, devops/qa) — Review: falta el 70-qa.md PASA del criterio 2.
- INFRA-515 (P3, devops) — In Progress: cubierta por PR #236 (policy de traducción viva); cerrar como cubierta.
- INFRA-516 (P4, devops) — To Do: cubierta por k8s-gitops-pocharlies#492; cerrar como cubierta.
- INFRA-517 (P5, devops) — To Do: cubierta por la migración de Dani (INFRA-523); cerrar como cubierta.
- INFRA-518 (P5b, developer/devops) — To Do: **cancelar o reescribir** según criterio 3b (architect: Connect no implementa SecretExists; PushSecret se quedan en SDK).
- INFRA-519 (P6, sre) — To Do: verificación viva formal de los criterios 4 y 5 (restart de ESO + force-sync con delta 0 del contador); depende de INFRA-533 para el criterio 4.
- INFRA-520 (P7, writer + architect) — To Do: runbook-1password-connect.md y nota de cupo en brain (criterio 6; store y ARCHITECTURE.md ya hechos).
- INFRA-522/INFRA-523 (qa/despliegue de Dani) — 523 In Progress: vehículo de la migración ya mergeada; cerrar con qa.
- INFRA-533 (Task, devops/sre) — To Do: el store SDK caído no debe bloquear la wave 1 del sync de k8s-infra (causa del Degraded, criterio 4).
- INFRA-534 (Task, devops) — To Do: detector de cambios que nunca termina y métrica de cupo en VictoriaMetrics.
- INFRA-525 (seguimiento, pm/CTO) — To Do: reescribir ~30 repos al formato Connect y retirar traducción + store SDK. **Fuera de alcance de esta entrega** (lo dice la épica); al cerrar INFRA-511 hay que desvincularla a épica propia o dejar constancia de la razón, o bloquea el criterio 7.
- INFRA-528/529/530/531 — las ejecuta Dani; este plan no las toca ni las cierra.

Orden sugerido para el CTO: INFRA-533 → INFRA-519 (P6) en paralelo con INFRA-520 (P7) y el cierre de las cubiertas (512/513/515/516/517/522/523) y la cancelación/reescritura de INFRA-518; INFRA-514 cierra en cuanto qa adjunte su PASA. INFRA-534 puede quedar como Task propia fuera del camino crítico.

## Tamaño

M — el núcleo (Connect, store, traducción, ignoreDifferences, P0) ya está mergeado, desplegado y verificado en vivo por esta sesión; lo que queda es una prueba formal de cupo, un arreglo de waves del sync, dos documentos y el cierre administrativo de ~9 historias. No es S porque INFRA-533 toca el orden de sync de la app más grande (k8s-infra) y P6 exige mediciones antes/después con reinicio de ESO.

## Dificultad

Dificultad: alta — despliega y opera un servicio (1Password Connect) que maneja TODOS los secretos del clúster, con credenciales y token creados fuera de banda, y el trabajo pendiente toca el contador de cupo real (un force-sync mal hecho repite el incidente del 03-10) y el orden de sync de k8s-infra. La arquitectura ya está decidida y aprobada por architect (nota-architect-plan.md, C1-C9), así que no hay decisión arquitectural nueva, pero el manejo de secretos mantiene el criterio de alta.
