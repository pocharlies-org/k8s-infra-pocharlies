# K3s production upgrade: v1.32.5+k3s1 to v1.33.13+k3s1

Status: prepared; execution is gated. This runbook never permits skipping a
minor version, parallel control-plane restarts, PDB bypass, or a Longhorn drain
while replicas are degraded/rebuilding.

## Verified production inventory (2026-07-10)

| Role | Nodes | Architecture | Current version |
| --- | --- | --- | --- |
| server + control-plane + embedded etcd | `ks5-cp-1`, `ks5-cp-2`, `ks5-cp-3` | amd64 | `v1.32.5+k3s1` |
| general/edge agents | `ubuntu`, `sauvage` | amd64 | `v1.32.5+k3s1` |
| GPU agents | `nvidia-dgx`, `gx10-ec3d` | arm64 | `v1.32.5+k3s1` |

The three server nodes are the same three embedded-etcd members. All seven
nodes were Ready. Longhorn had 87 volumes, no degraded/faulted volume, no
replica rebuild, and no volume configured with fewer than two replicas.

The local default `kubectl` was v1.36.1 and is outside the supported skew for a
v1.32 API. `scripts/install-kubectl-k3s-upgrade.sh` installs a checksum-pinned
v1.33.13 client that is supported against both sides of this upgrade.

## Supported version path

Run two complete rolling stages:

1. `v1.32.5+k3s1` -> `v1.32.13+k3s1`
2. `v1.32.13+k3s1` -> `v1.33.13+k3s1`

For each stage, upgrade the three servers one at a time, verify all servers are
at target, and only then upgrade agents one at a time. K3s explicitly requires
servers before agents and warns not to skip intermediate minors.

The target release changes embedded etcd from the 3.5 line to 3.6 and updates
containerd. It also updates the bundled Traefik chart, but bundled Traefik,
ServiceLB, and local-storage are disabled in this cluster. The playbook checks
the live server config before every server restart.

Official references:

- K3s manual upgrade order: <https://docs.k3s.io/upgrades/manual>
- K3s v1.32.13 release: <https://github.com/k3s-io/k3s/releases/tag/v1.32.13%2Bk3s1>
- K3s v1.33.13 release: <https://github.com/k3s-io/k3s/releases/tag/v1.33.13%2Bk3s1>
- K3s etcd snapshots and restore: <https://docs.k3s.io/cli/etcd-snapshot>
- Kubernetes v1.33 skew/order policy: <https://v1-33.docs.kubernetes.io/releases/version-skew-policy/>
- Longhorn node maintenance: <https://longhorn.io/docs/1.11.2/maintenance/maintenance/>

## Hard prerequisites

Do not begin either K3s stage unless `scripts/k3s_upgrade_gate.sh preflight`
passes without exceptions.

### CloudNativePG

The live CNPG operator was 1.25.1. CNPG 1.25 supports Kubernetes only through
1.32; Kubernetes 1.33 is tested but not supported. The prerequisite GitOps
change upgrades to official Helm chart 0.28.3 / operator 1.29.1. CNPG 1.29 is
the newest charted operator line that officially supports Kubernetes 1.33.
CNPG 1.30 officially supports Kubernetes 1.34-1.36 only.

Before syncing the CNPG upgrade:

1. Require both `postgres-shared` and `keycloak-postgres` at 2/2 Ready and
   `Cluster in healthy state`.
2. Require `ContinuousArchiving=True` on both clusters.
3. Require an S3 backup in phase `completed` from the last 24 hours for each.
4. Wait for any currently running backup to finish.
5. Confirm no custom monitoring query needs access to user tables. CNPG 1.29.1
   changes the exporter to the limited `cnpg_metrics_exporter` role.

The operator upgrade rolls instance managers. The GitOps values deliberately
spread cluster rollouts by 300 seconds and instance rollouts by 120 seconds.
After sync, require the operator at 2/2 Ready on different KS5 nodes, and wait
for both PostgreSQL clusters to return to all gates above. Check application
database connectivity before proceeding.

References:

- CNPG 1.29 support matrix: <https://cloudnative-pg.io/docs/1.30/supported_releases/>
- CNPG upgrade behavior: <https://cloudnative-pg.io/docs/1.30/installation_upgrade/>
- CNPG 1.29.1 release: <https://github.com/cloudnative-pg/cloudnative-pg/releases/tag/v1.29.1>

### Argo CD

All Applications must be Synced and Healthy. A pre-existing OutOfSync app can
only be classified as non-blocking after its live diff is captured and shown
not to affect control-plane, networking, storage, admission, secrets, databases,
or workloads scheduled on the node being drained. Degraded infrastructure or
data services are always a stop condition.

### etcd and restore material

