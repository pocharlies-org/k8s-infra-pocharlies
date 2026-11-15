# Evidencia INFRA-1365 (H2) — migración de pins a keep-<digest12>

Rama `INFRA-1365-migrar-pins` · trunk verificado `main` (la Application `k8s-infra` de
ArgoCD lee `main`; no existe `deploy/prod` — la spec lo citaba desactualizado).

Comandos ejecutados contra Harbor real (`harbor.lan.e-dani.com`), credenciales leídas del
clúster (`harbor-push` ns `buildkit`, robot pull), nunca commiteadas.

## C1 — test que debe fallar primero (correo-app, ci-* más reciente)

Medición inicial (antes de fijar ningún keep- sobre ese manifest):

```
$ # digest del INDEX del ci-* mas reciente de correo-app (commit main 0872a409...)
$ D=sha256:95d4074725c661395a44b7f0d86acb192484948c3b49fcc264a46e5a90d38b01
$ curl -sk -u "$CREDS_PUSH" ".../correo-app/artifacts/${D/:/%3A}/tags" | jq -r '.[].name'
ci-0872a409519296c3944ba016ccda570633027b4d
$ ... | grep -cx "keep-95d4074725c6"
0
exit=1
```

El keep- no existía → 0. (Al re-ejecutar hoy el mismo comando da **1**: el CI de P1 ya
fijó `keep-95d4074725c6` sobre el mismo manifest. No lo fijó este trabajo — aquí solo se
hizo dry-run y un POST a otro digest — es el mecanismo de publicación funcionando.)

### Fail-first reproducible hoy (repo cubierto aún sin migrar)

```
$ # pin paseo-atlantic (k8s-paseo-pocharlies), digest del INDEX
$ D=sha256:6e94762849d4c95b1cb85677c32ab7367022d2cd4f4208a994125b8a0a1d34a1
$ curl -sk -u "$CREDS_PUSH" ".../paseo-atlantic/artifacts/${D/:/%3A}/tags" | jq -r '.[].name'
ci-7b0ed3b421d4c2665d20612a0461770f0240a3f8
$ ... | grep -cx "keep-6e94762849d4"
0
exit=1
```

## C2-prep — credenciales (exigida)

```
LECTURA   GET  .../correo-app/artifacts/<digest>/tags  (robot push)      -> HTTP 200
ESCRITURA POST .../correo-app/artifacts/<digest>/tags {"name":"keep-..."} -> HTTP 409
```

- 200 lectura: el endpoint de tags anidados responde a cuenta robot (el listado de
  artefactos responde 403 a robots — hallazgo 4 del architect — por eso se comprueba por
  digest conocido, nunca listando).
- 409 escritura: la credencial de push (`harbor-push`, `robot$x86-buildkit-push`) alcanza
  el POST de CreateTag; 409 = ya existe y resuelve al mismo digest = éxito verificado.
  (Con pull solo daría 401, INFRA-1273.)

## Enumeración del módulo (dry-run, sin escribir)

`migrar.py` sobre `k8s-synapse-pocharlies/k8s` (DRY_RUN=1, credencial de push):

```
PROTEGIDO homelab/synapse@sha256:0736081f75a6...
RETAGUEARIA homelab/synapse@sha256:09a0b42150db... -> keep-09a0b42150db
... (15 RETAGUEARIA, 4 PROTEGIDO)
retagueados: 15, pendientes: 0, inexistentes: 0
```

Barrido de los 118 pins `@sha256:` de los clones GitOps (clasificación del módulo):

```
PROTEGIDOS (llevan keep-*):  26
DESPROTEGIDOS (a migrar):    36
INEXISTENTES (digest borrado por la retención): 56   -> DESPROTEGIDO (inexistente), no retagueables
```

Los 56 inexistentes son el caso "la bomba ya cayó": no se retaguean, se listan para
re-pinear. Ejemplos: `homelab/skirmbooks-backend@sha256:04f57710...`,
`homelab/skirmshopshopifyapp@sha256:0571218c...`.

## Tests

```
$ python3 -m pytest tests/test_guarda_pins_contract.py -q
13 passed
```

Cubren: extracción de refs completas (values/deployments), ignorar Docker Hub y digest
corto, host sin `.lan`, igualdad de la ruta PyYAML y la de texto crudo (imagen mínima del
Job), recorrido de directorios, `keep_tag` (12 hex), codificación de la URL (proyecto /
repo con `/` / digest), y clasificación PROTEGIDO/DESPROTEGIDO/INEXISTENTE + CreateTag/verify.

## Kustomize

```
$ kustomize build .            # exit 0 (ConfigMap guarda-pins generado desde scripts/guarda-pins/)
$ kustomize build platform/guarda-pins   # Namespace + ExternalSecret + SA + Job
```

## Criterios cubiertos por ESTA PR

- C2-prep (credenciales): demostrado arriba (200 lectura / 409 escritura).
- Tests unitarios del módulo (PyYAML): 13 passed.
- Docs: `ARCHITECTURE.md` §4 añade `platform/guarda-pins/` + `scripts/guarda-pins/`.
- Módulo de enumeración + `migrar.py` + `platform/guarda-pins/migrar-job.yaml` entregados.

## C3-mig (Job ejecutado → 0 pendientes) — NO cubierto por esta PR

Es un paso de producción tras el merge (ArgoCD sync del Job). Esta PR entrega el Job y
demuestra el mecanismo (dry-run + credenciales); la ejecución real y `grep -c DESPROTEGIDO`
sobre el reporte del pod se verifica tras fusionar, no se anticipa aquí.
