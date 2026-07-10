# K3s production upgrade: v1.32.5+k3s1 to v1.35.6+k3s1

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
v1.32 API. `scripts/install-kubectl-k3s-upgrade.sh` installs checksum-pinned
v1.33.13 and v1.34.9 clients. Use v1.33.13 for the v1.32/v1.33 stages and
v1.34.9 for the v1.34/v1.35 stages so the client always stays within one minor
of both sides.

## Supported version path

Run four complete rolling stages:

1. `v1.32.5+k3s1` -> `v1.32.13+k3s1`
2. `v1.32.13+k3s1` -> `v1.33.13+k3s1`
3. `v1.33.13+k3s1` -> `v1.34.9+k3s1`
4. `v1.34.9+k3s1` -> `v1.35.6+k3s1`

Kubernetes v1.33 reached end of life on 2026-06-28. It is an adjacent-minor
hop only and must never be declared the production baseline. Kubernetes v1.35
is supported until 2027-02-28 and is the highest version simultaneously tested
by the installed Longhorn 1.11.2, CNPG 1.29/1.30, and Argo CD 3.4.2.

For each stage, upgrade the three servers one at a time, verify all servers are
at target, and only then upgrade agents one at a time. K3s explicitly requires
servers before agents and warns not to skip intermediate minors.

The v1.33 hop changes embedded etcd from the 3.5 line to 3.6. The later hops
remain on etcd 3.6 and update containerd and Kubernetes. K3s v1.34.9 and
v1.35.6 update the bundled Traefik chart to v40, but bundled Traefik, ServiceLB,
and local-storage are disabled in this cluster. The playbook checks the live
server config before every server restart.

Official references:

- K3s manual upgrade order: <https://docs.k3s.io/upgrades/manual>
- K3s automated upgrades: <https://docs.k3s.io/upgrades/automated>
- K3s v1.32.13 release: <https://github.com/k3s-io/k3s/releases/tag/v1.32.13%2Bk3s1>
- K3s v1.33.13 release: <https://github.com/k3s-io/k3s/releases/tag/v1.33.13%2Bk3s1>
- K3s v1.34.9 release: <https://github.com/k3s-io/k3s/releases/tag/v1.34.9%2Bk3s1>
- K3s v1.35.6 release: <https://github.com/k3s-io/k3s/releases/tag/v1.35.6%2Bk3s1>
- K3s etcd snapshots and restore: <https://docs.k3s.io/cli/etcd-snapshot>
- Kubernetes supported releases and EOL dates: <https://kubernetes.io/releases/>
- Kubernetes version skew policy: <https://kubernetes.io/releases/version-skew-policy/>
- Longhorn node maintenance: <https://longhorn.io/docs/1.11.2/maintenance/maintenance/>
- K3s secrets encryption: <https://docs.k3s.io/cli/secrets-encrypt>

## Hard prerequisites

Do not begin any K3s stage unless `scripts/k3s_upgrade_gate.sh preflight`
passes without exceptions.

### CloudNativePG

The live CNPG operator was 1.25.1. CNPG 1.25 supports Kubernetes only through
1.32; Kubernetes 1.33 is tested but not supported. Before the first K3s hop,
upgrade to official Helm chart 0.28.3 / operator 1.29.1. CNPG 1.29 supports
Kubernetes 1.33, 1.34, and 1.35.

CNPG 1.29.2 is the recommended latest patch, but the official Helm repository
did not publish a chart containing it: chart 0.28.3 contains 1.29.1 and the next
chart, 0.29.0, contains operator 1.30.0. Do not override only the image because
that would leave chart-managed CRDs behind. Keep chart 0.28.3/operator 1.29.1
unchanged throughout all four K3s stages: the official 1.29 support matrix
includes Kubernetes 1.33, 1.34 and 1.35. This avoids combining a database
operator/instance-manager rollout with control-plane upgrades.

Upgrade CNPG 1.30 and migrate the deprecated in-tree Barman configuration in a
separate maintenance change after K3s 1.35 and Secrets encryption are stable.
CNPG 1.30 release notes now defer removal of in-tree Barman to 1.31, so that
migration is recommended but is not a prerequisite for the K3s wave.

