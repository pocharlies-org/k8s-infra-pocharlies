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

The normal join/rejoin endpoint is `https://k8s.lan.e-dani.com:6443`.
It resolves inside the tailnet to the stable Tailscale Service
`svc:k3s-api` (`k3s-api.taile0ad27.ts.net`), whose approved backends are the
three KS-5 control-plane nodes. Do not point `server:` back to the retired x86
worker `100.83.56.98`.

Before using the endpoint for recovery, require all of the following:

```bash
dig +short k8s.lan.e-dani.com A
tailscale status --json | jq '.Self.CapMap."service-host"'
kubectl --server=https://k8s.lan.e-dani.com:6443 get --raw=/readyz
```

The K3s API certificate must contain `DNS:k8s.lan.e-dani.com`. Each
control-plane persists its Service host mapping as
`tcp:6443 -> localhost:6443`. A newly rebuilt host must be approved for
`svc:k3s-api` in the Tailscale API/admin console before it can receive traffic.

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
