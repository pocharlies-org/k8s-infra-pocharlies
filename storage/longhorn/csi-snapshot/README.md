# CSI snapshot controller

Longhorn 1.11.2 deploys `csi-snapshotter:v8.5.0-20260428`. Longhorn's
documented requirement is to run snapshot CRDs and the common snapshot
controller from the matching external-snapshotter release.

This overlay pins:

- upstream external-snapshotter v8.5.0 commit
  `5aab051d1af135e2c852f6fb7fc27fa709d877bf`;
- snapshot-controller multi-architecture digest
  `sha256:74ca61ab13e978f03cf0f336a607281d15f04cda0a38a881306365473b28a3d8`.

The upstream v8.5.0 Deployment manifest still names the v8.4.0 image. The
Kustomize image transform intentionally replaces it with the released v8.5.0
digest. The overlay also preserves the live `app=snapshot-controller` selector
because Deployment selectors are immutable.

## Preflight

```bash
test "$(kubectl get volumesnapshots.snapshot.storage.k8s.io -A -o json | jq '.items | length')" -eq 0
test "$(kubectl get volumesnapshotcontents.snapshot.storage.k8s.io -o json | jq '.items | length')" -eq 0
kubectl kustomize storage/longhorn/csi-snapshot >/dev/null
kubectl diff -k storage/longhorn/csi-snapshot
```

## Verify

```bash
kubectl -n kube-system rollout status deploy/snapshot-controller --timeout=5m
kubectl -n kube-system get deploy snapshot-controller \
  -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
kubectl api-resources | grep -E 'volumesnapshots|volumegroupsnapshots'
```

Create a disposable Longhorn PVC and a `VolumeSnapshot` using
`longhorn-snapshot`; require `readyToUse=true`, restore it to a new PVC, compare
data, and then delete the entire test namespace.

## Rollback

If the v8.5.0 controller fails before the smoke test creates production
snapshots, restore the previous controller image without downgrading CRDs:

```bash
kubectl apply -f storage/longhorn/csi-snapshot/rollback-snapshot-controller-v6.3.1.yaml
kubectl -n kube-system rollout status deploy/snapshot-controller --timeout=5m
```

Stop and investigate. Do not delete CRDs or remove finalizers to force cleanup.
