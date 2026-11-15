Rol: tech-lead · Fecha: 2026-09-18 · Sesión: a3f4f554-1272-44bb-83a4-fe1092df119e · Estado: LISTO

# 00-spec — Ruta de upgrade Longhorn 1.11.2 a la primera versión publicada con el fix

## Qué y por qué

Documentar, solo con documentación oficial de Longhorn, si el salto del chart 1.11.2 (estado
actual del clúster) a la primera versión publicada que incluya el fix del bug de pods zombie
tras reinicio de k3s (longhorn/longhorn#13723; fix longhorn-manager#5085, backport #5225 a la
rama v1.12.x el 13-09-2026) es directo o exige versión intermedia, y qué hace falta para
aplicarlo por GitOps. El dictamen VP exige esta verificación como historia propia ANTES del
bump (INFRA-166, en hold hasta 2026-09-23). Última versión publicada: v1.12.1 (sin el fix);
candidatas: v1.12.2 (sin fecha) o v1.13.0 (prevista 2026-09-23).

Preparación pura: cero cambios en el clúster, cero PRs, cero bump.

## Criterios de aceptación

- [ ] Adjunto `10-plan.md` en esta historia, elaborado SOLO con documentación oficial de Longhorn
      (docs.longhorn.io, release notes de github.com/longhorn, README del chart), con URL por afirmación
- [ ] Establece si el salto 1.11.2 a 1.12.x es directo o exige versión intermedia, con la fuente que lo determina
- [ ] Cubre el caso v1.13.0: si exigiría ruta distinta (salto doble 1.11 a 1.12 a 1.13), con fuente
- [ ] Incluye requisitos previos: compatibilidad k8s 1.36 / k3s, CSI, engine images, settings entre versiones
- [ ] Incluye los pasos exactos por Helm/GitOps para esta app ArgoCD multi-origen (bump de chart + values en infra/longhorn/values.yaml de k8s-gitops-pocharlies deploy/prod)
- [ ] Incluye rollback
- [ ] Incluye checklist de comprobaciones en el clúster ANTES de aplicar (listadas, sin ejecutar nada)
- [ ] Cero cambios en el clúster, cero PRs, cero bump de versión

## Cómo se verifica

qa abre `10-plan.md` y, criterio a criterio, comprueba que cada afirmación lleva URL de fuente
oficial y que las URLs citadas corresponden con lo afirmado (abrir las fuentes). El veredicto
(ruta directa o intermedia) debe citar la página de upgrade de docs.longhorn.io que lo fija.

## Contexto del entorno (para los pasos GitOps, no para ejecutar)

- App ArgoCD `longhorn`: multi-origen — chart de charts.longhorn.io + repo k8s-gitops-pocharlies
  rama deploy/prod con los values en `infra/longhorn/values.yaml`.
- Clúster: k3s v1.36.2+k3s1, 7 nodos. Chart actual: Longhorn 1.11.2.

## Rescate

Sesión CTO: a3f4f554-1272-44bb-83a4-fe1092df119e
Agente: agent-a8ea037d915feae5f
Reanudar la sesión: cd /home/dibanez/k8s/k8s-infra-pocharlies && claude --resume a3f4f554-1272-44bb-83a4-fe1092df119e
Continuar el subagente: desde esa sesión, SendMessage al agente agent-a8ea037d915feae5f
Transcript: /home/dibanez/.claude/projects/-home-dibanez-k8s-k8s-infra-pocharlies/a3f4f554-1272-44bb-83a4-fe1092df119e/subagents/agent-a8ea037d915feae5f.jsonl