Before syncing the CNPG upgrade:

1. Require both `postgres-shared` and `keycloak-postgres` at 2/2 Ready and
   `Cluster in healthy state`.
2. Require `ContinuousArchiving=True` on both clusters.
3. Require an S3 backup in phase `completed` from the last 24 hours for each.
4. Wait for any currently running backup to finish.
5. Confirm no custom monitoring query needs access to user tables. CNPG 1.29.1
   changes the exporter to the limited `cnpg_metrics_exporter` role.
6. Defer CNPG 1.30-specific TLS status-port and Lease checks to its separate
   reviewed maintenance window.

The operator upgrade rolls instance managers. The GitOps values deliberately
spread cluster rollouts by 300 seconds and instance rollouts by 120 seconds.
After sync, require the operator at 2/2 Ready on different KS5 nodes, and wait
for both PostgreSQL clusters to return to all gates above. Check application
database connectivity before proceeding.

References:

- CNPG 1.29 support matrix: <https://cloudnative-pg.io/docs/1.29/supported_releases/>
- CNPG upgrade behavior: <https://cloudnative-pg.io/docs/1.29/installation_upgrade/>
- CNPG 1.29.1 release: <https://github.com/cloudnative-pg/cloudnative-pg/releases/tag/v1.29.1>
- CNPG 1.30.0 release: <https://github.com/cloudnative-pg/cloudnative-pg/releases/tag/v1.30.0>
- Official CNPG charts: <https://github.com/cloudnative-pg/charts/releases>

### Argo CD

All Applications must be Synced and Healthy. A pre-existing OutOfSync app can
only be classified as non-blocking after its live diff is captured and shown
not to affect control-plane, networking, storage, admission, secrets, databases,
or workloads scheduled on the node being drained. Degraded infrastructure or
data services are always a stop condition.

The live Argo CD is v3.4.2. Its official test matrix covers Kubernetes v1.32,
v1.33, v1.34, and v1.35. No Argo minor upgrade is required for this wave.
Reference: <https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/#tested-versions>.

### etcd and restore material

The preflight requires a successful off-node S3 snapshot from the last 12
hours. The playbook then creates a uniquely named local plus S3 snapshot before
each stage and verifies it appears in the S3 listing.

The K3s server token must also be retained in the approved secret manager. It
encrypts confidential bootstrap data and is required for restore. Never copy it
into Git, the runbook, CI logs, or chat.

### Longhorn

Longhorn 1.11.2's official production matrix explicitly tests Kubernetes 1.32,
1.33, 1.34, and 1.35. Keep Longhorn at 1.11.2 during the K3s wave; upgrading the
storage control plane while recovering a CSI incident would combine failure
domains. Evaluate the supported 1.11.x -> 1.12.x upgrade in a separate window.
Reference: <https://longhorn.io/docs/1.11.2/best-practices/#kubernetes-version>.

Require:

- every volume has at least two configured replicas;
- no volume is degraded or faulted;
- no replica rebuild is active;
- `node-drain-policy=block-if-contains-last-replica` and applied;
- only one node is upgraded at a time.

Never use `--disable-eviction`, `--force`, or ignore a blocked Longhorn drain.
Investigate the PDB/events. Longhorn explicitly warns that bypassing a blocked
drain removes its data-protection gate.

### OpenClaw controlled failover

Every server drain is also an OpenClaw availability event because the operator,
isolated social, and read-only gateways are separate, stateful singletons
constrained to the KS5 pool. Before cordoning a server, the playbook records all
three fully Ready gateway pods/nodes and Telegram router counters. It refuses to
start while any OpenClaw pod is Terminating, while a deployment is unavailable,
or while any gateway is outside a non-Ubuntu KS5 node.

The playbook deliberately refuses to cordon a node that hosts any protected
singleton: its `minAvailable: 1` PDB must never be bypassed. First run the
documented quiesce, router-pause, recreate-on-another-KS5, readiness, router
resume, and queue-drain procedure; then resume the idempotent K3s wave. The
evidence must identify each singleton independently. In every case the gate
then requires:

