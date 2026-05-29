# Claude Code Handoff: KS-5 HA k3s Rollout

## Prompt To Give Claude Code

Actua como SRE/DevOps senior y continua el rollout HA de k3s con 3 servidores
KS-5-A de OVH/Kimsufi. Trabaja en:

```text
/home/dibanez/k8s/k8s-infra-pocharlies
```

No imprimas secretos, tokens, auth keys, claves API, `K3S_TOKEN`, ni contenido
de `/home/dibanez/k8s/ks5-ha.runtime.env`. Si necesitas usar secretos, leelos
desde Vault/Kubernetes Secret o desde ese runtime env con permisos `0600`.

## Contexto Real Actual

Cluster actual:

- `ubuntu`: nodo x86 en casa, actualmente unico `control-plane,etcd,master`,
  k3s `v1.32.5+k3s1`, Tailscale `100.83.56.98`.
- `sauvage`: OVH KS-7/worker edge actual, IP publica `57.129.17.172`,
  Tailscale `100.109.183.9`.
- `nvidia-dgx` y `gx10-ec3d`: GPU/dev, conservar intactos.
- ExternalDNS usa Cloudflare con `domain-filter=e-dani.com` y `policy=upsert-only`.
- Traefik Edge esta desplegado como DaemonSet con `hostNetwork` en Sauvage.

Objetivo:

- 3 KS-5-A como unicos k3s `server/etcd`.
- `ubuntu` pasa a worker/dev, pero NO demotarlo si aun hay pods productivos ahi.
- Sauvage queda heavy/bulk/edge.
- KS-5 NVMe queda control-plane, ingress, core y datos rapidos.
- No migrar stateful automaticamente: `ALLOW_STATEFUL_MIGRATION=no`.

## Estado OVH Actual

OVH EU sigue exponiendo solo 2 de los 3 KS-5-A pedidos:

- `ns3182586.ip-141-94-73.eu`, IP `141.94.73.52`, DC `rbx8`,
  `KS-5-A | Intel Xeon E-2274G`, OS `none_64`.
- `ns3195172.ip-145-239-194.eu`, IP `145.239.194.168`, DC `rbx8`,
  `KS-5-A | Intel Xeon E-2274G`, OS `none_64`.

OVH CA ve Sauvage:

- `ns31652917.ip-57-129-17.eu`, IP `57.129.17.172`, DC `lim3`.

No instalar Ubuntu ni unir etcd hasta que OVH exponga los 3 KS-5-A. No continuar
con 2, porque el objetivo es quorum resiliente en 3 nodos nuevos.

## Estado Del Autopilot

Hay un runner:

```bash
scripts/autopilot_ks5_rollout.sh
```

Se lanzo como transient user systemd unit:

```bash
systemctl --user status ks5-ha-autopilot.service
tail -f /home/dibanez/k8s/ks5-ha-autopilot.log
```

El ultimo estado conocido es `failed`, exit code `3`, tras esperar 12h porque
OVH solo exponia 2/3 KS-5-A:

```text
Timed out waiting for 3 KS-5-A servers in OVH.
```

El runtime env esta fuera de Git:

```text
/home/dibanez/k8s/ks5-ha.runtime.env
```

Tiene permisos `0600` y contiene Tailscale auth key generada, Cloudflare token,
Cloudflare zone id, K3S token, SSH public key y gates. No mostrarlo. La auth key
Tailscale fue generada a partir de una API key y puede caducar; si el rollout se
reanuda mucho despues, pide una nueva API/auth key al usuario y regenera.

GOTCHA: Tailscale no permitio generar auth key con tags. El runtime usa:

```text
TAILSCALE_SKIP_TAGS=true
```

El rol Ansible omite `--advertise-tags` si esa variable esta activa. Etiquetar
nodos Tailscale despues cuando tag owners/ACL esten preparados.

## Secretos Ya Gestionados

OVH EU y OVH CA estan en Vault/Kubernetes ExternalSecrets:

- Vault KV: `secret/infra/ovh/claude-eu`
- Vault KV: `secret/infra/ovh/ca`
- K8s: `infra-secrets/ovh-claude-eu`
- K8s: `infra-secrets/ovh-ca`

Wrapper para usar OVH sin imprimir credenciales:

```bash
scripts/with_ovh_env.sh --secret-name ovh-claude-eu -- .venv/bin/python scripts/ovh_install.py discover
scripts/with_ovh_env.sh --secret-name ovh-ca -- .venv/bin/python scripts/ovh_install.py discover
```

1Password no se pudo actualizar porque `op` no conecta con la app desktop local.
No persistir OTPs puntuales.

## Archivos Clave

Lee primero:

- `docs/runbook.md`
- `docs/checklist.md`
- `docs/architecture.md`
- `scripts/autopilot_ks5_rollout.sh`
- `scripts/ks5_inventory_from_ovh.sh`
- `scripts/ovh_install.py`
- `scripts/with_ovh_env.sh`
- `scripts/preflight.sh`
- `scripts/preflight_production.sh`
- `scripts/verify.sh`
- `scripts/verify_placement.sh`
- `ansible/playbooks/bootstrap-ks5.yml`
- `ansible/playbooks/demote-x86-to-worker.yml`
- `ansible/roles/tailscale/tasks/main.yml`
- `ansible/roles/k3s_control_plane/tasks/main.yml`
- `ansible/roles/k3s_worker/tasks/main.yml`
- `ansible/roles/node_labels/tasks/main.yml`
- `networking/traefik-edge/values.yaml`
- `kubernetes/traefik/healthcheck-route.yaml`
- `kubernetes/storage/longhorn-prod-nvme.yaml`
- `kubernetes/secrets/kustomization.yaml`

