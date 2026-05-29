#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="$ROOT/docs/dns-backups"
mkdir -p "$BACKUP_DIR"

required_tools=(python3 kubectl jq curl git ssh ansible ansible-playbook helm)

for tool in "${required_tools[@]}"; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done

if ! command -v terraform >/dev/null && ! command -v tofu >/dev/null; then
  echo "Missing required tool: terraform or tofu" >&2
  exit 1
fi

required_env=(
  CLOUDFLARE_API_TOKEN
  CLOUDFLARE_ZONE_ID
  TAILSCALE_AUTH_KEY
  SSH_PUBLIC_KEY
  DOMAIN
  CURRENT_HOME_NODE_IP
  CURRENT_SAUVAGE_SERVER_NAME
  CURRENT_SAUVAGE_PUBLIC_IP
)

missing=0
if [[ -z "${OVH_APPLICATION_KEY:-}" || -z "${OVH_APPLICATION_SECRET:-}" || -z "${OVH_CONSUMER_KEY:-}" ]]; then
  if ! kubectl -n "${OVH_SECRET_NAMESPACE:-infra-secrets}" get secret "${OVH_SECRET_NAME:-ovh-claude-eu}" >/dev/null 2>&1; then
    echo "Missing OVH API env vars and Kubernetes Secret ${OVH_SECRET_NAMESPACE:-infra-secrets}/${OVH_SECRET_NAME:-ovh-claude-eu}" >&2
    missing=1
  fi
fi
for name in "${required_env[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "Missing env var: $name" >&2
    missing=1
  fi
done
[[ "$missing" == "0" ]] || exit 1

kubectl get --raw /readyz?verbose >/dev/null
kubectl get nodes -o wide
kubectl -n argocd get applications.argoproj.io >/dev/null

if [[ -n "${CLOUDFLARE_API_TOKEN:-}" && -n "${CLOUDFLARE_ZONE_ID:-}" ]]; then
  ts="$(date -u +%Y%m%dT%H%M%SZ)"
  python3 "$ROOT/scripts/cloudflare_backup.py" backup-json --output "$BACKUP_DIR/preflight-$ts.json"
  python3 "$ROOT/scripts/cloudflare_backup.py" backup-bind --output "$BACKUP_DIR/preflight-$ts.bind"
fi

if rg -n -P --hidden --glob '!.git/**' --glob '!docs/**' --glob '!terraform/**/*.md' \
  --glob '!scripts/preflight.sh' --glob '!scripts/with_ovh_env.sh' \
  'OVH_APPLICATION_SECRET=(?!\.\.\.)|OVH_CONSUMER_KEY=(?!\.\.\.)|TAILSCALE_AUTH_KEY=(?!\.\.\.)|CLOUDFLARE_API_TOKEN=(?!\.\.\.)|robot\\$k8s-nodes' "$ROOT"; then
  echo "Potential hardcoded secret detected; refusing preflight." >&2
  exit 1
fi

echo "Preflight OK"