- exactly one fully Ready operator gateway, social gateway, read-only gateway,
  and Telegram router;
- every active OpenClaw pod on one of the four approved OVH nodes
  (`ks5-cp-1`, `ks5-cp-2`, `ks5-cp-3`, or `sauvage`), never `ubuntu` or a GPU node;
- ready, non-terminating endpoints and `/readyz=true` for all three gateways;
- OpenClaw Longhorn volumes healthy, attached, and not attached to `ubuntu`;
- router unpaused, delivery acknowledgements enabled, a live backend, and no
  increase in the dead-letter count;
- no OpenClaw pod left Terminating.

The evidence file records independent source/destination pairs, queue and
dead-letter counters, and an upper bound for failover time. Never start a
second node while the post-drain gate is pending.

The 2026-07-10 rehearsal exposed a shutdown defect: the regular proxy/native
Codex process could keep an old gateway pod `Terminating` until its 900-second
grace period even after the main gateway had exited. K3s maintenance is blocked
until the OpenClaw GitOps fix is deployed and a controlled rehearsal proves
that both singleton types terminate cleanly without consuming that full grace
period. The gate must report zero `Terminating` pods before every drain. Never
work around this by force-deleting the pod or shortening the grace period
without first proving graceful child-process and session shutdown.

### OpenClaw post-stage functional contract

Kubernetes readiness is necessary but not sufficient. After all agents complete
each version stage, and again after Secrets encryption, the playbooks run the
three official smoke scripts from the OpenClaw deployment repository:

- `scripts/smoke-social-gateway.sh` validates the isolated social runtime,
  least-privilege identity/storage contract, deep audit, and active router;
- `scripts/smoke-workboard.sh` creates and reads a card in a temporary state
  directory that is removed on exit;
- `scripts/smoke-codex-k8s.sh` performs the strict endpoint probe plus
  materialised create/send/read contract, validates the exact response, and
  deletes the smoke thread through the supported remote Codex command.

`scripts/openclaw_functional_gate.sh` refuses a dirty or unrelated checkout and
requires its HEAD to equal the exact revision reported by the Synced/Healthy
OpenClaw Argo Application. It also requires the reviewed
`codex-smoke-cleanup-contract:v1` marker, pins every nested `kubectl` call to the
expected context, and runs only when every node reports the completed stage
version. It requires `codex-smoke-cleanup-contract:v2` plus
`openclaw-smoke-session-cleanup-contract:v1`, so both the Codex thread and the
OpenClaw orchestration session/transcript are deleted and verified absent. No
real owner Telegram update is sent. A missing cleanup contract, failed
readback/delete, or any other smoke failure is a hard stop.

## Controller preparation

Create a private inventory from the example. Real IPs and SSH options belong in
the ignored `ansible/inventory/generated/` directory.

```bash
cp ansible/inventory/k3s-production.example.ini \
  ansible/inventory/generated/k3s-production.ini
scripts/install-kubectl-k3s-upgrade.sh
export KUBECTL_BIN="$PWD/.tools/kubectl-v1.33.13"
export EXPECTED_KUBE_CONTEXT=x86-k3s
export OPENCLAW_SMOKE_REPO=/absolute/path/to/k8s-openclaw-qwen36-pocharlies
```

The OpenClaw checkout must be clean and checked out at the exact live Argo
revision. Do not point the gate at an unmerged feature branch or copy smoke
scripts into this repository. The revision comparison makes the test contract
part of the deployed release rather than an operator-local approximation.

Keep `kubectl-v1.33.13` selected for stages 1 and 2. Before stage 3, switch to
`export KUBECTL_BIN="$PWD/.tools/kubectl-v1.34.9"` and retain it for stages 3
and 4.

Verify SSH, passwordless sudo, architecture, service name, and live K3s version
on the six Ansible-mutated hosts before the window:

```bash
ansible -i ansible/inventory/generated/k3s-production.ini 'k3s_cluster:!sauvage' \
  -b -m shell -a 'hostname; uname -m; systemctl is-active k3s || systemctl is-active k3s-agent; k3s --version'
```

