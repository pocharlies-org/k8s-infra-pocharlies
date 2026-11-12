# Base comun node (INFRA-536 P2 / INFRA-1297).
# Pila node 22: 3 consumidoras propias en docs/images/inventario.json (correo-app,
# dgx-dashboard-ui, dgx-infra/chat). Bookworm-slim (glibc): encaja con las tres
# (node:22-alpine, node:22-bookworm y node:22.23.3-alpine).
# Multi-arch linux/amd64 + linux/arm64: buildx dual-builder sobre los buildkitd
# remotos del namespace buildkit (buildkitd-amd64 en atlantic, buildkitd-arm64 en
# dgx3), sin QEMU. Digest y consumidores fijados en docs/images/bases.md.
FROM node:22-bookworm-slim@sha256:5ec23b7c622b00547753bc6ffd78085dd868a68aeb41c8e0a1418f033e13d96d
