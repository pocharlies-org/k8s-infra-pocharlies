# KS-5 HA Runbook

## Preconditions

Install local tooling:

```bash
python3 -m pip install -r requirements.txt
cd ansible && ansible-galaxy collection install -r requirements.yml
```

Required environment variables:

```bash
cp .env.example ../ks5-ha.env
$EDITOR ../ks5-ha.env
set -a
source ../ks5-ha.env
set +a
```

Never commit env files, tfvars with secrets, inventories generated from private
addresses, or Cloudflare backups.

OVH credentials for this rollout are also stored in Vault at:

```text
secret/infra/ovh/claude-eu
secret/infra/ovh/ca
```

They are synced to Kubernetes by `kubernetes/secrets/ovh-*.yaml` as:

```text
infra-secrets/ovh-claude-eu
infra-secrets/ovh-ca
```

Prefer `scripts/with_ovh_env.sh <command>` to run OVH tooling without printing
or manually exporting credentials.

Use `--secret-name ovh-ca` for the CA account:

```bash
scripts/with_ovh_env.sh --secret-name ovh-ca -- .venv/bin/python scripts/ovh_install.py discover
```

## Phase 0: Preflight

```bash
scripts/preflight.sh
```

This validates local tooling, Kubernetes readiness, ArgoCD presence, required
environment variables, and creates Cloudflare DNS backups when token/zone are
available.

## Autopilot Mode

Runtime secrets are loaded from `/home/dibanez/k8s/ks5-ha.runtime.env`, which is
outside Git and must stay mode `0600`.

The current overnight runner is a transient user systemd unit:

```bash
systemctl --user status ks5-ha-autopilot.service
tail -f /home/dibanez/k8s/ks5-ha-autopilot.log
```

Stop it safely with:

```bash
systemctl --user stop ks5-ha-autopilot.service
```

The runner waits for all three KS-5-A servers to appear in OVH, installs Ubuntu
24.04, bootstraps Tailscale/k3s, validates etcd quorum, and can perform Traefik
HA/DNS cutover. It does not migrate stateful data. It refuses to demote
`ubuntu` while non-system production pods still run there unless
`ALLOW_PRODUCTION_DISRUPTION=ok` is explicitly added.

## Phase 1: OVH Discovery

```bash
scripts/with_ovh_env.sh -- .venv/bin/python scripts/ovh_install.py discover
scripts/with_ovh_env.sh -- .venv/bin/python scripts/ovh_install.py catalog \
  --offer-name KS-5-A \
  --require "Intel Xeon E-2274G" \
  --require "SSD NVMe" \
  --require "Soft RAID" \
  --reject HDD \
  --reject SATA
```

Do not proceed unless the selected offer is KS-5-A and the selected storage
option is SSD NVMe Soft RAID. It is acceptable for the catalog page to list SATA
alternatives; it is not acceptable to select them.

## Phase 2: Order KS-5-A

Fill `terraform/ovh/terraform.tfvars` from the OVH catalog. Then:

```bash
cd terraform/ovh
../../scripts/with_ovh_env.sh terraform init
../../scripts/with_ovh_env.sh terraform plan -var-file=terraform.tfvars \
  -var enable_order=true \
  -var confirm_ovh_order=order-3-ks5
../../scripts/with_ovh_env.sh terraform apply -var-file=terraform.tfvars \
  -var enable_order=true \
  -var confirm_ovh_order=order-3-ks5
```

If OVH cannot provide three KS-5-A in `rbx/Roubaix`, stop. Do not mix in
HDD/SATA variants.

Current selected KS-5-A order inputs:

- Plan: `26sk50a-v1` (`KS-5-A | Intel Xeon E-2274G`).
- Datacenter override: `rbx` / Roubaix, from the OVH cart selection.
- Memory: `ram-64g-ecc-2666-26sk50a-v1`.
- Storage: `softraid-2x960nvme-26sk50a-v1`.
- Bandwidth: `bandwidth-500-ks-gen0`.
- Expected first month from cart: `224,99 €` incl. IVA.
- Expected recurring: `127,01 €/mes` incl. IVA.

Current discovery after the order:

- OVH CA sees Sauvage: `ns31652917.ip-57-129-17.eu`, `57.129.17.172`,
  datacenter `lim3`.
- OVH EU currently exposes 2 KS-5-A in `rbx8`:
  `ns3182586.ip-141-94-73.eu` / `141.94.73.52` and
  `ns3195172.ip-145-239-194.eu` / `145.239.194.168`.
- Wait for the third KS-5-A before joining etcd; do not demote x86 with only two
  new servers.

## Phase 3: Install Ubuntu Server 24.04 LTS

After OVH delivers service names:

