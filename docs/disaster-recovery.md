# Disaster Recovery

## DNS Rollback

```bash
export CONFIRM_CLOUDFLARE_RESTORE=restore-dns-from-backup
scripts/rollback.sh dns docs/dns-backups/pre-ks5.json
```

`external-dns` uses `upsert-only`; it should not delete records during normal
operation.

## Traefik Rollback

```bash
export CONFIRM_TRAEFIK_ROLLBACK=rollback-traefik-edge-to-sauvage
scripts/rollback.sh traefik
```

Then verify:

```bash
kubectl -n traefik-edge get ds traefik-edge -o wide
curl -fsS --resolve "$DOMAIN:443:$CURRENT_SAUVAGE_PUBLIC_IP" "https://$DOMAIN/"
```

## k3s / etcd

Keep the existing etcd snapshot runbook in `k8s-gitops-pocharlies` as the
authoritative cluster restore flow. Before demoting x86, copy the latest
snapshot to durable storage and verify it is present in MinIO.

Rollback options:

- If KS-5 join fails: drain/delete the failed KS-5 node and retry Ansible.
- If quorum is unhealthy before x86 demotion: keep x86 as server and remove the
  broken KS-5 member.
- If quorum breaks after x86 demotion: restore from the latest healthy etcd
  snapshot onto x86 or one KS-5 node, then rejoin the remaining nodes.

## Node Removal

```bash
export CONFIRM_NODE_REMOVE=remove-k8s-node
scripts/rollback.sh remove-node ks5-cp-1
```

For Tailscale:

```bash
export CONFIRM_TAILSCALE_REMOVE=remove-tailscale-node
scripts/rollback.sh tailscale ks5-cp-1
```

This logs the node out via SSH; remove stale devices from the Tailscale admin
console/API afterward if needed.
