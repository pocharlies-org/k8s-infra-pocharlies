# Base comun python-slim + uv (INFRA-536 P2 / INFRA-1297).
# Pila python: 5 consumidoras propias en docs/images/inventario.json (correo-core,
# correo-telegram, dgx-dashboard-backend, dgx-messages, offers-mcp).
# Multi-arch linux/amd64 + linux/arm64: buildx dual-builder sobre los buildkitd
# remotos del namespace buildkit (buildkitd-amd64 en atlantic, buildkitd-arm64 en
# dgx3), sin QEMU. Digest y consumidores fijados en docs/images/bases.md.
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

# uv fijado por version (instalandose por PyPI, via oficial soportada).
RUN pip install --no-cache-dir uv==0.13.7

ENV PYTHONUNBUFFERED=1
