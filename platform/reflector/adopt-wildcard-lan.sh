#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# Metadata-only server-side apply preserves the existing TLS data while adding
# the direct-reflection annotation. Argo CD cannot apply kubernetes.io/tls
# resources without key data, so this one-time adoption stays explicit.
kubectl apply \
  --server-side \
  --field-manager=reflector-adoption \
  -f "${repo_root}/platform/reflector/wildcard-lan-mirrors.yaml"
