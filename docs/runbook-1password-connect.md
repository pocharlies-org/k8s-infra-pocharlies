# Runbook — 1Password Connect (INFRA-511)

Qué es Connect en este clúster, cómo se arranca sin git, qué hacer si cae y qué no tocar.
Las manifestaciones viven en `platform/onepassword-connect/` y el store en
`platform/external-secrets/cluster-secret-store-onepassword-connect.yaml` — léanse antes de
actuar; este runbook no las duplica.

## Qué es y por qué existe

1Password Connect es un servidor en el clúster (ns `onepassword-connect`, imagen 1.8.2 espejada
en Harbor) que mantiene una copia local del vault `k8s-pocharlies`. External Secrets Operator
lee a través del ClusterSecretStore `onepassword-connect` y **cada lectura sale de la copia
local: no gasta cupo** (comentario de `platform/onepassword-connect/connect.yaml`).

El cupo: la cuenta es Families — 1.000 peticiones de service-account por 24 h para toda la
cuenta, y una relectura completa de los ExternalSecrets del clúster cuesta aproximadamente eso
mismo (`connect.yaml`). El incidente del 03-10: el store SDK viejo agotó el cupo — condición
del PushSecret `hermes-api-key-analista` «failed to list vaults: rate limit exceeded» a las
10-03T22:28Z, y el store `onepassword` quedó en `InvalidProviderConfig` desde las
10-03T19:13Z (nota-sre-cupo.md de INFRA-511, §1 y §3).

Medido tras el merge de la PR 236 (04-10, nota-sre-cupo.md): el cupo **no se repitió** — 0
líneas `ratelimit`/`429` en los 7.393 registros del Connect y 0 menciones del SDK en los logs
del operador desde las 15:53Z; las ~260 relecturas de la tormenta del merge cayeron sobre la
copia local. Matiz observado: cada «account sync» completo de `connect-sync` sí gasta cupo (3
entre 16:44 y 16:45Z) — vigilar la frecuencia.

## Credenciales de arranque: fuera de banda, nunca en git

Connect es lo que permite a ESO leer 1Password, así que sus credenciales **no pueden venir de
1Password a través de ESO** (circularidad). Son dos Secrets creados a mano y sin ExternalSecret
que los gestione:

| Secret | namespace | clave | cómo se crea | copia de respaldo |
|---|---|---|---|---|
| `op-credentials` | `onepassword-connect` | `1password-credentials.json` | `op connect server create k8s-pocharlies-connect --vaults k8s-pocharlies` (el fichero que imprime) | documento «1Password Connect k8s-pocharlies-connect - credentials» en el vault Private |
| `onepassword-connect-token` | `external-secrets-operator` | `token` | `op connect token create eso-k8s --server k8s-pocharlies-connect --vault k8s-pocharlies` | documento «1Password Connect k8s-pocharlies-connect - token eso-k8s» en el vault Private |

Fuentes: comentario de `platform/onepassword-connect/connect.yaml` y comentario de
`platform/external-secrets/cluster-secret-store-onepassword-connect.yaml`.

El token de ESO es hoy de lectura y escritura, más de lo que ESO necesita (las PushSecret se
quedan en el store SDK): recrearlo de solo lectura es tarea de la rotación semanal.

## Rotación

Rotar el token o las credenciales **no se hace en el día**: es Task con etiqueta
`rotacion-semanal` y se hace en la sesión semanal de Dani con security (SC-1790). Regla de
`~/.claude/CLAUDE.md` («Rotaciones de credenciales»). Reparar una credencial rota que bloquea
trabajo (borrada, caducada) no es rotación: se repara al momento recreándola desde la copia
del vault Private.

## Recuperación tras reconstruir el clúster

Hay una circularidad que ya está resuelta: Harbor lee sus propios secretos por Connect y la
imagen de Connect está en Harbor. Con un clúster en marcha no se rompe nada (los Secrets
existen y la imagen está cacheada). En reconstrucción total, seguir
`docs/disaster-recovery.md` § «1Password Connect»: arrancar **sin** la policy Kyverno
`externalsecret-onepassword-to-connect` (así los ES leen del store SDK, que gasta el cupo: una
lectura completa ≈ el día entero) o pre-cargar las imágenes de Connect, recrear los dos Secrets
fuera de banda de la tabla de arriba y volver a añadir la policy.

