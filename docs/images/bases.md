# Bases comunes fijadas por digest (INFRA-536 P2 · INFRA-1297)

Bases compartidas por las imágenes propias de `harbor.e-dani.com/homelab/*`. Las
pilas elegidas son las dos con 3+ consumidoras propias en
`docs/images/inventario.json` (las demás no llegan a 3: verificado el 11-11 sobre
los 24 Dockerfiles resolubles del inventario). Las imágenes hijas (INFRA-537..541)
consumen estas bases **por digest**, nunca por tag.

Construcción: buildx dual-builder sobre los buildkitd remotos del namespace
`buildkit` (`buildkitd-amd64` en atlantic, `buildkitd-arm64` en dgx3), sin QEMU;
patrón canónico `dgx-infra/.github/workflows/build-bge-embedding.yml`. Cada índice
OCI lleva manifiestos `linux/amd64` y `linux/arm64` nativos más las attestations
de buildx. Medido el 2026-11-11 con dgx3 en modo `llm` (`phase: ready`, ventana
creative cerrada) y el builder de atlantic libre.

## base-python-slim-uv
- tag: 3.12
- digest: sha256:e2b290bdd0bdf118dd3daa355aa6019faa1d2c8301b818ef46dc653bd9fd9e20
- dockerfile: bases/python-slim-uv/Dockerfile
- arquitecturas: linux/amd64, linux/arm64
- consumidoras:
  - harbor.e-dani.com/homelab/correo-core
  - harbor.e-dani.com/homelab/correo-telegram
  - harbor.e-dani.com/homelab/dgx-dashboard-backend
  - harbor.e-dani.com/homelab/dgx-messages
  - harbor.e-dani.com/homelab/offers-mcp

Pila python: las cinco consumidoras construyen hoy `FROM python:3.12-slim` (tres
de ellas ya fijadas por digest en su Dockerfile). La base añade `uv==0.13.7`
(instalado por PyPI, versión fijada).

## base-node
- tag: 22
- digest: sha256:61b7a3ce3746d5f790a3a061eee28d932d778879dee3b367f2519292174f4049
- dockerfile: bases/node/Dockerfile
- arquitecturas: linux/amd64, linux/arm64
- consumidoras:
  - harbor.e-dani.com/homelab/correo-app
  - harbor.e-dani.com/homelab/dgx-dashboard-ui
  - harbor.e-dani.com/homelab/dgx-infra/chat

Pila node 22: las tres consumidoras construyen hoy `FROM node:22-*` (alpine y
bookworm); la base fija `node:22-bookworm-slim` (glibc), que sirve a las tres.

## Verificación (criterio C3)

```sh
crane digest harbor.e-dani.com/homelab/base-python-slim-uv:3.12   # == el digest de arriba
crane digest harbor.e-dani.com/homelab/base-node:22               # == el digest de arriba
crane manifest harbor.e-dani.com/homelab/base-python-slim-uv:3.12 | jq '.manifests | length'  # 4 (>=2)
crane manifest harbor.e-dani.com/homelab/base-node:22 | jq '.manifests | length'               # 4 (>=2)
```

El contrato de este fichero (formato del digest, >=3 consumidoras existentes en
el inventario, Dockerfiles con FROM fijado) lo fija
`tests/test_image_bases_contract.py`.
