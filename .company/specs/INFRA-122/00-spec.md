Rol: pm · Fecha: 2026-09-26T01:49:26+00:00 · Sesión: c2e9cff8-1823-4415-814c-533a4ea26ec1 · Estado: ESPERA

# INFRA-122 — Longhorn v1.11.2: tras reiniciar k3s, los pods con PVC quedan Running pero 0/N Ready (FailedMount "no Pending workload pods")

## Objetivo
Que un reinicio de k3s/kubelet en un nodo ks5-cp no deje pods con volumen Longhorn zombis (Running 0/N Ready, bucle `MountVolume.SetUp` "no Pending workload pods"). El diagnóstico y toda la preparación están HECHOS (ver abajo); lo único que falta es la release upstream que contiene el fix, que a fecha 26-09-2026 todavía no está publicada — la épica queda aparcada con wake 2026-10-03.

Repo: k8s-gitops-pocharlies (donde vive el pin del chart: `infra/longhorn.yaml`, tronco que lee ArgoCD = `deploy/prod`; el runbook vive en k8s-infra-pocharlies `main`)

## Espera
Qué se espera: una release publicada de Longhorn que contenga el fix — chart `1.12.2` (backport oficial, milestone del backport #13995) o `1.13.0` (fix original, hoy en rc4) en `https://charts.longhorn.io`.

Cómo se comprueba (comando exacto):
```
curl -s https://charts.longhorn.io/index.yaml | grep -oE 'version: 1\.(12\.[2-9]|13\.[0-9]+)' | sort -Vu
```
- Salida vacía → sigue la espera, aparcar 7 días más (máx. 14).
- Cualquier versión listada → la espera terminó: el CTO arranca con el bump a la MÁS BAJA de las listadas (preferir 1.12.x sobre 1.13.x: salto de patch, no de minor) y el resto de criterios ya están preparados.

Complemento al comprobar la espera: confirmar que la imagen del app coincide (`gh api repos/longhorn/longhorn-manager/tags --jq '.[].name' | grep -E '^v1\.12\.2$|^v1\.13\.0$'`).

Revisar: 2026-10-03

## Lo que ya está hecho (no repetir)
- **Criterio 1 (diagnóstico upstream): CERRADO.** Bug upstream `longhorn/longhorn#13723`; fix `longhorn/longhorn-manager#5085` ("fix(csi): ignore terminal workloads in NodePublishVolume"), mergeado a `master`/`v1.13.x` el 21-08-2026 y **backporteado a `v1.12.x` el 13-09-2026** (backport issue `longhorn/longhorn#13995`, milestone v1.12.2, cerrado 14-09). Medido hoy 26-09 con `gh api`. Falta solo colgar el comentario-enlace en la épica al ejecutar (el histórico está en el adjunto `comentarios-historico.md`).
- **GOTCHA: el chart 1.11.3 existe en charts.longhorn.io pero NO contiene el fix** — la rama `v1.11.x` no recibió el backport (último commit de `csi/node_server.go` en v1.11.x: 23-04-2026, medido hoy). No hacer bump a 1.11.3.
- **Runbook merged** (criterio 4, base): `docs/runbook-longhorn-zombie-pods-k3s-restart.md` en `origin/main` de k8s-infra-pocharlies (PR #117, 18-09). Hay que actualizarlo con la versión que arregla al hacer el bump (hoy dice "no published release contains the fix", cierto a 13-09).
- **Fixture de reproducción preparado** en k8s-gitops `deploy/prod`: `infra/longhorn-zombie-test/` (namespace + PVC RWO + deployment con `nodeSelector: kubernetes.io/hostname: ks5-cp-3`).
- **Dictamen VP 18-09**: congelar reinicios de k3s en ks5-cp-1/2/3 hasta el bump verificado (política, registrada en la épica: `nota-cto-congelacion-ks5.md`). Ventana de reproducción acordada: ks5-cp-3, ≤15 min, fuera de hora punta, solo con Longhorn Synced/Healthy y sin volúmenes Degraded.
- **Estado vivo medido 26-09**: Longhorn `1.11.2` (chart y `longhorn-manager:v1.11.2`), app ArgoCD `longhorn` multi-origen (chart charts.longhorn.io + values k8s-gitops `deploy/prod`), pin en `infra/longhorn.yaml:35` (`targetRevision: 1.11.2`).

## Criterios de aceptación
Cada criterio se responde met o no met con la evidencia que se indica; un criterio sin evidencia no se cumple.

- [ ] 1. Diagnóstico upstream: un comentario en la épica enlaza longhorn/longhorn#13723, longhorn/longhorn-manager#5085 y el backport #13995 (milestone v1.12.2), afirmando qué versión publicada lo contiene. Comando de evidencia: `python3 ~/.local/libexec/x86-host-runtime/jira_rest.py progreso INFRA-122 --rol devops --paso "criterio 1"` con los tres enlaces; salida esperada: comentario creado (el contenido ya está verificado en "Lo que ya está hecho").
- [ ] 2. Fix aplicado por GitOps: PR a k8s-gitops-pocharlies `deploy/prod` cambiando `infra/longhorn.yaml` `targetRevision: 1.11.2` → la versión publicada con el fix; ArgoCD lo aplica; ningún cambio imperativo. Comando de evidencia: `kubectl get application -n argocd longhorn -o jsonpath='{.spec.sources[0].targetRevision} {.status.sync.status} {.status.health.status}'` → salida esperada: `<nueva> Synced Healthy`, y `kubectl get pods -n longhorn-system -l app=longhorn-manager -o jsonpath='{.items[0].spec.containers[0].image}'` → `...v1.12.2` (o la versión fijada).
- [ ] 3. Reproducción superada (ventana acordada, nodo ks5-cp-3, dictamen VP 18-09: ≤15 min fuera de hora punta, solo con el bump Synced/Healthy y sin volúmenes Degraded): tras reiniciar k3s en ks5-cp-3, el pod de `infra/longhorn-zombie-test` vuelve a N/N Ready solo, sin borrarlo. Evidencia pegada: mismo nombre y UID antes y después (`kubectl get pod -n longhorn-zombie-test -o jsonpath='{.items[0].metadata.name}{.items[0].metadata.uid}'`), `kubectl get pod -n longhorn-zombie-test` → `1/1 Running`, y `kubectl get events -n longhorn-zombie-test --field-selector reason=FailedMount` → vacío tras el reinicio (sin bucle `MountVolume.SetUp`). El reinicio lo ejecuta el maker dentro de la ventana con el runbook del nodo; no es reinicio improvisado.
- [ ] 4. Runbook actualizado: `docs/runbook-longhorn-zombie-pods-k3s-restart.md` (k8s-infra-pocharlies `main`, ya existe vía PR #117) nombra la versión publicada que arregla y el procedimiento de recuperación si reaparece. Comando de evidencia: `git -C ~/k8s/k8s-infra-pocharlies show origin/main:docs/runbook-longhorn-zombie-pods-k3s-restart.md | grep -E 'v1\.12\.2|v1\.13\.0'` → al menos una línea.
- [ ] 5. Restricciones respetadas: backup verificado ANTES de tocar Longhorn citando la evidencia del sistema de backups (`docs/runbook-longhorn-systembackup.md` / SystemBackup último BackingUp=Complete: `kubectl get backups.longhorn.io -n longhorn-system` pegado), y ningún pod borrado a mano en `openclaw-qwen36`.
- [ ] 6. Documentación: cada criterio cumplido nombra el documento que queda reflejando el resultado, o dice en una línea explícita que no hacía falta actualizar ninguno. Silencio no es respuesta.

## Restricciones
- Longhorn solo por GitOps (ArgoCD); ningún cambio imperativo. El pin vive en k8s-gitops-pocharlies `deploy/prod` (`infra/longhorn.yaml`), NO en k8s-infra.
- Backup verificado antes de tocar Longhorn (competencia del sistema de backups; citar su evidencia).
- En `openclaw-qwen36` no se borran pods a mano (VAP y runbook del approval bundle).
- Ventana de reproducción: ks5-cp-3, ≤15 min, fuera de hora punta, con Longhorn Synced/Healthy y sin volúmenes Degraded (dictamen VP 18-09). Congelación de reinicios k3s en ks5-cp vigente hasta el bump verificado.
- No bump a 1.11.3 (no contiene el fix — ver GOTCHA arriba). Preferir la 1.12.x publicada sobre 1.13.x.

## Trabajo reciente (24 h)
- Nada en 24 h que afecte a este plan más allá del reanálisis pedido: 26-09 00:40Z Dani mueve la épica a Backlog para rehacer el 00-spec con las reglas nuevas (nadie espera, criterios con fixture, autopilot) — este spec lo hace. Sesión CTO anterior (a3f4f554) soltada; no hay sesión viva trabajando en Longhorn (radar 26-09). Medición fresca de hoy: fix en v1.12.x (backport #13995 cerrado 14-09), chart publicado topa en 1.12.1, v1.13.0 en rc4 — la espera sigue viva pero su final es inminente.

## Diseño
Diseñador: no — sin interfaz: es un bump de versión por GitOps, una reproducción en nodo y un runbook.

## Historias previstas
- H1 bump del chart Longhorn 1.11.2 → 1.12.2 (o 1.13.0) por PR a k8s-gitops `deploy/prod` + ver ArgoCD Synced/Healthy (dueño: devops).
- H2 reproducción del escenario en ks5-cp-3 dentro de la ventana acordada con el fixture `infra/longhorn-zombie-test` ya desplegado (dueño: devops; la ventana la coordina el CTO con el operador, dictamen VP 18-09).
- H3 actualizar el runbook con la versión que arregla + comentario de diagnóstico en la épica (dueño: devops; puede ir en el mismo PR de H1 el runbook en k8s-infra).
- H4 veredicto qa (criterios 2-3 con evidencia pegada) y cierre pm (dueño: qa + pm).

## Tamaño
S — el análisis, el runbook y el fixture ya están hechos y medidos; queda un bump de una línea, un sync, una reproducción de 15 min y actualizar un markdown. Bloqueado solo por la release upstream (ver ## Espera).

## Dificultad
Dificultad: alta — la épica ya se atascó antes (dos parkings, sesión CTO soltada, reanálisis del 26-09) y el resto es un upgrade de almacenamiento compartido en producción con ventana de reinicio de un control-plane.
