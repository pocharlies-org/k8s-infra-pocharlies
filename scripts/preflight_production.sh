#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXECUTE=0
if [[ "${1:-}" == "--execute" ]]; then
  EXECUTE=1
fi

ts="$(date -u +%Y%m%dT%H%M%SZ)"

run() {
  printf '+ %s\n' "$*"
  if [[ "$EXECUTE" == "1" ]]; then
    "$@"
  fi
}

run kubectl get --raw /readyz?verbose
run kubectl get nodes -o wide
run kubectl -n argocd get applications.argoproj.io

if [[ "$EXECUTE" == "1" ]]; then
  ssh ubuntu@100.83.56.98 "sudo k3s etcd-snapshot save --name pre-ks5-${ts}"
else
  echo "+ ssh ubuntu@100.83.56.98 'sudo k3s etcd-snapshot save --name pre-ks5-${ts}'"
fi

run kubectl -n databases apply -f - <<YAML
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: postgres-shared-pre-ks5-${ts}
spec:
  cluster:
    name: postgres-shared
YAML

run kubectl -n velero apply -f - <<YAML
apiVersion: velero.io/v1
kind: Backup
metadata:
  name: pre-ks5-${ts}
spec:
  includedNamespaces:
    - argocd
    - databases
    - longhorn-system
    - skirmshop
    - skirmshop-brain-prod
    - skirmshop-brain-stg
    - traefik-edge
    - external-dns
    - cert-manager
YAML

if kubectl -n databases get pod shared-rabbitmq-0 >/dev/null 2>&1; then
  if [[ "$EXECUTE" == "1" ]]; then
    mkdir -p "$ROOT/docs/runtime-backups"
    kubectl -n databases exec shared-rabbitmq-0 -- rabbitmqadmin export - \
      > "$ROOT/docs/runtime-backups/rabbitmq-definitions-${ts}.json"
  else
    echo "+ kubectl -n databases exec shared-rabbitmq-0 -- rabbitmqadmin export - > docs/runtime-backups/rabbitmq-definitions-${ts}.json"
  fi
fi

echo "preflight_production mode=$([[ "$EXECUTE" == "1" ]] && echo execute || echo dry-run)"
