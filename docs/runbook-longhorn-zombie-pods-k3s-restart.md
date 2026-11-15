# Longhorn zombie pods after a k3s restart ("no Pending workload pods")

Tracked in INFRA-41. Diagnosis is closed (INFRA-73). The fix shipped in
Longhorn v1.13.0 and is deployed and verified in this cluster (INFRA-122): on
2026-11-01 a single k3s restart on `ks5-cp-3` left the fixture pod `Ready` on
its own — same name and UID, 0 `FailedMount` events (50-entrega.md of
INFRA-168, 70-qa.md PASA). The recovery below is what cleared a stuck mount on
versions before v1.13.0; it stays the emergency answer if the symptom ever
reappears.

## Symptom

After a k3s restart on a KS5 node, workloads that mount Longhorn volumes get
stuck: the pod reports `Running 0/1 Ready` (readiness never flips) and its
events repeat:

```text
MountVolume.SetUp failed for volume "pvc-..." : ... no Pending workload pods
```

The pod is not Pending — it is already running on the node — so the kubelet
re-runs the mount forever, the volume setup never completes, and nothing
recovers on its own. The node and the Longhorn volume themselves are healthy;
recreating the pod clears it.

## Cause

Upstream bug: https://github.com/longhorn/longhorn/issues/13723.

Longhorn-manager resolves the volume's workload by looking for *Pending* pods.
After a k3s restart the kubelet re-issues `MountVolume.SetUp` for pods that are
already running, so there is no Pending pod to find, the mount fails with "no
Pending workload pods", and the retry loop never ends.

Fix: https://github.com/longhorn/longhorn-manager/pull/5085, merged to
`master` and the `v1.13.x` branch. The backport to the 1.12 line is merged too
— https://github.com/longhorn/longhorn-manager/pull/5225, into `v1.12.x` on
2026-09-13, tracked in https://github.com/longhorn/longhorn/issues/13995
(milestone v1.12.2) — but the v1.12.2 release that would ship it is **not
published** as of 2026-10-05 (latest published: v1.13.0).

## Version that fixes it

The fix ships in chart/image **v1.13.0** — the first published release that
contains it:

