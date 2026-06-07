# KS-5 HA Architecture

## Current State

- k3s `v1.32.5+k3s1`.
- `ubuntu` x86 is the only control-plane/etcd node.
- `sauvage` is the public edge worker with Traefik Edge running as a
  hostNetwork DaemonSet.
- Private node connectivity uses Tailscale; current Kubernetes node InternalIPs
  are Tailscale `100.x` addresses.

## Target State

- `ks5-cp-1`, `ks5-cp-2`, `ks5-cp-3`: KS-5-A dedicated servers in OVH
  Roubaix (`rbx8` from delivered services).
- Each KS-5-A must match:
  - CPU: Intel Xeon E-2274G.
  - RAM: 32GB DDR4 ECC included.
  - Storage: 2x SSD NVMe 960GB Enterprise Class Soft RAID included.
  - OS: Ubuntu Server 24.04 LTS.
- The three KS-5-A nodes become the only k3s server/etcd members.
- `ubuntu` becomes a tainted worker for development, dashboards, experiments and
  LLM/dev services only.
- `sauvage` remains heavy worker plus public edge for bulk/heavy production
  services that do not require NVMe.
- Fast stateful production workloads use the KS-5 NVMe pool.
- Traefik Edge runs on all nodes with `ingress=true`: three KS-5-A nodes plus
  Sauvage.
- Cloudflare publishes multiple A records to the four public edge IPs.

## Traffic Flow

```mermaid
flowchart LR
  CF["Cloudflare proxied DNS"] --> IP1["KS-5-A #1 public IP"]
  CF --> IP2["KS-5-A #2 public IP"]
  CF --> IP3["KS-5-A #3 public IP"]
  CF --> IPS["Sauvage public IP"]
  IP1 --> T1["Traefik Edge hostNetwork"]
  IP2 --> T2["Traefik Edge hostNetwork"]
  IP3 --> T3["Traefik Edge hostNetwork"]
  IPS --> TS["Traefik Edge hostNetwork"]
  T1 --> SVC["Kubernetes Services over Tailscale/flannel"]
  T2 --> SVC
  T3 --> SVC
  TS --> SVC
```

## Shared Artifact Object Storage

Skirmshop has a shared internal S3-compatible object store for documents and
generated artifacts that should also land in Google Drive:

```text
apps and Synapse adapters
  -> MinIO skirmshop-drive-s3.backup-hub.svc.cluster.local:9000
  -> bucket skirmshop-drive
  -> PVC skirmshop-drive-mirror on nfs-cold
  -> Sauvage /srv/nfs/k8s-cold
  -> rclone export to Google Drive info@skirmshop.es
```

Operator LAN/Tailscale access:

- API: `https://skirmshop-s3.lan.e-dani.com`
- Console: `https://skirmshop-s3-console.lan.e-dani.com`

This store is for invoices, price lists, catalog/RAG source files and generated
media. It is not a replacement for Longhorn/Postgres/Redis/NATS or hot
application state. Workloads should write `s3://skirmshop-drive/<key>`
references into Synapse events and databases.

## Failure Model

- One KS-5-A can fail while k3s etcd keeps quorum.
- One public edge IP can fail while Cloudflare still has other A records.
- Multi-A does not provide health-based removal; use Cloudflare Load Balancer in
  the future if active origin failout is required.
