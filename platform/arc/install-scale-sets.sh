#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART="oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set"
VERSION="0.14.1"
NAMESPACE="arc-runners"

kubectl get namespace "$NAMESPACE" >/dev/null
kubectl get secret arc-github-app -n "$NAMESPACE" >/dev/null

# Single shared org-scope runner for all of pocharlies-org.
helm upgrade --install arc-k8s "$CHART" \
  --version "$VERSION" \
  --namespace "$NAMESPACE" \
  -f "$ROOT/platform/arc/scale-set-k8s.yaml"
