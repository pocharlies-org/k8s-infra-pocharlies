Rol: developer · Fecha: 2026-11-11 · Sesión: 4af16e30-aa62-4c4e-9026-4d232e3643e4 · Estado: LISTO

# 50-entrega — INFRA-1296 (P1 de INFRA-536): inventario y grafo regenerables (C1 + C2)

## Qué se hizo

- `scripts/image-inventory.py`: inventario regenerable desde las refs reales del clúster
  (`kubectl get deploy,sts,ds,cronjob -A -o json`). Normaliza los dos hosts de Harbor al mismo
  repo lógico (con `harbor.e-dani.com` preferido y reintento), resuelve índices OCI a la
  plataforma del nodo (descartando la atestiguación `architecture: unknown` que adjunta buildx,
  medida en vivo), y fija el contrato JSON de C1: las 7 claves de toda propia siempre presentes y
  no nulas; el no-dato como marcador `sin_dato` dentro del propio campo. Espejos (`redis`,
  `onepassword-connect`, `vllm-*`, `searxng`, `clamav`, `agentgateway`, `minio`, y `ghcr.io/*` sin
  repo GitHub homónimo) salen con `"clase":"espejo"` y sin los 7 campos. Ficheros generados sin
  marcas de tiempo de ejecución; sin credenciales.
- `scripts/image-graph.py`: grafo determinista (`grafo.md` + `grafo.dot`) consumiendo
  `inventario.json`; bases como raíces, imágenes propias intermedias, despliegues como hojas;
  cada imagen del inventario es nodo. Dos pasadas → bytes idénticos.
- `docs/images/`: `inventario.json`, `inventario.md`, `sizes-baseline.json`, `grafo.md`,
  `grafo.dot` generados contra el clúster real (evidencia abajo).
- Tests de contrato con fixture fija commiteada (`tests/test_image_inventory_contract.py`,
  `tests/test_image_graph_contract.py`), patrón `tests/test_*_contract.py`.
- Fila de `docs/images/inventario.json` + `sizes-baseline.json` en `ARCHITECTURE.md` §4.

## Correcciones clave respecto al intento anterior (por qué la evidencia anterior no valía)

La fixture del intento anterior codificaba una interfaz `gh` que no existe:
`gh search code --org ...` (la CLI real, gh 2.103, usa `--owner`; no existe `--org`) y el campo
`full_name` (la salida real trae `nameWithOwner`). Los tests pasaban contra la fixture pero el
comando real fallaba — exactamente "un 200 no basta". Corregido contra la CLI real medida en vivo:

- **Resolución del Dockerfile por escaneo de la org, no por búsqueda.** Medido en el clúster real
  (11-11, primera pasada en vivo): la búsqueda por imagen con `gh search code` (motor legacy) no es
  fiable — devuelve `[]` para `homelab/blog` y un hit con **path vacío** para
  `homelab/dgx-dashboard-backend`, cuyo workflow sí existe y declara `IMAGE:`. El script recorre
  ahora una sola vez el `.github/workflows` de los 241 repos de `pocharlies-org` (`gh api`, límite
  core) y mapea la línea `IMAGE:` de cada workflow → Dockerfile declarado. Misma fuente de verdad
  que fija el spec (envs `IMAGE:`/`DOCKERFILE:`); solo cambia la recuperación, que pasa de
  135 búsquedas limitadas a ~30/min a un escaneo paralelo determinista.
- Refs con tag **y** digest a la vez (`name:tag@sha256:…`, medido en el clúster): el tag se quita
  también del repo lógico.
- Hijos de atestiguación (`platform.architecture: "unknown"`) descartados al elegir plataforma
  (medido: los índices de Harbor los llevan).
- Espejo multi-palabra (`onepassword-connect`): el patrón casa con el nombre entero, no solo por
  segmentos.
- Pozo de 8 para las llamadas por repo; `crane export` acotado (≤100 MB comprimidos y
  `timeout 300 s`): throughput medido ~6 MB/s — las imágenes grandes quedan con marcador
  `sin_dato` dentro del campo, como prescribe el plan de la épica (el guard C4 solo necesita el
  comprimido).

## PR

<PR_URL> (rama `INFRA-536-inventario-grafo`, contra `main`).

## Cómo verificar

```sh
cd <clone> && git fetch origin && git checkout INFRA-536-inventario-grafo
python3 -m unittest discover -s tests -p 'test_*.py'          # 22 casos nuevos, sin red ni clúster
export KUBECONFIG=~/.kube/config
python3 scripts/image-inventory.py && jq 'length' docs/images/inventario.json \
  && jq '[.[]|select(.clase=="propia")|select(.dockerfile==null or .base_digest==null or .comprimido==null or .descomprimido==null or .capas_top==null or .build_fecha==null or (.deployments|length)==0)]|length' docs/images/inventario.json
python3 scripts/image-graph.py && python3 scripts/image-graph.py && git diff --exit-code -- docs/images/grafo.md docs/images/grafo.dot
```

## Checklist del 00-spec.md

