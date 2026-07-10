# OpenClaw failover before K3s node maintenance

This procedure moves the four RWO/single-writer OpenClaw workloads off one KS5
node before K3s maintenance. It is not an active-active rollout and has a short
controlled interruption per workload while Longhorn detaches and reattaches.

## Required deployed state

- The OpenClaw revision that adds the `openclaw-qwen36-telegram-router` PDB must
  be merged, Synced and Healthy. All four PDBs must have `minAvailable: 1`.
- The OpenClaw smoke checkout must be clean and exactly match the 40-character
  Argo revision.
- All three KS5 nodes, Argo CD, Longhorn and both backup locations must be
  healthy. Do not start while a release or sync operation is running.
- Use an absolute state-file path on protected operator storage.

## What `prepare` enforces

1. Acquires an immutable in-cluster maintenance lock. A second failover cannot
   silently overlap it.
2. Records pod/PVC/PV placement, router queue and `deadCount`, and the exact
   Argo sync policy.
3. Disables auto-sync/self-heal and sets Argo's skip-reconcile annotation for
   the short live-eviction window. This prevents self-heal or a hook sync from
   restoring a PDB or resuming the router mid-move.
4. Pauses the router and waits for `workerBusy=false`, then cordons the target.
5. Quiesces each gateway. For only the selected singleton it changes
   `minAvailable` from 1 to 0, waits until the PDB controller has observed the
   current generation and allows a disruption, and submits a `policy/v1`
   Eviction with the exact Pod UID as a precondition. It immediately restores
   the PDB to 1. There is no direct or force deletion fallback.
6. Requires the replacement on a different KS5, one attached Kubernetes
   `VolumeAttachment`, and a healthy Longhorn Volume attached to that same
   node. The router is treated as the fourth protected singleton.
7. While still paused, runs a social readiness/deep-security smoke plus the
   Workboard and strict Codex lifecycle smokes. It then resumes the router,
   drains the durable queue, rejects any increase in `deadCount`, and runs the
   normal active social smoke.
8. Restores the exact Argo policy. It leaves the target cordoned and the lock in
   place for the K3s operation.

Any failure restores all PDBs and Argo policy through the exit trap. The lock,
router pause and target cordon remain fail-closed so a human can inspect state
or use the explicit `abort` path.

## Prepare

```bash
export KUBECTL_BIN=kubectl
export EXPECTED_KUBE_CONTEXT=x86-k3s
export OPENCLAW_SMOKE_REPO=/absolute/path/to/clean/live/openclaw-checkout
export TARGET_NODE=ks5-cp-1
export FAILOVER_STATE=/absolute/protected/path/openclaw-${TARGET_NODE}.json
export CONFIRM_OPENCLAW_MAINTENANCE_FAILOVER="move-openclaw-off-${TARGET_NODE}"

scripts/openclaw_maintenance_failover.sh prepare \
  --target-node "${TARGET_NODE}" \
  --state-file "${FAILOVER_STATE}" \
  --smoke-repo "${OPENCLAW_SMOKE_REPO}"
```

Acceptance is explicit: four protected singletons off the target, all PDBs at
1, router active/idle, no new dead letter, Argo policy restored, target still
cordoned, and the immutable lock present.

Now run only the reviewed single-node K3s playbook stage. Its existing
`openclaw_failover_gate.sh --require-off-target` check includes the router and
will refuse the node if any singleton returned to it.

## Verify after K3s maintenance

Run this only after the K3s playbook reports the node Ready, passes all gates
and uncordons it:

```bash
scripts/openclaw_maintenance_failover.sh verify \
  --target-node "${TARGET_NODE}" \
  --state-file "${FAILOVER_STATE}" \
  --smoke-repo "${OPENCLAW_SMOKE_REPO}"
```

`verify` repeats placement, VolumeAttachment/Longhorn, PDB, router and all three
functional smokes, marks the evidence verified, and releases the lock.

## Fail-closed recovery

Do not manually uncordon, resume, delete a Pod, or patch a Longhorn attachment.
After diagnosing the recorded failure, use:

```bash
export CONFIRM_OPENCLAW_MAINTENANCE_ABORT="abort-openclaw-failover-${TARGET_NODE}"
scripts/openclaw_maintenance_failover.sh abort \
  --target-node "${TARGET_NODE}" \
  --state-file "${FAILOVER_STATE}" \
  --smoke-repo "${OPENCLAW_SMOKE_REPO}"
```

Abort restores all PDBs, waits for every Deployment, resumes and drains the
router without a `deadCount` increase, runs all smokes, removes only a cordon
created by this helper, marks the evidence aborted, and releases only its own
matching lock.

## Authoritative behavior used by the helper

- Kubernetes documents that the `policy/v1` Eviction API honors PDBs and the
  Pod termination grace period: <https://kubernetes.io/docs/concepts/scheduling-eviction/api-eviction/>.
- PDB status is used only after `observedGeneration` matches the resource
  generation: <https://kubernetes.io/docs/reference/kubernetes-api/policy/pod-disruption-budget-v1/>.
- Argo CD's `skip-reconcile` annotation stops Application processing:
  <https://argo-cd.readthedocs.io/en/release-3.4/user-guide/skip_reconcile/>.
  It is explicitly an alpha feature, so the helper also disables automated
  sync/self-heal, verifies the freeze before every eviction, stores the exact
  prior policy, and restores/verifies it through the exit trap.
- Longhorn recommends cordon/drain and allowing Kubernetes/CSI to migrate
  engines with workload Pods, without bypassing blocked drains:
  <https://longhorn.io/docs/1.12.0/maintenance/maintenance/>.