Do not disable SSH host verification. Enrol and verify each host key out of band.

`sauvage` intentionally does not expose passwordless sudo. Do not weaken sudoers
or copy an interactive password into Ansible. Its agent binary is upgraded with
the official System Upgrade Controller v0.19.2, restricted by hostname to only
that node. The helper verifies the release manifests by SHA-256 and pins the
controller and per-K3s upgrade images by multi-architecture digest.

The helper only performs a fresh controller installation: it refuses to adopt
an existing namespace, CRD, ClusterRole, or binding. It rewrites and verifies
the controller image digest before the Deployment is ever submitted, so an
unpinned controller cannot win an image-pull race. Before every new node Plan,
it requires zero stale Plans/Jobs; a resumable Plan is accepted only when its
node selector, version, service account, concurrency, and prepare/upgrade image
exactly match the reviewed contract.

The helper does not let the controller drain the node. It first runs the same
production preflight, performs the explicit PDB-safe drain without `--force` or
`--disable-eviction`, and submits a one-node Plan only after the node is empty
and cordoned. The Plan's prepare container stores a root-only binary/config/unit
backup on the host. A failure leaves the node cordoned for diagnosis or the
explicit rollback action.

## Stage 1: latest v1.32 patch

```bash
export CONFIRM_K3S_UPGRADE=upgrade-v1.32.13-k3s1
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.32.5+k3s1 \
  -e target_version=v1.32.13+k3s1 \
  -e upgrade_phase=servers
```

The split sequence is mandatory: the playbook rejects an implicit or `all`
phase. Run `-e upgrade_phase=servers` first. Only after all three servers are at
target, upgrade `sauvage` with the commands below, then run
`-e upgrade_phase=agents`. Before touching any Ansible-managed agent, that phase
requires the Kubernetes API to report `sauvage` already at the target version;
it then verifies and skips `sauvage` without opening a sudo session. The
preflight accepts only the adjacent source and target versions, and
already-upgraded nodes are verified and skipped.

```bash
export CONFIRM_K3S_SAUVAGE_SUC=install-sauvage-system-upgrade-controller
scripts/k3s_upgrade_sauvage_suc.sh install

export CONFIRM_K3S_SAUVAGE_SUC=upgrade-sauvage-to-v1.32.13-k3s1
scripts/k3s_upgrade_sauvage_suc.sh upgrade \
  v1.32.5+k3s1 v1.32.13+k3s1

ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.32.5+k3s1 \
  -e target_version=v1.32.13+k3s1 \
  -e upgrade_phase=agents
```

Stop and observe the full cluster after the final infrastructure and functional
gates. Do not start stage 2 while any Application, PDB, CNPG cluster, Longhorn
volume, node, API, social, Workboard, or Codex contract is unhealthy.

## Stage 2: Kubernetes v1.33

```bash
export CONFIRM_K3S_UPGRADE=upgrade-v1.33.13-k3s1
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.32.13+k3s1 \
  -e target_version=v1.33.13+k3s1 \
  -e upgrade_phase=servers
```

Between the server and agent phases of stage 2:

```bash
export CONFIRM_K3S_SAUVAGE_SUC=upgrade-sauvage-to-v1.33.13-k3s1
scripts/k3s_upgrade_sauvage_suc.sh upgrade \
  v1.32.13+k3s1 v1.33.13+k3s1

ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.32.13+k3s1 \
  -e target_version=v1.33.13+k3s1 \
  -e upgrade_phase=agents
```

Kubernetes v1.33 is EOL. Do not pause the maintenance programme here or treat
this hop as the production baseline.

## Stage 3: Kubernetes v1.34

Switch to the client that remains within one minor of v1.33 and v1.35:

```bash
export KUBECTL_BIN="$PWD/.tools/kubectl-v1.34.9"
export CONFIRM_K3S_UPGRADE=upgrade-v1.34.9-k3s1
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.33.13+k3s1 \
  -e target_version=v1.34.9+k3s1 \
  -e upgrade_phase=servers

export CONFIRM_K3S_SAUVAGE_SUC=upgrade-sauvage-to-v1.34.9-k3s1
scripts/k3s_upgrade_sauvage_suc.sh upgrade \
  v1.33.13+k3s1 v1.34.9+k3s1

ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.33.13+k3s1 \
  -e target_version=v1.34.9+k3s1 \
  -e upgrade_phase=agents
```