The preflight requires a successful off-node S3 snapshot from the last 12
hours. The playbook then creates a uniquely named local plus S3 snapshot before
each stage and verifies it appears in the S3 listing.

The K3s server token must also be retained in the approved secret manager. It
encrypts confidential bootstrap data and is required for restore. Never copy it
into Git, the runbook, CI logs, or chat.

### Longhorn

Require:

- every volume has at least two configured replicas;
- no volume is degraded or faulted;
- no replica rebuild is active;
- `node-drain-policy=block-if-contains-last-replica` and applied;
- only one node is upgraded at a time.

Never use `--disable-eviction`, `--force`, or ignore a blocked Longhorn drain.
Investigate the PDB/events. Longhorn explicitly warns that bypassing a blocked
drain removes its data-protection gate.

## Controller preparation

Create a private inventory from the example. Real IPs and SSH options belong in
the ignored `ansible/inventory/generated/` directory.

```bash
cp ansible/inventory/k3s-production.example.ini \
  ansible/inventory/generated/k3s-production.ini
scripts/install-kubectl-k3s-upgrade.sh
export KUBECTL_BIN="$PWD/.tools/kubectl-v1.33.13"
export EXPECTED_KUBE_CONTEXT=x86-k3s
```

Verify SSH, passwordless sudo, architecture, service name, and live K3s version
on every inventory host before the window:

```bash
ansible -i ansible/inventory/generated/k3s-production.ini k3s_cluster \
  -b -m shell -a 'hostname; uname -m; systemctl is-active k3s || systemctl is-active k3s-agent; k3s --version'
```

Do not disable SSH host verification. Enrol and verify each host key out of band.

## Stage 1: latest v1.32 patch

```bash
export CONFIRM_K3S_UPGRADE=upgrade-v1.32.13-k3s1
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.32.5+k3s1 \
  -e target_version=v1.32.13+k3s1
```

Stop and observe the full cluster after the final gate. Do not start stage 2
while any Application, PDB, CNPG cluster, Longhorn volume, node, or API check is
unhealthy.

## Stage 2: Kubernetes v1.33

```bash
export CONFIRM_K3S_UPGRADE=upgrade-v1.33.13-k3s1
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.32.13+k3s1 \
  -e target_version=v1.33.13+k3s1
```

Each node operation performs:

1. current-version and architecture assertion;
2. root-only backup of binary, config, unit, and SHA-256;
3. official release download with a pinned SHA-256;
4. server-side drain dry-run;
5. cordon and real drain without PDB bypass;
6. atomic binary replacement and one service restart;
7. local service/API check;
8. cluster, Argo, Longhorn, CNPG, and node-version gates;
9. uncordon.

If a node operation fails after replacement, the Ansible rescue block restores
the old binary, restarts it, uncordons the node, and aborts the whole wave.

## Rollback

### Immediate single-node binary rollback

Use only during the mixed-version rolling stage, before declaring that stage
complete. Agents are safe to roll back to the prior binary. A server rollback
requires explicit acknowledgement because rolling back one executable is not a
substitute for restoring a datastore after a successful etcd upgrade.

```bash
export CONFIRM_K3S_BINARY_ROLLBACK=rollback-<node>-to-v1.32.13-k3s1
# Servers only:
export CONFIRM_K3S_SERVER_ROLLBACK_RISK=acknowledge-etcd-compatibility-risk
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-rollback-binary.yml \
  --limit <node> \
  -e current_version=v1.33.13+k3s1 \
  -e rollback_version=v1.32.13+k3s1
```

### Cluster/datastore rollback

If API/etcd integrity is not restored by the per-node rescue, freeze all writes
and use the official multi-server snapshot-restore procedure. This is a
cluster-wide recovery event:

1. record the selected S3 snapshot name and verify the original server token;
2. stop K3s on every server;
3. on one server, run `k3s server --cluster-reset
   --cluster-reset-restore-path=<snapshot>` with its S3 configuration;
4. restart that server without `--cluster-reset`;
5. remove the stale etcd data directory on the other servers as directed by the
   official K3s multi-server restore procedure, then start them to rejoin;
6. validate etcd membership, all nodes, Argo, Longhorn, CNPG, and applications;
7. start agents and reopen writes only after all gates pass.

Do not improvise the destructive restore commands from memory; follow the
versioned K3s restore page linked above and preserve the failed disks first.

## Stop conditions

Abort immediately on any of the following:

- fewer than two Ready control-plane/etcd peers while upgrading a server;
- drain cannot complete without bypassing a PDB;
- any Longhorn degraded/faulted volume or rebuild;
- any CNPG cluster below desired Ready instances, failed archiving, or stale backup;
- API `/readyz` failure, unexpected node version, or service restart loop;
- new Argo OutOfSync/Degraded state;
- the target node cannot be returned Ready and schedulable after rollback.
