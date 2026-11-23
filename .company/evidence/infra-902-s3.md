# INFRA-1412 (INFRA-902 S3) · evidencia — sonda de divergencia e-dani.com

Dónde: worktree de la rama `INFRA-902-s3` (desde origin/main cc45718), sesión ejecutada
dentro del clúster (pod `paseo-0`, ns paseo) con `KUBECONFIG=~/.kube/config`; sonda
ejecutada contra los 10 endpoints reales de `kube-dns` y push real a
`vmsingle-vm-victoria-metrics-k8s-stack.monitoring.svc:8428`. 20-11-2026.
Nada de `kubectl apply`: los manifiestos llegan al clúster por el trunk tras el merge.

## 1. Rojo primero · PASS (FAIL esperado)

Mutación sobre el manifiesto (borrar la línea `adguard-setup.e-dani.com` del `names.txt`
embebido, única copia que lee el job):

`python3 -m unittest tests/test_edani_dns_divergence_watch_contract.py`
```
FAIL: test_names_txt_equals_list_fixed (TestNamesSingleSource)
AssertionError: Items in the second set but not the first:
'adguard-setup.e-dani.com'
Ran 13 tests in 0.050s
FAILED (failures=1)
```
La deriva de la lista embebida respecto a `--list-fixed` se pilla en CI (job
`coredns-edani-guard`, donde queda cableado el test).

## 2. Verde tras el cambio · PASS

```
python3 -m unittest tests/test_edani_dns_divergence_watch_contract.py  -> Ran 13 tests, OK
python3 -m unittest tests/test_coredns_edani_contract.py                -> Ran 9 tests, OK  (sin regresión)
kustomize build .                                                        -> limpio
```

Diff de objetos `kustomize build` main vs rama: 475 -> 481; los 6 nuevos son
`ServiceAccount/Role/RoleBinding/ConfigMap/CronJob/VMRule`, todos
`edani-dns-divergence-watch` (SA y CronJob en `monitoring`; Role/RoleBinding en
`kube-system`; VMRule en `monitoring`).

## 3. Por qué resolver en stdlib y no `dig`

`crane config alpine/k8s:1.32.5` (histórico de capas): `apk add` instala
`curl ca-certificates bash git`, `py3-pip`, `jq yq`, `gettext`; **no hay `bind-tools`
(dig)**. El probe resuelve con un cliente DNS A en stdlib (`socket`+`struct`), que es
además el mismo código que corrió la evidencia de abajo (el entorno de la evidencia
tampoco tiene dig). Parser cubierto por 5 tests (nombre comprimido, multi-A, NXDOMAIN,
id erróneo, respuesta corta).

## 4. Sonda ejecutada contra los endpoints reales de kube-dns

`kubectl -n kube-system get endpoints kube-dns` -> 10 IPs (10.42.0.131 … 10.42.8.31).
La sonda se ejecutó con el `probe.py` embebido en el ConfigMap extraído del manifiesto
(mismo código que correrá el CronJob), `NAMES_FILE` = `--list-fixed` (57 nombres).

### C3b — estado sano: gauge 0, alerta no firing · PASS

```
$ NAMES_FILE=names.txt VM_PUSH_URL=http://vmsingle-...:8428 python3 probe.py
sonda: 57 nombres x 10 endpoints kube-dns
resultado: gauge=0 divergentes=0 sin_respuesta=0 de 570 consultas
metricas empujadas a http://vmsingle-vm-victoria-metrics-k8s-stack.monitoring.svc:8428
```
Consulta `/api/v1/query?query=edani_dns_public_answer` (instantánea tras el flush de
vmsingle, ~10-60 s):
```
[{"metric": {"__name__": "edani_dns_public_answer"}, "value": [1795152437, "0"]}]
```
Con el gauge en 0 la expresión de la VMRule, `edani_dns_public_answer == 1`, no devuelve
serie -> `EdaniDnsPublicAnswer` no puede estar `firing`.

### C3a — divergencia forzada: gauge 1 · PASS

Nombre de prueba pasado como argumento (`EXTRA_TEST_NAME=www.cloudflare.com`, nombre no
fijado que responde pública por diseño), retirado en la pasada siguiente:
```
$ EXTRA_TEST_NAME=www.cloudflare.com python3 probe.py
sonda: 58 nombres x 10 endpoints kube-dns
DIVERGENCIA: www.cloudflare.com @ 10.42.0.131 responde 104.16.123.96,104.16.124.96
... (10 endpoints) ...
resultado: gauge=1 divergentes=10 sin_respuesta=0 de 580 consultas
```
Consulta tras el flush:
```
edani_dns_public_answer -> [{"metric": {...}, "value": [1795152493, "1"]}]
edani_dns_public_answer_offender -> 10 series, ej.:
 {"metric": {"__name__": "..._offender", "answer": "104.16.123.96,104.16.124.96",
             "endpoint": "10.42.0.131", "name": "www.cloudflare.com"}, "value": [..., "1"]}
```
Y la expresión exacta de la VMRule con el gauge en 1:
```
/api/v1/query?query=edani_dns_public_answer == 1
-> [{"metric": {"__name__": "edani_dns_public_answer"}, "value": [1795152519, "1"]}]
```
Retirado el nombre (pasada sana siguiente), el job empuja gauge 0 y la condición deja de
dar serie: la alerta se resuelve.

### Firing completo en VictoriaAlert · delegado a la QA de la épica

La VMRule llega al clúster con el merge (app `k8s-infra`); no se hace `kubectl apply`
manual. Tras el sync, verificar en vmalert que `EdaniDnsPublicAnswer` existe y repetir
C3a/C3b con `kubectl create job -n monitoring --from=cronjob/edani-dns-divergence-watch ...`
(y el env `EXTRA_TEST_NAME` en el job creado, no en el CronJob).

## Criterios

- C3a: divergencia forzada con nombre de prueba -> métrica 1 + offenders con
  `{name,endpoint,answer}` (sección 4, C3a); la condición de la VMRule se cumple con el
  gauge en 1 (misma sección). Firing en vmalert: tras el deploy, QA de la épica.
- C3b: estado sano -> gauge 0 y la expresión de la regla no da serie, no firing
  (sección 4, C3b). Retirado el nombre de prueba el estado vuelve a sano (gauge 0
  empujado de nuevo; producción queda en 0).

## Notas

- La sonda trata `sin_respuesta` (NXDOMAIN/SERVFAIL/timeout) como dato no-alertable
  (3 timeouts transitorios UDP en una pasada de 570 consultas, 0 en las siguientes): el
  gauge afirma respuestas públicas, que es C3.
- Ventana de visibilidad: vmsingle indexa el import con retardo de segundos y la
  consulta instantánea mira ~5 min hacia atrás; con la cadencia de 5 min del CronJob
  siempre hay muestra fresca. Si el job muere, `K8sCronJobFailed` (topic Crons) avisa.
