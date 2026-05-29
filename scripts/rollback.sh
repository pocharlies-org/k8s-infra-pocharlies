#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-}"

case "$ACTION" in
  dns)
    backup="${2:-$ROOT/docs/dns-backups/pre-ks5.json}"
    if [[ "${CONFIRM_CLOUDFLARE_RESTORE:-}" != "restore-dns-from-backup" ]]; then
      echo "Set CONFIRM_CLOUDFLARE_RESTORE=restore-dns-from-backup" >&2
      exit 1
    fi
    python3 "$ROOT/scripts/cloudflare_backup.py" restore-json --input "$backup"
    ;;
  traefik)
    if [[ "${CONFIRM_TRAEFIK_ROLLBACK:-}" != "rollback-traefik-edge-to-sauvage" ]]; then
      echo "Set CONFIRM_TRAEFIK_ROLLBACK=rollback-traefik-edge-to-sauvage" >&2
      exit 1
    fi
    git -C "$ROOT" checkout HEAD -- networking/traefik-edge/values.yaml
    kubectl -n argocd patch application traefik-edge --type merge -p '{"operation":{"sync":{"revision":"HEAD","syncOptions":["ServerSideApply=true"]}}}'
    ;;
  remove-node)
    node="${2:-}"
    if [[ -z "$node" ]]; then
      echo "Usage: scripts/rollback.sh remove-node <node-name>" >&2
      exit 1
    fi
    if [[ "${CONFIRM_NODE_REMOVE:-}" != "remove-k8s-node" ]]; then
      echo "Set CONFIRM_NODE_REMOVE=remove-k8s-node" >&2
      exit 1
    fi
    kubectl drain "$node" --ignore-daemonsets --delete-emptydir-data --timeout=300s || true
    kubectl delete node "$node"
    ;;
  tailscale)
    node="${2:-}"
    if [[ -z "$node" ]]; then
      echo "Usage: scripts/rollback.sh tailscale <tailscale-hostname>" >&2
      exit 1
    fi
    if [[ "${CONFIRM_TAILSCALE_REMOVE:-}" != "remove-tailscale-node" ]]; then
      echo "Set CONFIRM_TAILSCALE_REMOVE=remove-tailscale-node" >&2
      exit 1
    fi
    ssh "$node" sudo tailscale logout
    ;;
  *)
    echo "Usage: scripts/rollback.sh {dns [backup.json]|traefik|remove-node <node>|tailscale <host>}" >&2
    exit 1
    ;;
esac