## Si Connect cae

- El Deployment es de réplica única: SPOF aceptado a propósito (nota-architect-plan.md de
  INFRA-511, P1). Mientras Connect esté caído, ESO no puede refrescar, pero **conserva el
  último valor de cada Secret**: los Secrets del clúster no desaparecen.
- Al reiniciar el pod, `connect-sync` reconstruye la copia desde cero (volumen `emptyDir`, sin
  PVC — `connect.yaml`). No añadir PVC ni réplicas sin decisión de arquitectura.
- Comprobación: `kubectl get pods -n onepassword-connect` y
  `kubectl get clustersecretstore onepassword-connect -o jsonpath='{.status.conditions}'`
  (esperado `Valid=True`; estado de referencia medido el 04-10, nota-sre-cupo.md §3).
- Con Connect caído, **no** hacer `force-sync` masivo de los ES: los que aún conservan forma
  SDK (store `onepassword`) volverían al proveedor real y gastarían cupo; los ya traducidos a
  Connect fallan sin coste. (Razonado sobre lo medido en nota-sre-cupo.md §2; no probado como
  escenario de caída — hipótesis.)

## Cómo leen los ExternalSecrets hoy (04-10)

- ~260 de los 275 ES del clúster leen del store `onepassword-connect` (nota-sre-cupo.md §2).
- Los ES escritos en forma SDK (`key: item/campo`) los traduce en admisión la ClusterPolicy
  Kyverno `externalsecret-onepassword-to-connect` a `key: item` + `property: campo`, store
  `onepassword-connect`, hasta que los ~30 repos se reescriban (INFRA-525). Los ES nuevos
  deben escribirse ya en forma Connect. Fuentes: ARCHITECTURE.md §4 y comentario del store.
- Las PushSecret de Hermes (13 según la spec de INFRA-520; nota-architect-plan.md dice 12 —
  sin recuento propio en esta sesión, `kubectl` no está en el mapa del writer) se quedan en el
  store SDK `onepassword`: el proveedor Connect no implementa `SecretExists`, que necesitan con
  `updatePolicy: IfNotExists` (nota-architect-pr236.md, C2). El store SDK sigue vivo por ellas
  y gastan cupo: su refresco (24 h) más el `onepassword-change-detector`, que cada 4 h hace
  force-sync de lo que cambió con 1–2 peticiones SDK por pasada (nota-architect-pr236.md,
  no bloqueante; ARCHITECTURE.md §4).
- Herida abierta a 04-10: la app ArgoCD `k8s-infra` está OutOfSync/Degraded porque el store
  SDK roto (wave 0) nunca llega a Healthy y bloquea la wave 1, donde vive la policy que quita
  la regla `onchange-existing`; mientras tanto cada resync de Kyverno regenera UpdateRequests
  (nota-sre-cupo.md §4). El arreglo propuesto es de devops/tech-lead, no de este runbook.

## Qué NO hacer

- **Rotar credenciales en el día.** La rotación espera la sesión semanal (SC-1790).
- **Reiniciar ESO o hacer `force-sync` masivo sin medir.** Con los ES ya en Connect es gratis;
  con cualquier ES que aún conserve forma SDK, cada relectura va al proveedor y gasta cupo —
  una lectura completa ≈ el día entero (`connect.yaml`).
- **Devolver `mutateExistingOnPolicyUpdate: true` a una policy que toque ES**, o resucitar la
  regla `onchange-existing`: fue la causa de la tormenta del 03-10 (275–535 UpdateRequests por
  resync, nota-sre-cupo.md §2).
- **Poner `op-credentials` o `onepassword-connect-token` en git o en un ExternalSecret**:
  circularidad; el arranque de Connect no puede depender de lo que Connect sirve.
- **Escalar Connect o añadirle un PVC** sin decisión de arquitectura (réplica única = SPOF
  aceptado, nota-architect-plan.md P1).
