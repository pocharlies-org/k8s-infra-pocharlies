# Fixture negativa del contrato de bases (INFRA-1297).

## base-mala
- tag: 1.0
- digest: sha256:no-es-un-digest-valido
- dockerfile: bases/node/Dockerfile
- arquitecturas: linux/amd64
- consumidoras:
  - harbor.e-dani.com/homelab/no-existe-en-el-inventario