After the complete v1.34.9 gate and observation window, keep CNPG at
chart 0.28.3/operator 1.29.1 and repeat its backup, archiving, connectivity, HA
operator and cluster readiness checks. Do not introduce the separate CNPG 1.30
or Barman migration into this control-plane window.

## Stage 4: supported production baseline v1.35

```bash
export CONFIRM_K3S_UPGRADE=upgrade-v1.35.6-k3s1
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.34.9+k3s1 \
  -e target_version=v1.35.6+k3s1 \
  -e upgrade_phase=servers

export CONFIRM_K3S_SAUVAGE_SUC=upgrade-sauvage-to-v1.35.6-k3s1
scripts/k3s_upgrade_sauvage_suc.sh upgrade \
  v1.34.9+k3s1 v1.35.6+k3s1

ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-upgrade.yml \
  -e from_version=v1.34.9+k3s1 \
  -e target_version=v1.35.6+k3s1 \
  -e upgrade_phase=agents
```

After all seven nodes pass the exact v1.35.6 final gate, remove the temporary
privileged controller and its cluster-wide RBAC:

```bash
export CONFIRM_K3S_SAUVAGE_SUC=remove-sauvage-system-upgrade-controller
scripts/k3s_upgrade_sauvage_suc.sh cleanup
```

Each node operation performs:

1. current-version and architecture assertion;
2. root-only backup of binary, config, unit, and SHA-256;
3. official release download with a pinned SHA-256;
4. OpenClaw pre-drain availability capture on servers;
5. on server operations, direct local `/readyz?verbose` checks on all three API
   servers, including both `etcd` readiness checks;
6. cordon, then server-side drain dry-run after CNPG and Longhorn observe it;
7. real drain without PDB bypass, followed by another direct readiness check on
   both surviving etcd/API peers immediately before the server restart;
8. atomic binary replacement and one service restart;
9. local service/API check;
10. cluster, Argo, Longhorn, CNPG, node-version, and OpenClaw gates;
11. uncordon.

If an agent operation fails after replacement, the Ansible rescue block restores
the old binary, restarts it, uncordons the node, and aborts the whole wave. A
server failure after replacement is intentionally different: the server remains
on the target binary and cordoned. Automatically starting the prior K3s/etcd
binary after datastore migration is not a safe rollback. Use the incident and
snapshot-restore procedure before changing that server again.

## Enable Kubernetes Secrets encryption at rest

This is a separate post-upgrade operation. Do not mix it into any binary
upgrade stage. The enable-existing-cluster procedure is available only from
K3s `v1.33.10+k3s1`; this runbook waits until every node is healthy at the
supported final baseline `v1.35.6+k3s1`.

Do not apply the control-plane role merely to add `secrets-encryption: true` on
an existing unencrypted cluster. The playbook must first initialise the shared
encryption configuration on S1, following the official HA order.

```bash
export CONFIRM_K3S_SECRETS_ENCRYPTION=enable-after-v1.35.6-healthy
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-enable-secrets-encryption.yml
```

The playbook verifies a recognised initial/resume state on all servers, takes
and verifies an S3 etcd snapshot, runs `k3s secrets-encrypt enable` on S1 only
when no configuration exists, persists the flag, restarts S1/S2/S3 serially,
requires the `start` stage with matching hashes,
runs `rotate-keys` on S1 only when the live stage has not already advanced,
waits for `reencrypt_finished`, restarts S1/S2/S3 serially again, verifies
enabled state and matching hashes, takes a second S3 snapshot, and reruns all
infrastructure and OpenClaw functional gates.

