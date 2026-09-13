# Longhorn zombie pods after a k3s restart ("no Pending workload pods")

Tracked in INFRA-41. Diagnosis is closed (INFRA-73); this runbook is the
operational answer until a fixed Longhorn release exists.

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
`master` and the `v1.13.x` branch only.

## Version that fixes it

As of 2026-09-13 no published Longhorn release contains the fix:

| version | status |
| --- | --- |
| v1.12.1 | latest published release — no fix |
| v1.13.0 | planned 2026-09-23 — will contain the fix |
| v1.11.4, v1.12.2 | backports pending — not published yet |

This cluster runs chart 1.11.2. The GitOps surface is `infra/longhorn.yaml`
(multi-source Application, chart pinned there) plus `infra/longhorn/values.yaml`
in `k8s-gitops-pocharlies`, branch `deploy/prod`. There is **no configuration
workaround** — recovery is operational (recreate the pod). Do not bump the
chart until a version with the fix is published; bumping to v1.12.1 today
changes nothing except risk. When v1.13.0 or a backport lands, the change is a
PR raising `targetRevision` in `infra/longhorn.yaml` only.

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
directory is NOT referenced by the root `kustomization.yaml`, so merging its PR
deploys nothing.

1. In the operator window, a follow-up PR adds
   `infra/longhorn-zombie-test/application.yaml` to the root
   `kustomization.yaml`. Sync the app manually — its `syncPolicy` has no
   `automated` block on purpose.
2. Capture the pod before the restart:

   ```bash
   kubectl -n longhorn-zombie-test get pod -l app=longhorn-zombie-test \
     -o custom-columns=NAME:.metadata.name,UID:.metadata.uid,NODE:.spec.nodeName
   ```

3. Restart k3s on `ks5-cp-3` (`sudo systemctl restart k3s`). This command is
   executed ONLY by the operator, never by an agent session.
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
7. Cleanup: a follow-up PR removes the Application from the root
   `kustomization.yaml` and ArgoCD prunes the test namespace contents.
