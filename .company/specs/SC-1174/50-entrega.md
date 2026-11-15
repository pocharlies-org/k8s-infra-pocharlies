Rol: devops · Fecha: 2026-09-18 · Sesión: a5b648df-3f6e-444f-aac4-e582baafc2a8 · Estado: LISTO

# 50-entrega — Retiro espejo + 3 sueltos

## Encargo 1 — retiro del espejo (PR abierto)

- PR: https://github.com/pocharlies-org/k8s-infra-pocharlies/pull/144 (rama
  `sc490-retiro-espejo` → `main`, tronco que lee la Application `k8s-infra`:
  path `.`, targetRevision main — medido). Borra
  `platform/external-secrets/onepassword-sync.yaml` (Namespace + 4 ES `*-from-op` + 4
  PushSecret `*-to-vault`) y su línea del `kustomization.yaml`; 283 deletions, 0 additions.
- Prune medido: Application `k8s-infra` → `{"automated":{"prune":false,"selfHeal":true}}`.
  Borrar de git NO borra los vivos → comando exacto en la descripción del PR y **ítem g)
  añadido** a `/home/dibanez/k8s/_ops/vault-to-1password/fase6-evidencia/OPERADOR-FINAL.md`:
  `kubectl delete namespace onepassword-sync` (+ verificación NotFound). Medido 18-09: el
  ns contiene exactamente los 4 ES + 4 PushSecret + 4 Secret del espejo y nada más.
- Consecuencia en la descripción del PR: Vault CONGELADO al cesar el espejo (sin más
  re-frescos op→Vault), aceptado (Vault muere en fase 6); el cotejo Skirmshop
  (OPERADOR-FINAL ítem f) queda como snapshot del momento del cese (así se anotó también
  en el propio ítem f).
- Premisa verificada: k8s-infra#140 (CES del piloto → onepassword) MERGED 2026-09-18T01:34Z;
  en la rama `git grep 'op/infra-harbor|op/skirmshop-catalog|op/minio-backup|op/skirmshop-drive'`
  → sin lectores. Cero referencias a `onepassword-sync` restantes.
- Comentarios rancios: los del fichero viajan borrados. `git grep -n vault-backend` en la
  rama deja solo: `docs/runbook-sauvage-longhorn-attach-only-codex-home.md` ×2 (histórico,
  no lo cubre el guion; el store muere en fase 6) y el comentario ya actualizado de
  `platform/keycloak-next/chat-agentgateway-client.yaml:12` (lo cubre el ítem c del guion).
- Verificación: `kubectl kustomize .` en la rama rc=0, 13308 líneas, 0 referencias al espejo.

## Encargo 2 — los 3 ES sin dueño CES: los tres ya en onepassword; CERO PRs

Medidos vivos (`kubectl get es -A` + ownerRefs) y en el tronco de sus repos:

1. **agentgateway/agentgateway-backend-tokens** (la duda del CTO era el ns): ownerRef
   ninguno (sin CES), vivo store `onepassword` 6h SecretSynced. Git:
   `k8s-agentgateway-pocharlies` trunk `k8s/base/externalsecret.yaml` ya `onepassword`
   (item `agentgateway-prod`, 10 campos). No está en el guion (en `migrados/` solo hay el
   de agentgateway-**stg**). → Ya migrado, sin acción.
   Nota: el tocayo `agentgateway-stg/agentgateway-backend-tokens` (vault-backend 1h) SÍ
   está en el guion (`migrados/agentgateway-stg__agentgateway-backend-tokens.yaml`,
   APLICAR 2a) → reportado, no tocado. El ns agentgateway-stg no tiene Application ArgoCD
   (medido: NotFound), por eso es huérfano de apply a mano.
2. **skirmshop-brain-prod/harbor-runtime-pull**: ownerRef ninguno, vivo `onepassword` 6h
   SecretSynced. Git: `skirmshop-brain-k8s` trunk
   `apps/brain/overlays/prod/harbor-imagepullsecret.externalsecret.yaml` ya `onepassword`.
   No está en el guion (en `migrados/` de ese ns solo hay el `skirmshop-drive-s3-app`, hijo
   del CES piloto ya convergido — el CES `skirmshop-drive-s3-app` vivo está en onepassword).
   Los demás ES del ns (brain-reembed-telegram, ghcr-pocharlies-org-readonly,
   skirmshop-brain-secrets) también están todos en `onepassword` vivos. → Ya migrado, sin
   acción.
3. **skirmshop-product-relations/harbor-runtime-pull**: ownerRef ninguno, vivo
   `onepassword` 6h SecretSynced. Git: `skirmshop-brain-k8s` trunk
   `apps/brain/overlays/prod/staged-product-relations/harbor-imagepullsecret.externalsecret.yaml`
   ya `onepassword`. No está en el guion. → Ya migrado, sin acción.

Evidencia de que los items/campos existen en 1Password: los tres ES están `SecretSynced
True` contra el store `onepassword` (medido vivo) — no hizo falta `op item get` porque no
se abrió ningún PR de traducción.

## Checklist 00-spec

- [x] PR de retiro abierto contra main, prune medido (false) + comando exacto en la
      descripción + ítem g) en OPERADOR-FINAL.md.
- [x] Vault CONGELADO + snapshot Skirmshop constan en la descripción del PR.
- [x] `git grep -n vault-backend` en la rama deja solo lo no cubierto por el guion
      (runbook histórico) + el comentario de keycloak ya actualizado (cubierto por ítem c).
- [x] Los 3 ES sin dueño CES clasificados: los tres ya en `onepassword` (git+live), cero
      PRs, cero faltas de contenido.

## Cómo verificar

- `gh pr view 144 --repo pocharlies-org/k8s-infra-pocharlies` — diff: borrado del fichero
  + línea del kustomization.
- `kubectl get application -n argocd k8s-infra -o jsonpath='{.spec.syncPolicy}'` → prune:false.
- `kubectl get es -n agentgateway agentgateway-backend-tokens -o jsonpath='{.spec.secretStoreRef.name}'` → onepassword (igual ns skirmshop-brain-prod y skirmshop-product-relations).

### Rescate
Sesión CTO: a5b648df-3f6e-444f-aac4-e582baafc2a8
Agente: agent-a53b020ff21c748c1
Reanudar la sesión: cd /home/dibanez/k8s/k8s-infra-pocharlies && claude --resume a5b648df-3f6e-444f-aac4-e582baafc2a8
Continuar el subagente: desde esa sesión, SendMessage al agente agent-a53b020ff21c748c1
Transcript: /home/dibanez/.claude/projects/-home-dibanez-k8s-k8s-infra-pocharlies/a5b648df-3f6e-444f-aac4-e582baafc2a8/subagents/agent-a53b020ff21c748c1.meta.json
