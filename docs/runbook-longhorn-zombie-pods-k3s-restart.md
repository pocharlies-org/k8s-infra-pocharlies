# Longhorn zombie pods after a k3s restart ("no Pending workload pods")

Tracked in INFRA-41. Diagnosis is closed (INFRA-73). The fix is published in
Longhorn v1.13.0 and the cluster is being bumped to it through INFRA-122; until
that bump is deployed and verified, the operational answer below (recreate the
pod) is what clears a stuck mount.

## CONGELACION (decision VP 18-09-2026)

Prohibido reiniciar k3s/kubelet en `ks5-cp-1`, `ks5-cp-2` y `ks5-cp-3` hasta
que el fix de longhorn/longhorn#13723 esté aplicado por GitOps (bump del chart
longhorn que lo incluya) y verificado con el pod de prueba: mismo pod y UID
tras el reinicio, sin bucle de `MountVolume.SetUp`. Esta congelación prevalece
sobre el procedimiento de reproducción de más abajo.

Única excepción: un reinicio inevitable (p. ej. un parche de seguridad), en
ventana acordada, con la recuperación preparada (este runbook) y aviso previo
al VP.

La congelación se levanta solo con el criterio 3 de la épica medido
(verificación con el pod de prueba). Referencias: épica INFRA-122, adjunto
`nota-cto-congelacion-ks5.md`, etiqueta `parked-hasta-2026-09-23`.

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
| v1.11.2 | this cluster's current chart — no fix |
| v1.11.3 | published — no fix (backport did not land in 1.11.x) |
| v1.12.0, v1.12.1 | published (latest of the 1.12 line) — no fix |
| v1.12.2 | not published; the backport (longhorn-manager#5225) is merged to `v1.12.x` — only the release is missing |
| **v1.13.0** | **contains the fix** |

The GitOps surface is `infra/longhorn.yaml` (multi-source Application, chart
pinned there) plus `infra/longhorn/values.yaml` in `k8s-gitops-pocharlies`,
branch `deploy/prod`. There is **no configuration workaround** — until v1.13.0
is deployed, recovery is operational (recreate the pod).

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

If the symptom reappears on a node before v1.13.0 is running (or a k3s restart
happens during the upgrade window), use the recovery below; it is unchanged.

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