| version | fix |
| --- | --- |
| v1.11.2 | chart this cluster ran before INFRA-122 — no fix |
| v1.11.3 | published — no fix (backport did not land in 1.11.x) |
| v1.12.0, v1.12.1 | published (latest of the 1.12 line) — no fix |
| v1.12.2 | not published; the backport (longhorn-manager#5225) is merged to `v1.12.x` — only the release is missing |
| **v1.13.0** | **contains the fix** |

The GitOps surface is `infra/longhorn.yaml` (multi-source Application, chart
pinned there) plus `infra/longhorn/values.yaml` in `k8s-gitops-pocharlies`,
branch `deploy/prod`. There was **no configuration workaround** — before
v1.13.0, recovery was operational (recreate the pod).

### Upgrade path (INFRA-122)

Longhorn only supports upgrading one minor version at a time and does **not**
support downgrade — rolling back means restoring volumes from backup
(`docs/runbook-longhorn-systembackup.md`). From 1.11.2 the mandatory route is
therefore **1.11.2 → 1.12.1 → 1.13.0**, one PR per bump of `targetRevision` in
`infra/longhorn.yaml`:

1. **Pre-check before each bump**: read the upstream upgrade notes for the
   target version and compare `infra/longhorn/values.yaml` against that chart's
   defaults (`helm show values longhorn/longhorn --version <v>`) for renamed or
   removed keys. Chart 1.13.0 requires Kubernetes `>=1.34` (the cluster runs
   k3s v1.36 — fine).
2. **Verify a backup before every bump** (`kubectl get backups.longhorn.io -n
   longhorn-system`; the last one must be `Complete`).
3. Merge only with all volumes Healthy, none Degraded, and the volumes' engines
   upgraded to the current image (Longhorn's own EngineImage mechanism — e.g.
   `defaultSettings.concurrentAutomaticEngineUpgradePerNodeLimit` > 0 in
   `values.yaml`) before moving to the next minor.
4. The ArgoCD app is `automated` + `selfHeal`: **merging is the upgrade**. A
   volume left Degraded mid-route stops the path and escalates to the CTO —
   do not continue to the next minor, and do not downgrade.

**Status (2026-11-01): the route is complete — the cluster runs chart
v1.13.0.** For the **next** Longhorn bump, step 3 is manual work:
`concurrentAutomaticEngineUpgradePerNodeLimit` is back to `0` in
`infra/longhorn/values.yaml` (lowered after the 91 volumes were verified on
v1.13.0, INFRA-166), so engines do not follow the chart on their own. Raise
the limit, wait until every engine runs the new image, set it back to `0`,
and only then move `targetRevision`.

If the symptom ever reappears (e.g. on a node not yet on v1.13.0, or during
a future upgrade window), use the recovery below; it is unchanged.

## Recovery (operational)

Recreate the affected pod through its owning workload:

```bash
kubectl -n <namespace> rollout restart deployment/<name>
kubectl -n <namespace> rollout status deployment/<name>
```

NEVER delete pods by hand in `openclaw-qwen36`. That is the SC-230 lesson:
rollout, not delete — the namespace is guarded by a VAP and an approval bundle,
and a manual delete bypasses both. For workloads that are not Deployments,
recreate the pod through whatever controller owns it.

Verify: the replacement pod reaches `Ready` and shows no new
`MountVolume.SetUp failed` events.

## Reproduction in the operator window (INFRA-75)

Materials live in `infra/longhorn-zombie-test/` in `k8s-gitops-pocharlies`
(namespace `longhorn-zombie-test`, 1 GiB RWO Longhorn PVC, one busybox writer
pinned to `ks5-cp-3`, and an ArgoCD Application with no `automated` sync). The
Application is NOT in the root `kustomization.yaml` — the INFRA-168 cleanup
removed it after the 2026-11-01 measurement — so the fixture is deployed on
demand, never permanently.

1. In the operator window, apply the Application directly:
   `kubectl apply -f infra/longhorn-zombie-test/application.yaml` (repo
   `k8s-gitops-pocharlies`, branch `deploy/prod`). Its `syncPolicy` has no
   `automated` block on purpose — sync the app manually when ready.
2. Capture the pod before the restart:

   ```bash
   kubectl -n longhorn-zombie-test get pod -l app=longhorn-zombie-test \
     -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,NODE:.spec.nodeName
   ```

3. Restart k3s on `ks5-cp-3` (`sudo systemctl restart k3s`). This command is
   executed by the operator, or by a session explicitly authorized by
   `security` for the window — never ad-hoc. The 2026-11-01 measurement ran
   that way (Request INFRA-1046): one restart, no repeats.
4. Watch the pod and its events:

   ```bash
   kubectl -n longhorn-zombie-test get pod -l app=longhorn-zombie-test -w
   kubectl -n longhorn-zombie-test get events \
     --field-selector involvedObject.name=<pod-name> --sort-by=.lastTimestamp
   ```

   Expected reproduction: pod `Running 0/1 Ready` with repeated
   `MountVolume.SetUp failed ... no Pending workload pods`.
5. Capture the pod again. Same name and same UID as step 2 confirms the zombie
   state: the pod was never recreated, only its mount is wedged.
6. Recover with the rollout restart above and confirm the new pod (new UID)
   mounts and reaches `Ready`.
7. Cleanup: `kubectl delete -f infra/longhorn-zombie-test/application.yaml`.
   The Application's finalizer cascade-deletes the namespace contents —
   workloads and the PVC — which is what this fixture wants: everything under
   `longhorn-zombie-test` is disposable test data. Elsewhere in the cluster,
   never delete an ArgoCD Application by hand.
