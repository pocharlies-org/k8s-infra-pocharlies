Rol: tech-lead · Fecha: 2026-09-18 · Sesión: a5b648df-3f6e-444f-aac4-e582baafc2a8 · Estado: LISTO

# 00-spec — Retiro espejo + 3 sueltos (SC-490/SC-496, fase 6)

Contexto: /home/dibanez/k8s/_ops/vault-to-1password/ (README, huerfanos/README.md con las
tablas del guion, fase6-evidencia/). FALLO DEL CTO: el espejo onepassword-sync (op→Vault)
se RETIRA — sin lectores tras fusionarse k8s-infra#140 y muere con Vault. Solo lectura en
clúster; nada de apply/patch/merge.

## Encargo 1 — PR de retiro del espejo (k8s-infra, tronco main)

- Localizar el manifiesto del espejo: `platform/external-secrets/onepassword-sync.yaml`
  (los ES `*-from-op` que sincronizan 1Password→Vault; posiblemente también
  PushSecret/otro mecanismo — `git grep -n onepassword-sync` y leer el fichero entero).
- PR que RETIRA los manifiestos del espejo por git. Prune: mirar la Application que
  despliega ese manifiesto (`kubectl get application -n argocd <app> -o
  jsonpath='{.spec.syncPolicy}'`) — si `prune: false`, borrar de git NO borra los objetos
  vivos: la descripción del PR debe llevar el comando EXACTO de borrado que quedará para
  el operador (y añadirlo a fase6-evidencia/OPERADOR-FINAL.md como ítem nuevo, numerado,
  con el comando). Si prune:true, el PR basta.
- Consecuencia que debe constar en la descripción: al cesar el espejo, Vault queda
  CONGELADO (deja de recibir re-frescos desde 1Password) — aceptado por el CTO porque
  Vault muere en fase 6; el guion de verificación del espejo (Skirmshop) queda como
  snapshot del momento del cese.
- Comentarios rancios: los del propio onepassword-sync.yaml que describen consumidores
  vault-backend viajan borrados con el fichero; verificar que no queden referencias
  colgantes: `git grep -n vault-backend` en la rama tras el PR debe dejar solo lo que el
  guion del operador aún no cubre.
- Rama `sc490-retiro-espejo`; commit "chore(external-secrets): retire onepassword→Vault
  mirror (SC-490)" + Co-Authored-By; PR contra el tronco que lee la Application.

## Encargo 2 — los 3 ES sin dueño CES

`agentgateway` (ns agentgateway?), `skirmshop-brain-prod`,
`skirmshop-product-relations/harbor-runtime-pull`. Para cada uno:

- `kubectl get es -A` para ns/nombre exacto y su storeRef vivo.
- Localizar el manifiesto en ~/k8s (grep del nombre).
- Comprobar si está en el guion de 28 (huerfanos/: ¿hay manifiesto en migrados/ y está
  listado en APLICAR.md?).
- Si ESTÁ en el guion → reportar y no tocar.
- Si NO está y su storeRef es vault-backend → PR de traducción (storeRef onepassword,
  item/campo del mapping*.tsv o del op item que corresponda — verificar el campo con
  `_ops/vault-to-1password/op-sa.sh op item get <item> --fields label`, cero escrituras),
  refreshInterval 6h, contra el tronco que lee su Application.
- Si el item/campo NO existe en 1Password → NO PR, reportar como falta de contenido (con
  la ruta Vault que lee hoy) para decidir.

## Criterios de aceptación

- [ ] PR de retiro abierto contra main, con prune de la Application medido y, si
      prune:false, comando exacto de operador en la descripción + ítem numerado añadido a
      OPERADOR-FINAL.md.
- [ ] Consecuencia «Vault CONGELADO» y snapshot del guion Skirmshop constan en la
      descripción del PR.
- [ ] `git grep -n vault-backend` en la rama deja solo lo no cubierto por el guion.
- [ ] Los 3 ES sin dueño CES: identificados ns/nombre/storeRef vivos, clasificados (en
      guion / PR abierto / falta de contenido) con evidencia.

### Rescate
Sesión CTO: a5b648df-3f6e-444f-aac4-e582baafc2a8
Agente: agent-a53b020ff21c748c1
Reanudar la sesión: cd /home/dibanez/k8s/k8s-infra-pocharlies && claude --resume a5b648df-3f6e-444f-aac4-e582baafc2a8
Continuar el subagente: desde esa sesión, SendMessage al agente agent-a53b020ff21c748c1
Transcript: /home/dibanez/.claude/projects/-home-dibanez-k8s-k8s-infra-pocharlies/a5b648df-3f6e-444f-aac4-e582baafc2a8/subagents/agent-a53b020ff21c748c1.meta.json