Generated/ignored files you may inspect but must not commit:

- `/home/dibanez/k8s/ks5-ha.runtime.env`
- `/home/dibanez/k8s/ks5-ha-autopilot.log`
- `ansible/inventory/generated/ks5.ini`
- `ansible/inventory/generated/ks5.partial.ini`
- `docs/dns-backups/*.json`
- `docs/dns-backups/*.bind`
- `terraform/ovh/terraform.tfvars`

## Safe Resume Commands

Check current OVH state:

```bash
cd /home/dibanez/k8s/k8s-infra-pocharlies
scripts/with_ovh_env.sh --secret-name ovh-claude-eu -- .venv/bin/python scripts/ovh_install.py discover
scripts/with_ovh_env.sh --secret-name ovh-ca -- .venv/bin/python scripts/ovh_install.py discover
```

Regenerate inventory. It must show 3 KS-5-A before proceeding:

```bash
set -a
source /home/dibanez/k8s/ks5-ha.runtime.env
set +a
scripts/ks5_inventory_from_ovh.sh ansible/inventory/generated/ks5.ini
```

If it still says `ks5_count=2`, stop and diagnose OVH order/service delivery.
Do not run install with 2 nodes.

If it shows 3 and runtime auth key is still valid, resume autopilot:

```bash
systemctl --user reset-failed ks5-ha-autopilot.service 2>/dev/null || true
systemd-run --user \
  --unit=ks5-ha-autopilot \
  --description='KS-5 HA autopilot rollout' \
  --property=WorkingDirectory=/home/dibanez/k8s/k8s-infra-pocharlies \
  --setenv=OVH_WAIT_SECONDS=43200 \
  --setenv=OVH_WAIT_INTERVAL=300 \
  --setenv=RUNTIME_ENV=/home/dibanez/k8s/ks5-ha.runtime.env \
  /home/dibanez/k8s/k8s-infra-pocharlies/scripts/autopilot_ks5_rollout.sh
```

Monitor:

```bash
systemctl --user status ks5-ha-autopilot.service
tail -f /home/dibanez/k8s/ks5-ha-autopilot.log
```

## Autopilot Behavior

The runner does:

1. `scripts/preflight.sh`
2. Wait until `scripts/ks5_inventory_from_ovh.sh` returns 3 KS-5-A in `rbx*`.
3. Install Ubuntu 24.04 via OVH API with `CONFIRM_OVH_REINSTALL`.
4. Wait for SSH on all KS-5 public IPs.
5. Run Ansible bootstrap for Tailscale + k3s server/etcd.
6. Validate `ks5-cp-1..3` Ready and etcd count `4` before any demotion.
7. If allowed, apply Traefik HA + DNS target rewrite.
8. Refuse x86 demotion if production pods still run on `ubuntu` and
   `ALLOW_PRODUCTION_DISRUPTION` is not explicitly `ok`.

## Hard Safety Rules

- Do not commit or print secrets.
- Do not install/reinstall OVH servers unless all 3 KS-5-A are visible.
- Do not demote `ubuntu` while production/stateful pods remain on it unless the
  user explicitly accepts production disruption in the current session.
- Do not migrate PostgreSQL/RabbitMQ/Qdrant/FalkorDB/brain PVCs by nodeSelector
  only. Migration needs backup + restore validation.
- Do not destroy servers without `CONFIRM_DESTROY=<serviceName>`.
- Cloudflare DNS changes require backup JSON/BIND first.
- Keep `policy=upsert-only` for external-dns.
- Keep GPU nodes intact.

## Validation Commands

```bash
bash -n scripts/*.sh
.venv/bin/python -m py_compile scripts/ovh_install.py scripts/cloudflare_backup.py scripts/update_external_dns_targets.py
terraform -chdir=terraform/ovh validate
ansible-playbook --syntax-check ansible/playbooks/bootstrap-ks5.yml ansible/playbooks/demote-x86-to-worker.yml ansible/playbooks/harden-existing-workers.yml
kubectl apply --dry-run=server -k kubernetes/secrets
kubectl kustomize kubernetes/storage >/tmp/storage.yaml
kubectl kustomize kubernetes/traefik >/tmp/traefik.yaml
kubectl kustomize kubernetes/node-labels >/tmp/node-labels.yaml
DOMAIN=e-dani.com scripts/verify.sh --pre
scripts/verify_placement.sh
```

After KS-5 join:

```bash
EXPECTED_KS5_COUNT=3 scripts/verify.sh --ks5
EXPECTED_ETCD_COUNT=4 scripts/verify.sh --etcd
kubectl get --raw /readyz?verbose
kubectl get nodes -o wide
kubectl get nodes -L node-pool,storage,db-storage,workload,topology,region
```

## Current Decision Notes

- The rollout must wait for the third OVH KS-5-A service to materialize.
- The generated Tailscale auth key is untagged; Kubernetes labels still apply.
- Existing node relabel/taint is gated to avoid breaking scheduling while
  production still lives on `ubuntu`.
- Statefulness stays put until a separate backup/restore migration phase.

