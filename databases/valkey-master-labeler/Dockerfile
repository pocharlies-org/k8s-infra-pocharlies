# Imagen del etiquetador de master valkey (SC-5880), consumida por los
# deployments shared-valkey-master-labeler (databases) y
# labels-valkey-master-labeler (skirmshop, repo k8s-shopify-label-pocharlies).
#
# Base propia del repo fijada por digest (INFRA-1301/1302; la base y su
# digest viven en bases/python-slim-uv/Dockerfile y docs/images/bases.md).
# Hostname LAN: quien resuelve el FROM es el buildkitd del namespace
# buildkit, dentro del clúster (precedente en dgx-infra:
# build-dashboard-backend.yml — harbor.lan es el mismo Harbor que
# harbor.e-dani.com; los manifiestos de despliegue siguen usando
# harbor.e-dani.com).
FROM harbor.lan.e-dani.com/homelab/base-python-slim-uv:3.12@sha256:e2b290bdd0bdf118dd3daa355aa6019faa1d2c8301b818ef46dc653bd9fd9e20

# Versiones fijadas (imagen reproducible, INFRA-1300).
RUN pip install --no-cache-dir redis==5.2.1 kubernetes==32.0.1

WORKDIR /app
COPY src/ /app/

# Sin secretos en la imagen: la contraseña de Sentinel entra por env
# (secretKeyRef en el Deployment).
USER 65534:65534

ENTRYPOINT ["python", "-m", "valkey_master_labeler.main"]
