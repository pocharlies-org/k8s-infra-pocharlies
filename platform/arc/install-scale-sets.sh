#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART="oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set"
VERSION="0.14.1"
NAMESPACE="arc-runners"

kubectl get namespace "$NAMESPACE" >/dev/null
kubectl get secret arc-github-pat-secret -n "$NAMESPACE" >/dev/null

helm upgrade --install arc-runners-amd64 "$CHART" \
  --version "$VERSION" \
  --namespace "$NAMESPACE" \
  -f "$ROOT/platform/arc/scale-set-amd64.yaml"

for values in "$ROOT"/platform/arc/scale-sets/*.yaml; do
  name="$(basename "$values" .yaml)"
  helm upgrade --install "arc-runners-${name}" "$CHART" \
    --version "$VERSION" \
    --namespace "$NAMESPACE" \
    -f "$values"
done