```bash
export CONFIRM_OVH_REINSTALL=install-ubuntu-24.04
scripts/with_ovh_env.sh -- .venv/bin/python scripts/ovh_install.py install-ubuntu \
  --service-name <ks5-1-service> --hostname ks5-cp-1 \
  --service-name <ks5-2-service> --hostname ks5-cp-2 \
  --service-name <ks5-3-service> --hostname ks5-cp-3 \
  --fallback-no-raid
scripts/with_ovh_env.sh -- .venv/bin/python scripts/ovh_install.py wait \
  --service-name <ks5-1-service> \
  --service-name <ks5-2-service> \
  --service-name <ks5-3-service>
scripts/with_ovh_env.sh -- .venv/bin/python scripts/ovh_install.py inventory \
  --service-name <ks5-1-service> --hostname ks5-cp-1 \
  --service-name <ks5-2-service> --hostname ks5-cp-2 \
  --service-name <ks5-3-service> --hostname ks5-cp-3
```

This erases disks. The confirmation variable is intentionally ugly.

## Phase 4: Bootstrap Tailscale and k3s

Retrieve the current k3s token from the secret manager or the existing x86 node,
without writing it to Git.

```bash
export K3S_TOKEN=...
export K3S_JOIN_SERVER_IP=100.83.56.98
cd ansible
ansible-playbook playbooks/bootstrap-ks5.yml
```

Validate:

```bash
scripts/verify.sh --k8s
scripts/verify.sh --etcd
```

## Phase 5: Demote x86 to Worker

Only after the three KS-5-A etcd members are Ready:

```bash
export CONFIRM_DEMOTE_X86=demote-x86-after-ks5-quorum
export K3S_JOIN_SERVER_IP=<ks5-cp-1-tailscale-ip>
cd ansible
ansible-playbook playbooks/demote-x86-to-worker.yml
```

## Phase 6: Traefik and DNS

Merge `kubernetes/traefik/values-ha.yaml` into
`networking/traefik-edge/values.yaml`, then deploy the health route:

```bash
kubectl apply -k kubernetes/traefik
```

Back up DNS and update public targets:

```bash
export PUBLIC_EDGE_TARGETS=KS5_1,KS5_2,KS5_3,57.129.17.172
python3 scripts/cloudflare_backup.py backup-json --output docs/dns-backups/pre-ks5.json
python3 scripts/cloudflare_backup.py backup-bind --output docs/dns-backups/pre-ks5.bind
export CONFIRM_DNS_TARGET_REWRITE=update-ha-targets
python3 scripts/update_external_dns_targets.py --repo-root . --targets "$PUBLIC_EDGE_TARGETS" --write
```

## Public health-check NodePort guard

The Traefik LAN `externalTrafficPolicy: Local` health check currently reserves
`TCP/32763`. Kubernetes installs its `KUBE-*` accept path before UFW, so this
one port needs a dedicated pre-KUBE guard on every public k3s edge: the three
KS-5 control planes and `sauvage`.

The Ansible role creates only the `inet edge_wan_guard` table and the
`edge-wan-firewall.service` unit. It does not enable or modify the global
`nftables.service`, and it does not alter UFW. The table has an accept policy
and rejects only `TCP/32763` received on the verified WAN interface. Public
`80/tcp`, `443/tcp`, `tailscale0`, and non-WAN/LAN traffic remain outside the
rule. The role does not open `4444/tcp` (or any other port); any pre-existing
per-host policy for it remains unchanged.

Use the Tailnet inventory and Ansible's configured `become` authorization; no
direct public SSH or nested `sudo ssh` is used. First record the global
nftables service state:

```bash
cd ansible
ansible edge_wan_firewall -i inventory/ks5-tailscale.ini -b \
  -m command -a 'systemctl is-enabled nftables.service'
ansible-playbook -i inventory/ks5-tailscale.ini \
  playbooks/edge-wan-firewall.yml --limit ks5-cp-1 --check --diff
ansible-playbook -i inventory/ks5-tailscale.ini \
  playbooks/edge-wan-firewall.yml --limit ks5-cp-1
```

Before continuing, verify from an external probe that `32763/tcp` is closed on
the canary while its intentionally published `80/tcp` and `443/tcp` remain
available. If `4444/tcp` was intentionally published on that host, verify it
was not changed; do not open it as part of this rollout. Verify from the
Tailnet that SSH, the Kubernetes API, and node readiness remain healthy. Then
apply serially to all four edge hosts:

```bash
ansible-playbook -i inventory/ks5-tailscale.ini \
  playbooks/edge-wan-firewall.yml
ansible edge_wan_firewall -i inventory/ks5-tailscale.ini -b \
  -m command -a 'systemctl is-enabled nftables.service'
```

Rollback removes only the dedicated table, helper, ruleset, and unit:

```bash
ansible-playbook -i inventory/ks5-tailscale.ini \
  playbooks/edge-wan-firewall.yml \
  -e edge_wan_firewall_state=absent
```

## Ports

Public:

- `80/tcp`, `443/tcp`: Traefik Edge.
- `4444/tcp`: Tesla Fleet Telemetry passthrough if still needed.
- `22/tcp`: bootstrap SSH; restrict further to Tailscale or trusted IPs after
  first successful Ansible run.

Tailscale/private:

- `6443/tcp`: Kubernetes API.
- `2379/tcp`, `2380/tcp`: etcd peers.
- All pod/service overlay traffic through k3s/flannel over Tailscale.
