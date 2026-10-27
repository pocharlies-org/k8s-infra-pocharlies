# Brief devops — PR runbook CONGELACION (despachar con Agent(subagent_type: company-devops, run_in_background: false))

Pegar como prompt (autocontenido). El merge lo pulsa el CTO.

---

Eres devops en la compañía. Tarea única y acotada: UNA PR de documentación al repo
**k8s-infra-pocharlies** (checkout único y source of truth:
`/home/dibanez/k8s/k8s-infra-pocharlies`; tronco `main`). No toques el clúster: nada de
kubectl/helm. No merges: el merge lo pulsa el CTO — tu entrega es rama + PR.

Contexto: épica INFRA-122 (Jira, proyecto INFRA): bug longhorn/longhorn#13723 — tras reiniciar
k3s, los pods con PVC Longhorn quedan Running pero 0/N Ready (FailedMount "no Pending workload
pods"). El VP ha dictado hoy 18-09-2026 congelar preventivamente el reinicio de k3s/kubelet en
los control-planes hasta tener el fix aplicado y verificado (registrado en la épica: adjunto
nota-cto-congelacion-ks5.md y etiqueta parked-hasta-2026-09-23).

Qué hacer:
1. `git fetch` y trabaja desde `origin/main`. Comprueba si existe
   `docs/runbook-longhorn-zombie-pods-k3s-restart.md` en main. Si existe, AÑADELE una sección
   nueva; si NO existe, créalo con un título breve (runbook del escenario zombie pods tras
   reinicio de k3s, épica INFRA-122) y la sección, y dilo explícitamente en el informe.
2. Título exacto de la sección: `## CONGELACION (decision VP 18-09-2026)`. La sección debe decir,
   con estas palabras o equivalentes fieles:
   - Prohibido reiniciar k3s/kubelet en `ks5-cp-1`, `ks5-cp-2`, `ks5-cp-3` hasta que el fix de
     longhorn/longhorn#13723 esté aplicado por GitOps (bump del chart longhorn que lo incluya) y
     verificado con el pod de prueba: mismo pod y UID, sin bucle de `MountVolume.SetUp`.
   - Única excepción: reinicio inevitable (p. ej. parche de seguridad) en ventana acordada, con
     recuperación preparada (este runbook) y aviso previo al VP.
   - La congelación se levanta solo con el criterio 3 de la épica medido (verificación con el pod
     de prueba). Referencia: épica INFRA-122, adjunto `nota-cto-congelacion-ks5.md`, etiqueta
     `parked-hasta-2026-09-23`.
3. Rama nueva (p. ej. `infra-122-congelacion-runbook`), commit convencional
   (`docs(runbook): CONGELACION preventica de reinicio k3s en ks5-cp (INFRA-122)`) con las líneas
   de atribución de tu sesión al final del mensaje. `git push` de TU rama (nunca el tronco) y
   `gh pr create` contra `main`. Cuerpo de la PR: referencia `INFRA-122` y una línea de que es
   solo documentación.
4. Si el CI falla, informa tal cual; NO hagas merge aunque esté verde.

Informe (exacto): URL de la PR; si el fichero ya existía o se creó; diff de la sección añadida
(máx. 15 líneas); salida de `gh pr view --json state,mergeable` o equivalente; errores tal cual.
