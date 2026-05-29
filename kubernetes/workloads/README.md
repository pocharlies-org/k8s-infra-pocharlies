# Workload Migration Notes

- OpenClaw/plugins/stateless production: prefer `node-pool=ovh-heavy` on
  `sauvage`, with controlled fallback to KS-5.
- RabbitMQ, PostgreSQL/CNPG, Qdrant, FalkorDB/brain and other fast-disk
  stateful workloads: prefer `node-pool=ks5-nvme` and `db-storage=fast`.
- x86 `ubuntu`: development, dashboards, `dgx-infra`, experiments and LLM/dev
  services only; production must not require it.
- Core services, ingress, cert-manager, external-dns, ArgoCD and light
  observability: prefer `node-pool=ks5-nvme`.
- GPU workloads remain on existing `dedicated=llm` / GPU labels.