- [x] `scripts/image-inventory.py` → `inventario.json`, `inventario.md`, `sizes-baseline.json`
- [x] Punto de partida: refs reales del clúster; nunca se asume `latest` (medido: `blog:latest` y
      `cv-dani:latest` dan 404; el inventario usa los tags/digests que cita el clúster)
- [x] Alcance `harbor.e-dani.com/homelab/*`, `harbor.lan.e-dani.com/homelab/*` (mismo repo lógico,
      host preferido con reintento) y `ghcr.io/pocharlies-org/*`
- [x] Contrato JSON de C1 (7 claves no nulas; `sin_dato` dentro del campo) — verificado en vivo
- [x] Resolución `dockerfile`: ghcr → repo homónimo vía `gh api` (fallback búsqueda); Harbor →
      workflow que declara `IMAGE: homelab/<n>` (verificado por contenido); sin resolución → marcador
- [x] Propia/espejo por la misma regla (upstreams → `"clase":"espejo"`)
- [x] Tamaños: comprimido = suma `layers[].size` del manifiesto resuelto a plataforma (índices
      siempre resueltos, incluso de una sola plataforma); descomprimido vía `crane export` con
      reintentos y umbral; `capas_top`; `build_fecha` = `crane config | jq -r .created`;
      `deployments` = consumidores
- [x] Ficheros generados sin marcas de tiempo de ejecución
- [x] `sizes-baseline.json` con formato estable documentado en el propio fichero
- [x] Sin credenciales en ficheros ni código
- [x] `scripts/image-graph.py` determinista (`git diff --exit-code` limpio)
- [x] Fixture fija: índice multi-arch, índice de una sola plataforma + atestiguación, imagen
      simple, espejo, espejo multi-palabra, imagen sin `latest` (todos los tags son reales del
      clúster; ningún `latest`), los dos hosts de Harbor al mismo repo lógico, propia con marcador
      `sin_dato`, y el test del jq EXACTO de C1 dando 0
- [x] Fila en `ARCHITECTURE.md` §4
- [x] Python 3.12 + PyYAML sin dependencias nuevas (solo stdlib)
- [x] Rama + PR contra `main`; nada tocado de Dockerfiles ajenos ni buildkit

## Reutilizado

- `ARCHITECTURE.md` §3 (stack: Python + stdlib, sin dependencias nuevas), §4 (donde registrar),
  §6 (`python3 -m unittest discover -s tests -p 'test_*.py'`) y el patrón de los 33
  `tests/test_*_contract.py` existentes (p. ej. `tests/test_velero_operability_contract.py`:
  subproceso + assert sobre salida).
- Método verificado por el PM: `crane manifest`/`crane config | jq -r .created`/`crane digest`,
  `kubectl get deploy,sts,ds,cronjob -A -o json`, envs `IMAGE:`/`DOCKERFILE:` de los workflows de
  build (formato confirmado en `dgx-infra/.github/workflows/build-dashboard-backend.yml:33,37`).
- `requirements.txt`: PyYAML ya estaba; no se añadió nada (los scripts usan solo stdlib).
- Nuevo: la resolución de índices con descarte de atestiguación y el limitador de búsquedas —
  nada en el repo los cubría (buscado con `rg -n "crane|inventario|image-graph" scripts/ tests/`:
  cero resultados previos).

## Evidencia

Salida real del 11-11 contra el clúster en vivo (KUBECONFIG=~/.kube/config). Completa en
`.company/evidence/INFRA-536-inventario-grafo.md` y en la descripción de la PR.

- **C1** — «`python3 scripts/image-inventory.py && jq 'length' … && jq '[.[]|select(.clase=="propia")|select(…)]|length'` → exit 0 y segundo número `0`; espejos con `"clase":"espejo"`»:
  ```
  $ python3 scripts/image-inventory.py
  125 imagenes (117 propias, 8 espejos) en docs/images
  $ jq 'length' docs/images/inventario.json
  125
  $ jq '[.[]|select(.clase=="propia")|select(.dockerfile==null or .base_digest==null or .comprimido==null or .descomprimido==null or .capas_top==null or .build_fecha==null or (.deployments|length)==0)]|length' docs/images/inventario.json
  0   # exit 0
  ```
  117 propias, 8 espejos. Marcadores `sin_dato` dentro de campo: descomprimido 57 (56 por >100 MB
  comprimidos — export rinde ~6 MB/s medido —, 1 por fallo), dockerfile 93 (sin workflow que declare
  la imagen: construyen vía workflows reutilizables sin envs `IMAGE:`/`DOCKERFILE:` — caso (c) del
  spec), base_digest 107 (derivado del dockerfile). `comprimido`/`build_fecha`/`capas_top`: 0.
- **C2** — «`python3 scripts/image-graph.py && python3 scripts/image-graph.py && git diff --exit-code -- docs/images/grafo.md docs/images/grafo.dot` → exit 0»:
  ```
  447 nodos, 329 aristas en docs/images   (primera pasada)
  447 nodos, 329 aristas en docs/images   (segunda pasada)
  git diff --exit-code: exit 0 (bytes idénticos)
  ```
