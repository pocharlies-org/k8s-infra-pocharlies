Rol: developer · Fecha: 2026-11-11 · Sesión: 4af16e30-aa62-4c4e-9026-4d232e3643e4 · Estado: LISTO

# Evidencia en vivo C1 y C2 — INFRA-1296 (11-11)

Entorno destino: clúster k3s real (KUBECONFIG=~/.kube/config), Harbor harbor.e-dani.com y
harbor.lan.e-dani.com, ghcr.io/pocharlies-org, gh autenticado (pocharlies), crane con
~/.docker/config.json. Nada de esto es un 200: son las salidas reales de los comandos del spec.

## C1

```
$ python3 scripts/image-inventory.py
125 imagenes (117 propias, 8 espejos) en docs/images

$ jq 'length' docs/images/inventario.json
125

$ jq '[.[]|select(.clase=="propia")|select(.dockerfile==null or .base_digest==null or .comprimido==null or .descomprimido==null or .capas_top==null or .build_fecha==null or (.deployments|length)==0)]|length' docs/images/inventario.json
0
# exit 0
```

Recuento del día: 125 imágenes lógicas = 117 propias + 8 espejos (el recuento no es criterio; el criterio es el 0 de arriba).

Espejos: aurora-frontend, aurora-server, minio, sugiere, minio, onepassword-connect-api, onepassword-connect-sync, redis

Marcadores sin_dato dentro de campo (propias):
```
{
  "propias": 117,
  "dockerfile_sin_dato": 93,
  "base_digest_sin_dato": 107,
  "comprimido_sin_dato": 0,
  "descomprimido_sin_dato": 57,
  "build_fecha_sin_dato": 0,
  "capas_top_vacias": 0
}
```

Motivos:
- descomprimido: 56 × «omitido por tamaño» (>100 MB comprimidos; crane export rinde ~6 MB/s medido en vivo; el guard C4 solo necesita el comprimido) y 1 × «crane export fallo tras 2 intentos».
- dockerfile: 93 × sin workflow que declare la imagen. Medido: estos repos (p. ej. skirmshop-picker) construyen vía workflows reutilizables de k8s-gitops sin env IMAGE:/DOCKERFILE: — el caso (c) del spec: marcador con motivo. Ampliar la resolución al mapeo images: de kustomize sería una fuente nueva (fuera del método fijado): anotado para el tech-lead.
- base_digest: derivado del Dockerfile; sin Dockerfile no hay FROM que resolver (107 = 93 sin dockerfile + 14 con Dockerfile sin FROM resoluble).

## C2

```
$ python3 scripts/image-graph.py
447 nodos, 329 aristas en docs/images
$ python3 scripts/image-graph.py
447 nodos, 329 aristas en docs/images
$ git diff --exit-code -- docs/images/grafo.md docs/images/grafo.dot
# exit 0 (dos pasadas, bytes idénticos)
```
