#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:---all}"

check_kubectl() {
  kubectl get --raw /readyz?verbose
  kubectl get nodes -o wide
  kubectl get nodes -o json | jq -e '
    [.items[] | select(.status.conditions[]? | .type == "Ready" and .status == "True")] | length >= 1
  ' >/dev/null
}

check_etcd() {
  local expected="${EXPECTED_ETCD_COUNT:-3}"
  kubectl get nodes -l node-role.kubernetes.io/etcd --no-headers | awk -v expected="$expected" '
    END { if (NR < expected) exit 1 }
  '
}

check_ks5() {
  local expected="${EXPECTED_KS5_COUNT:-3}"
  kubectl get nodes -l node-pool=ks5-nvme --no-headers | awk -v expected="$expected" '
    END { if (NR < expected) exit 1 }
  '
}

check_argocd() {
  kubectl -n argocd get applications.argoproj.io -o json | jq -e '
    [.items[] | select(.status.health.status != "Healthy" or .status.sync.status != "Synced")] | length == 0
  '
}

check_traefik() {
  kubectl -n traefik-edge get ds traefik-edge -o json | jq -e '
    .status.numberReady >= 4 and .status.desiredNumberScheduled >= 4
  '
}

check_dns() {
  if [[ -z "${DOMAIN:-}" ]]; then
    echo "DOMAIN unset; skipping DNS lookup" >&2
    return 0
  fi
  dig +short "$DOMAIN" A
}

check_edge_ips() {
  if [[ -z "${PUBLIC_EDGE_TARGETS:-}" || -z "${DOMAIN:-}" ]]; then
    echo "PUBLIC_EDGE_TARGETS or DOMAIN unset; skipping edge curl checks" >&2
    return 0
  fi
  IFS=',' read -r -a ips <<<"$PUBLIC_EDGE_TARGETS"
  for ip in "${ips[@]}"; do
    ip="${ip//[[:space:]]/}"
    [[ -n "$ip" ]] || continue
    curl -fsS --resolve "${DOMAIN}:443:${ip}" "https://${DOMAIN}/" >/dev/null
  done
}

check_tailscale() {
  command -v tailscale >/dev/null || return 0
  tailscale status
}

case "$MODE" in
  --all)
    check_kubectl
    check_ks5
    check_etcd
    check_argocd
    check_traefik
    check_dns
    check_edge_ips
    check_tailscale
    ;;
  --pre)
    EXPECTED_ETCD_COUNT="${EXPECTED_ETCD_COUNT:-1}" check_kubectl
    EXPECTED_ETCD_COUNT="${EXPECTED_ETCD_COUNT:-1}" check_etcd
    check_dns
    check_tailscale
    ;;
  --k8s) check_kubectl ;;
  --etcd) check_etcd ;;
  --ks5) check_ks5 ;;
  --argocd) check_argocd ;;
  --traefik) check_traefik ;;
  --dns) check_dns ;;
  --edge) check_edge_ips ;;
  *)
    echo "Usage: scripts/verify.sh [--all|--pre|--k8s|--etcd|--ks5|--argocd|--traefik|--dns|--edge]" >&2
    exit 1
    ;;
esac

echo "Verify OK: $MODE"
