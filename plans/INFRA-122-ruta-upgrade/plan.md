Rol: tech-lead · Fecha: 2026-09-18 · Sesión: a3f4f554-1272-44bb-83a4-fe1092df119e · Estado: LISTO

# Plan — Ruta de upgrade Longhorn 1.11.2 → primera versión publicada con el fix (bajo INFRA-122)

Objetivo (CTO): preparación documental ANTES del bump (INFRA-166, hold hasta 23-09). No se toca
el clúster, no se abren PRs, no se hace bump. Fix de referencia: longhorn/longhorn#13723 (bug),
longhorn-manager#5085 (fix), backport #5225 a v1.12.x (13-09-2026). Última versión publicada con
el fix: ninguna (última v1.12.1); candidatas v1.12.2 (sin fecha) / v1.13.0 (prevista 2026-09-23).

## Partes (orden estricto — cada una depende de la clave de la anterior)

| # | Parte | Dueño | Producto | Verificación |
|---|---|---|---|---|
| 1 | Crear la historia bajo INFRA-122 con criterios comprobables, asignada a Daniel Ibanez Fernandez | pm | historia INFRA-xxx en Backlog, Epic Link INFRA-122 | la historia existe con los criterios `- [ ]` y el bloque Rescate |
| 2 | Adjuntar `00-spec.md` a la historia (brevete del developer; el guard lo exige antes de In Progress) | tech-lead | `00-spec.md` adjunto (contenido ya redactado en `00-spec.md` de esta carpeta) | `jira_rest.py attachments INFRA-xxx` lo lista |
| 3 | Investigar con documentación oficial y redactar/adjuntar `10-plan.md` + `50-entrega.md`; In Progress → Review | developer | `10-plan.md` adjunto con URL por afirmación; veredicto ruta directa o intermedia | `jira_rest.py attachments INFRA-xxx`; qa comprueba contra criterios |
| 4 | Verificación por criterio contra las fuentes citadas | qa | `70-qa.md` (PASA | NO PASA) | adjunto en la historia |

Hecho (objetivo global) = historia en Review/QA con `10-plan.md` que responde: 1.11.2→1.12.x
directo o intermedio (con fuente), caso v1.13.0 (doble salto o no), requisitos previos
(k8s 1.36/k3s, CSI, engine images, settings), pasos GitOps exactos para la app ArgoCD
multi-origen (charts.longhorn.io + k8s-gitops-pocharlies deploy/prod, `infra/longhorn/values.yaml`),
rollback, y checklist de comprobaciones previas (sin ejecutar).

## Riesgos

- Que las docs oficiales no digan nada explícito del trío 1.11→1.12→1.13 (versiones futuras):
  el developer debe citar lo que las docs digan y marcar como hipótesis lo que no, sin inventar.
- Que v1.12.2 nunca se publique y el fix llegue solo en v1.13.0: el plan debe cubrir ambas rutas.
- Bloqueante de harness actual: los despachos Agent del tech-lead en esta sesión están denegados
  (ver informe); las partes 1, 3 y 4 deben despacharse desde la sesión del CTO con los briefs
  de esta carpeta.
