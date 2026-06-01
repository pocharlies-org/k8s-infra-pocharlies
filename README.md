# k8s-infra-pocharlies

Infraestructura del cluster k3s: networking (Traefik, MetalLB, cert-manager),
storage (Longhorn, MinIO, NFS), platform (Harbor, Vault, Keycloak, Kyverno,
GPU Operator, Velero), shared PostgreSQL + RabbitMQ + Redis.

## Cluster

- **Actual**: `ubuntu` x86 es control-plane/etcd; `sauvage` es worker/edge; `nvidia-dgx` y `gx10-ec3d` son workers GPU.
- **Objetivo KS-5 HA**: `ks5-cp-1..3` serán los únicos k3s server/etcd; `ubuntu` pasará a worker rápido; `sauvage` seguirá como worker pesado + edge.
- **OS objetivo para KS-5**: Ubuntu Server 24.04 LTS, instalado por API OVH con SSH key y RAID1 software cuando OVH lo permita.

## GitOps

Gestionado por ArgoCD desde [k8s-gitops-pocharlies](https://github.com/pocharlies/k8s-gitops-pocharlies).

## Automatización KS-5

- `terraform/ovh`: discovery/order seguro de OVH/Kimsufi. No compra nada salvo `enable_order=true` y `confirm_ovh_order=order-3-ks5`.
- `scripts/ovh_install.py`: instala Ubuntu Server 24.04 LTS en servidores dedicados ya entregados. Requiere `CONFIRM_OVH_REINSTALL=install-ubuntu-24.04`.
- `ansible/`: hardening, Tailscale, k3s server/agent y labels.
- `kubernetes/`: parches y material de rollout para Traefik HA, external-dns y scheduling.
- `scripts/verify.sh`: validaciones end-to-end antes, durante y después del cambio.

Consulta `docs/runbook.md` antes de ejecutar cualquier fase destructiva.