Both restart passes use the same production disruption discipline as the K3s
binary wave. For each server the playbook requires all three protected OpenClaw
singletons off the target, cordons it, runs a server-side drain dry-run, drains
without PDB bypass, restarts K3s, verifies the local encryption stage plus all
infrastructure/OpenClaw gates, and only then uncordons. A per-node root-only
marker under `/var/lib/k3s-upgrade-backups/secrets-encryption-v1.35.6/` records
the completed `start` and `reencrypt-finished` restart passes.

This makes the operation deliberately resumable. If the next target hosts a
protected singleton, perform the controlled failover and rerun the same
playbook; already completed nodes are checked against their marker, persisted
flag, and live encryption state and are not restarted again. The rotation step
uses live JSON status as the source of truth: it rotates only from disabled
`start` with matching hashes, waits through an in-progress re-encryption, and
never repeats `rotate-keys` after `reencrypt_finished`.

A failure before a restart is uncordoned automatically. A failure after restart
attempt remains cordoned for diagnosis. Markers are evidence for this one
operation, not authority after an etcd snapshot restore or node reinstall; a
recovery event requires a new reviewed plan and must not blindly reuse or
manually fabricate them.

Abort on any hash mismatch, non-ready server, or unexpected rotation stage.
Do not attempt manual repair of an encryption configuration from memory: use
the verified pre-encryption snapshot, original server token, and the official
versioned recovery procedure.

### Finalise the canonical Ansible defaults

This preparation branch deliberately keeps `k3s_version` at the verified live
`v1.32.5+k3s1` value and `k3s_secrets_encryption_enabled: false`. Advancing
either default before the guarded operations complete would create a second,
unguarded path that can skip minor versions or start a server with the
encryption flag before the shared configuration has been initialised.

Only after all seven nodes are exactly `v1.35.6+k3s1`, the final infrastructure
and OpenClaw gates pass, `k3s secrets-encrypt status` reports Enabled /
`reencrypt_finished` / all hashes match, and the post-encryption S3 snapshot is
verified, merge a separate finalisation change that sets:

```yaml
k3s_version: "v1.35.6+k3s1"
k3s_secrets_encryption_enabled: true
```

Do not run the generic control-plane or worker bootstrap roles during the
rolling window. If a node must be replaced mid-wave, stop the wave and bootstrap
it explicitly at the currently completed cluster stage; never rely on the
canonical default while the cluster is intentionally mixed-version.

## Rollback

### Immediate single-agent binary rollback

Use only during the mixed-version rolling stage, before declaring that stage
complete. The playbook accepts only one explicitly limited agent and only the
immediately preceding stage. It verifies the declared live version and all
production gates before cordon. Server binary rollback is intentionally
forbidden: rolling back one server executable is not a datastore rollback and
the official K3s procedure requires restoration of the snapshot taken on the
older minor.

```bash
export CONFIRM_K3S_BINARY_ROLLBACK=rollback-<node>-to-v1.34.9-k3s1
ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-rollback-binary.yml \
  --limit <node> \
  -e current_version=v1.35.6+k3s1 \
  -e rollback_version=v1.34.9+k3s1
```

Do not pass a control-plane node to this playbook. For a failed server after
binary replacement, keep it cordoned on the target binary and follow the
cluster/datastore restore section below if quorum or API integrity cannot be
recovered.

For `sauvage`, leave the node cordoned and use its verified on-host backup:

```bash
export CONFIRM_K3S_SAUVAGE_SUC=rollback-sauvage-to-v1.34.9-k3s1
scripts/k3s_upgrade_sauvage_suc.sh rollback \
  v1.35.6+k3s1 v1.34.9+k3s1
```

The rollback Job is hostname-bound, privileged only for the recovery window,
verifies the stored binary checksum, atomically restores it, and terminates the
agent process so its existing supervisor restarts the prior version.

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
- an OpenClaw failover that leaves a pod `Terminating` for the 900-second grace
  period or otherwise lacks verified graceful proxy/native Codex shutdown;
- any social gateway, ephemeral Workboard, or strict Codex create/send/read/delete
  contract failure after a completed version stage or Secrets encryption;
- an unknown Secrets-encryption JSON stage or mismatched `start` hashes;
- the target node cannot be returned Ready and schedulable after rollback.
