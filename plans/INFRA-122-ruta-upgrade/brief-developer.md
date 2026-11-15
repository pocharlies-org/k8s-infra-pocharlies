# Brief developer — investigar y adjuntar 10-plan.md (después de que pm cree la historia)

Pegar como prompt en Agent(subagent_type: company-developer, run_in_background: false),
sustituyendo INFRA-XXX por la clave que devolvió pm.

---

Eres developer en la compañía. Historia: **INFRA-XXX** (proyecto INFRA, épica INFRA-122).
Primero lee el brevete: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py get INFRA-XXX 00-spec.md`
y trabaja contra sus criterios. Tarea: INVESTIGACIÓN DOCUMENTAL y redacción; no hay código.

Objetivo: establecer, SOLO con documentación oficial de Longhorn y con URL por afirmación, la
ruta de upgrade del chart 1.11.2 (estado actual del clúster) a la primera versión publicada que
incluya el fix del bug de pods zombie tras reinicio de k3s. Datos de partida: bug
longhorn/longhorn#13723; fix longhorn-manager#5085; backport longhorn-manager#5225 fusionado a
la rama v1.12.x el 13-09-2026; última versión publicada v1.12.1 (sin el fix); candidatas v1.12.2
(sin fecha) o v1.13.0 (prevista 2026-09-23).

El documento `10-plan.md` debe responder, cada afirmación con su URL:

1. Ruta 1.11.2 → 1.12.x: directa o versión intermedia obligatoria. Fuente: guía de upgrade de
   docs.longhorn.io (versión 1.12.x).
2. Caso v1.13.0: si exigiría ruta distinta (doble salto 1.11 → 1.12 → 1.13) o la misma regla.
3. Qué versión publicada contendrá el fix: comprueba en github.com/longhorn (releases, milestone
   de #5085/#5225) si v1.12.2 existe ya o el fix solo puede llegar en v1.13.0. Si ninguna está
   publicada, dilo tal cual.
4. Requisitos previos: compatibilidad del chart 1.12.x/1.13.x con Kubernetes v1.36 (k3s
   v1.36.2+k3s1), requisitos de CSI, procedimiento de engine image (desplegar, por defecto), y
   cambios de settings/defaults entre 1.11 y 1.12/1.13 que afecten al upgrade.
5. Pasos exactos Helm/GitOps para ESTE despliegue: app ArgoCD `longhorn` multi-origen (chart de
   charts.longhorn.io + repo k8s-gitops-pocharlies rama deploy/prod con values en
   `infra/longhorn/values.yaml`). Lee SOLO en lectura ese repo local (~/k8s/k8s-gitops-pocharlies)
   para ajustar los pasos al layout real (dónde se fija la versión del chart). Secuencia:
   comprobaciones previas → bump → rollout de engine image → ponerla por defecto → verificación.
6. Rollback (lo que la documentación oficial diga de downgrades; si no lo soportan, dilo con la fuente).
7. Checklist de comprobaciones en el clúster ANTES de aplicar (comandos listados, NO ejecutados).

Fuentes admitidas: docs.longhorn.io (docs versionadas por rama), release notes de
github.com/longhorn/*, README del chart (github.com/longhorn/charts o artifacthub). Carga
WebFetch/WebSearch con ToolSearch si están diferidas. Si una página no carga o no dice lo que
necesitas, dilo TAL CUAL en el doc (sección "sin fuente"): NO inventes citas ni infieras de
memoria lo que las docs no digan; marca explícitamente toda hipótesis como hipótesis.

Restricciones duras: no ejecutar NADA contra el clúster (ni kubectl ni helm, ni lectura del
cluster); no abrir PRs; no modificar ningún repo; no tocar otras historias.

Entrega:
- Escribe el doc con cabecera exacta: `Rol: developer · Fecha: 2026-09-18 · Sesión: a3f4f554-1272-44bb-83a4-fe1092df119e · Estado: LISTO`
- Antes de nada: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py gate INFRA-XXX "In Progress"` y, si pasa, transiciona a In Progress (jira_transition_issue, servidor MCP local atlassian).
- Adjunta: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py attach INFRA-XXX <fichero> --as 10-plan.md` (el CLI acepta 10-plan.md en historias; verificado).
- Adjunta también `50-entrega.md` (qué se hizo, checklist de 00-spec.md marcada, PR: ninguno — es documentación) y transiciona a Review (gate primero).
- Informe: veredicto de ruta (directa o intermedia, y para 1.13.0) con la URL decisiva por
  afirmación, lista de adjuntos (salida de `jira_rest.py attachments INFRA-XXX`), y cualquier
  fuente no alcanzable con el error tal cual.
