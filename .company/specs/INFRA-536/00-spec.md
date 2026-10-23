Rol: pm · Fecha: 2026-10-09 · Sesión: 63e87f75-78b4-4a15-98d0-6d9fea939afb · Estado: LISTO

## Objetivo
Construir en k8s-infra-pocharlies la plataforma de imágenes de INFRA-474: inventario regenerable de las imágenes propias, grafo base→imágenes→Deployments, bases comunes fijadas por digest y un guard reutilizable de CI (hadolint + tamaño). Desbloquea a las hijas de corrección INFRA-537, 538, 539, 540 y 541, que consumen el inventario, las bases y el guard (esta hija produce; ellas adoptan y no duplican).

Repo: k8s-infra-pocharlies (tronco `main`; el workflow reusable del guard va a `k8s-gitops-pocharlies` por convención — un solo fichero, ver Restricciones)

## Criterios de aceptación
Estado de partida re-verificado hoy 09-10 contra `origin/main` (207cedd): NO existe nada de esto en k8s-infra-pocharlies ni en k8s-gitops-pocharlies (`scripts/image-inventory.py`, `scripts/image-graph.py`, `docs/images/`, `bases/`, `sizes-baseline.json`, `reusable-image-guard.yml`), ni imágenes `base-*` en Harbor (`crane digest harbor.e-dani.com/homelab/base-python-slim-uv` y `base-node` → NOT_FOUND). hadolint sigue sin estar instalado en local. Los cuatro criterios siguen íntegros.

- [ ] **C1 Inventario regenerable** de las imágenes propias en uso en el clúster (Harbor `homelab/*` en `harbor.e-dani.com` y `harbor.lan.e-dani.com`, y ghcr `pocharlies-org/*`), con 7 campos: repo y ruta del Dockerfile, base con tag y digest, tamaño comprimido, tamaño descomprimido, capas más grandes, fecha del último build, Deployments que la usan; y clasificación propia / espejo de tercero.
  - Comando: `python3 scripts/image-inventory.py && jq 'length' docs/images/inventario.json && jq '[.[]|select(.clase=="propia")|select(.dockerfile==null or .base_digest==null or .comprimido==null or .descomprimido==null or .capas_top==null or .build_fecha==null or (.deployments|length)==0)]|length' docs/images/inventario.json`
  - Salida esperada: exit 0; el primer número ≈ los repos propios medidos hoy (112 repos propios / 142 refs propias entre 293 imágenes distintas de Deployments/StatefulSets/DaemonSets/CronJobs; tolerancia por drift); el segundo es `0` (toda propia con los 7 campos, o con motivo explícito en un campo `sin_dato`). Los espejos (redis, onepassword-connect, vllm-*, searxng, clamav, agentgateway…) salen con `"clase":"espejo"`.
  - Método verificado hoy: `crane manifest --platform linux/{arch} {img}` (suma de `.layers[].size`; si es índice OCI se resuelve a la plataforma del clúster), `crane config {img} | jq -r .created`, `kubectl get deploy,sts,ds,cronjob -A -o json` (consumidores). Descomprimido: `crane export`/`docker image inspect` por plataforma. Ojo: muchos repos no tienen tag `latest` (404 en `brain-mcp:latest` hoy) — el script parte de las refs reales del clúster, nunca de `latest`.

- [ ] **C2 Grafo regenerable y determinista** base → bases propias intermedias → imágenes propias → Deployments, en el repo.
  - Comando: `python3 scripts/image-graph.py && python3 scripts/image-graph.py && git diff --exit-code -- docs/images/grafo.md docs/images/grafo.dot`
  - Salida esperada: exit 0 (dos ejecuciones seguidas dan ficheros idénticos). Nodos raíz = imágenes base (propias y de terceros); hojas = Deployments; cada imagen del inventario aparece como nodo.

- [ ] **C3 Bases comunes** para las pilas con 3 o más consumidores propios (mínimo `python-slim+uv` y `node`), construidas, subidas a Harbor y fijadas por digest.
  - Comando: `for p in python-slim-uv node; do crane digest harbor.e-dani.com/homelab/base-$p:{tag}; done` y `grep -c 'sha256:' docs/images/bases.md`
  - Salida esperada: un `sha256:` por base, idéntico al fijado en `docs/images/bases.md`; `bases.md` lista cada base con tag, digest, `bases/{pila}/Dockerfile` y sus consumidores (3 o más por pila, salidos del inventario). Cada base es índice multi-arch (`crane manifest ... | jq '.manifests|length'` ≥ 2: arm64 + amd64) o declara por escrito la arquitectura única y por qué.

- [ ] **C4 Guard reutilizable de CI**: lint del Dockerfile con hadolint + tope/aviso de crecimiento de tamaño contra `sizes-baseline.json`, invocable por `workflow_call`.
  - Comando: `grep -n 'workflow_call' .github/workflows/reusable-image-guard.yml` (en `k8s-gitops-pocharlies`, junto a `reusable-ci.yml`) y una PR de prueba en un repo de imagen que lo llame con `uses: pocharlies-org/k8s-gitops-pocharlies/.github/workflows/reusable-image-guard.yml@{sha}`.
  - Salida esperada: el workflow existe y corre en `arc-k8s`; la PR de prueba con un error hadolint (p. ej. `FROM x:latest`) falla el check y la que engorda la imagen por encima del umbral falla o avisa según el input `modo`; una PR limpia pasa. `docs/images/sizes-baseline.json` (generado por el inventario) es la línea base. Se enlazan las ejecuciones de las tres PR de prueba como evidencia.

