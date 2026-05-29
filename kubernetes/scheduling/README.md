# Scheduling Defaults

Use these patterns when moving workloads after KS-5 joins.

Core/platform and ingress services:

```yaml
affinity:
  nodeAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        preference:
          matchExpressions:
            - key: node-pool
              operator: In
              values: ["ks5-nvme"]
```

Fast database/storage services:

```yaml
nodeSelector:
  node-pool: ks5-nvme
  db-storage: fast
tolerations:
  - key: node-role.kubernetes.io/control-plane
    operator: Exists
    effect: NoSchedule
```

Sauvage heavy/stateless production services:

```yaml
affinity:
  nodeAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        preference:
          matchExpressions:
            - key: node-role
              operator: In
              values: ["heavy-worker"]
tolerations:
  - key: pocharlies.io/pool
    operator: Equal
    value: bulk
    effect: NoSchedule
```

x86 development services:

```yaml
nodeSelector:
  node-pool: home-dev
tolerations:
  - key: pocharlies.io/pool
    operator: Equal
    value: dev
    effect: NoSchedule
```

Do not move PostgreSQL/RabbitMQ with affinity alone. Take CNPG/RabbitMQ backups,
validate storage on the target node, then perform a controlled restore or
switchover.
