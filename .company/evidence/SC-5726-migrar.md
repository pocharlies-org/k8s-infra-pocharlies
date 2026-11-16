# Evidencia SC-5726 — Job `guarda-pins-migrar` fallido por DeadlineExceeded

Rama `SC-5726-migrar-deadline` · tronco verificado `main` (Application `k8s-infra`,
`targetRevision: main`, sync `automated` con `selfHeal`). Comandos contra el clúster real
(`KUBECONFIG=~/.kube/config`) y Harbor real; credenciales nunca leídas ni commiteadas (la
comprobación C4 corre dentro de un pod transitorio con `envFrom` del Secret
`guarda-pins-creds`, que solo imprime nombres de tag).

## Causa medida (no la hipótesis de la spec)

El `DeadlineExceeded` no fue volumen de pins ni Harbor lento: el init container se quedó
en `ImagePullBackOff` los 900 s porque la imagen fijada no existe
(`docker.io/library/alpine/git:2.45.2` → el repo es `docker.io/alpine/git`).

```
$ kubectl get events -n guarda-pins --sort-by=.lastTimestamp
...  Warning  Failed  pod/guarda-pins-migrar-ww4b2  Failed to pull image
       "docker.io/library/alpine/git:2.45.2@sha256:22ab341e...": pull access denied,
       repository does not exist or may require authorization
...  Warning  DeadlineExceeded  job/guarda-pins-migrar  Job was active longer than specified deadline
```

La imagen ya está corregida en el tronco por `a7e7a160b` (OWU-137, PR #547). Con esa
imagen, el Job recreado por ArgoCD completó en **39 s** (35 pins únicos, no ~184: 9
PROTEGIDO + 25 retagueados + 1 inexistente). Por eso el arreglo de esta historia es solo
de capacidad del deadline (cota de un run colgado), sin tocar `pins.py`: no hubo ninguna
petición colgada que justifique un presupuesto por petición.

## C1 — el Job termina con éxito

Antes (debe fallar — medido 2026-11-16, Job de las 03:53 y el recreado de las 05:34):

```
$ kubectl get job guarda-pins-migrar -n guarda-pins -o jsonpath='{.status.succeeded}'
(vacío)
$ kubectl get job guarda-pins-migrar -n guarda-pins \
    -o jsonpath='{.status.conditions[?(@.type=="Failed")].reason}'
DeadlineExceeded
```

Tras la corrección de la imagen y la re-ejecución de ArgoCD (06:00:50Z → 06:01:29Z):

```
$ kubectl get job guarda-pins-migrar -n guarda-pins \
    -o jsonpath='succeeded={.status.succeeded} failed_cond={.status.conditions[?(@.type=="Failed")].reason}'
succeeded=1 failed_cond=
```

PASS. (Queda pendiente la misma comprobación sobre el Job recreado con
`activeDeadlineSeconds: 1800`, tras el merge — se registra en el ticket.)

## C2 — informe del Job sin pendientes

```
$ kubectl logs job/guarda-pins-migrar -n guarda-pins --tail=1
retagueados: 25, pendientes: 0, inexistentes: 1
```

PASS. El único `inexistente` es `homelab/skirmshop-labels-synapse-janitor@sha256:7b14735b…`
(digest ya borrado por la retención: es re-pinear, no retaguear — no es fallo).

## C3 — el arreglo está en GitOps

`platform/guarda-pins/migrar-job.yaml`: `activeDeadlineSeconds: 900 → 1800`, con la causa
real documentada en el comentario de cabecera. Sin `kubectl apply`.

```
$ kubectl get application -n argocd k8s-infra -o jsonpath='{.status.sync.status}'
Synced
```

El objeto vivo con el valor nuevo se comprueba tras el merge (borrar el Job y dejar que
ArgoCD lo re-cree); registrado en el ticket.

## C4 — comprobación en Harbor (punta de lanza)

El digest que INFRA-1365 dejó como fail-first reproducible (`paseo-atlantic`,
`sha256:6e94762849d4…`) lleva su `keep-`:

```
$ # pod transitorio, mismo ConfigMap `guarda-pins` y envFrom `guarda-pins-creds`
$ python3 -c "... pins.harbor_tag_names(base,'homelab/paseo-atlantic',D,user,pw)"
TAGS ['ci-7b0ed3b421d4c2665d20612a0461770f0240a3f8', 'keep-6e94762849d4']
KEEP_OK True
```

PASS. Coincide con la línea `RETAGUEADO homelab/paseo-atlantic@sha256:6e94762849d4…` del
stdout del Job.

## C5 — documentación

El cabecero de `migrar-job.yaml` documenta ahora el valor 1800 y la causa real del
fallo (ImagePullBackOff, #547), además del patrón de un solo uso. Este fichero es la
evidencia de la re-ejecución con el stdout del Job que pasó.