## Restricciones
- GitOps: PR contra `main` de cada repo; nunca merge ni push directo al tronco.
- **Dónde viven los reusables (verificado 04-10, vigente hoy):** todos los workflows reusables de la compañía están en `k8s-gitops-pocharlies` (`reusable-ci.yml`, `reusable-pr-review.yml`, `reusable-release.yml`…; ramas `main` y `deploy/prod`) y los repos los consumen fijados por SHA. k8s-infra-pocharlies no tiene ningún reusable. Decisión: `reusable-image-guard.yml` va en `k8s-gitops-pocharlies` (convención); scripts, `docs/images/` y `bases/` en este repo. La historia del guard abre una segunda PR de un solo fichero en gitops — es la única incursión fuera del repo de la épica, no un alcance multi-repo.
- hadolint no está instalado en local (recomprobado hoy: `command not found`): el guard lo corre vía imagen/binario fijado en CI (`arc-k8s`, skill `ci-runners-arc`), no con una instalación local.
- Multi-arch: hay índices OCI. Nodos hoy (09-10): arm64 = `gx10-ec3d`, `nvidia-dgx`, `dgx3` (Spark, se unió el 08-10); amd64 = `ubuntu`, `sauvage`, `ks5-cp-1/2/3`. Inventario y guard resuelven el índice a la plataforma del nodo donde corre el Deployment.
- Dos hosts de Harbor en uso (`harbor.e-dani.com` y `harbor.lan.e-dani.com`): el inventario los normaliza al mismo repo. Hoy ambos responden (el EOF del 04-10 fue transitorio); el script reintenta y prefiere `harbor.e-dani.com`.
- No corregir Dockerfiles de imágenes concretas: es de INFRA-537 a 541. Esta hija solo produce inventario, grafo, bases y guard.
- No tocar el buildkit degradado (INFRA-475, fuera de alcance). Construir las bases puede ir lento por él: documentarlo, no arreglarlo.
- Adoptar las bases en cada Dockerfile es de las hijas de dominio.
- Los scripts son Python 3.12 + PyYAML (stack de `ARCHITECTURE.md`); llevan su test en `tests/` (`python3 -m unittest discover -s tests -p 'test_*.py'`). Sin credenciales en los ficheros generados: crane/skopeo/kubectl usan las de `~/.docker/config.json` y el kubeconfig sin imprimirlas.
- Solapes: ninguna otra épica abierta cubre inventario, grafo, bases ni guard (repasada la lista de épicas abiertas del 09-10). INFRA-537 y 538 en To Do y 539-541 en Backlog citan a 536 como bloqueo y solo adoptan; INFRA-475 (buildkit) es infraestructura de build.

## Trabajo reciente (24 h)
Nada en 24 h que afecte a este plan. (Comprobado: transcripts de 24 h sin menciones a INFRA-474/536-541, sesiones vivas —solo esta pm, ninguna otra sobre estas claves—; el MCP del brain dio timeout y no pudo consultarse. `origin/main` de k8s-infra avanzó a 207cedd sin commits de imágenes.)

## Diseño
Diseñador: no — scripts, docs y un workflow, sin superficie visual

## Historias previstas
- Story — Inventario y grafo regenerables (developer): `scripts/image-inventory.py` + `scripts/image-graph.py` → `docs/images/inventario.md/.json`, `sizes-baseline.json`, `grafo.md/.dot` determinista, con tests. Cubre C1 y C2 (un solo pipeline de datos: el grafo consume el inventario).
- Story — Bases comunes (devops): `bases/python-slim-uv` y `bases/node`, build multi-arch, push a Harbor, digest en `bases.md` con consumidores. Cubre C3; depende de la historia 1.
- Story — Guard CI reusable (devops): `reusable-image-guard.yml` en `k8s-gitops-pocharlies` (hadolint + tamaño contra baseline) y 3 PR de prueba en repos de imagen. Cubre C4; depende de `sizes-baseline.json` de la historia 1.
- (La verificación — regeneración idéntica, digests en Harbor, guard detectando error hadolint y crecimiento — la hace qa en el flujo de la épica, no es historia.)

## Tamaño
M — un repo principal más un fichero en gitops; dos scripts nuevos contra crane/kubectl/Harbor, dos bases multi-arch y un workflow reusable; sin despliegues de negocio. Revertible: todo es aditivo.

## Dificultad
Dificultad: media — trabaja sobre lo que ya existe (crane/kubectl/Harbor, la convención de reusables de gitops, los Dockerfiles de las pilas), sin producto ni arquitectura nuevos; pero define el método y las bases de las otras cinco hijas, y el inventario debe resolver bien multi-arch (3 Sparks arm64 + amd64), dos hosts de Harbor y la clasificación propia/espejo. Reversible.
