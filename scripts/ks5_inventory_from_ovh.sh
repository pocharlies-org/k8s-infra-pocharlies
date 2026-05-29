#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
OUTPUT="${1:-$ROOT/ansible/inventory/generated/ks5.ini}"
SECRETS="${OVH_ACCOUNT_SECRETS:-ovh-claude-eu ovh-ca}"
REQUIRED_DATACENTER_PREFIX="${REQUIRED_OVH_DATACENTER_PREFIX:-rbx}"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

for secret_name in $SECRETS; do
  OVH_ACCOUNT_SECRET="$secret_name" "$ROOT/scripts/with_ovh_env.sh" --secret-name "$secret_name" -- "$PYTHON" - <<'PY' >>"$tmp"
import json
import os

import ovh

c = ovh.Client(
    endpoint=os.environ["OVH_ENDPOINT"],
    application_key=os.environ["OVH_APPLICATION_KEY"],
    application_secret=os.environ["OVH_APPLICATION_SECRET"],
    consumer_key=os.environ["OVH_CONSUMER_KEY"],
)

for service_name in c.get("/dedicated/server"):
    info = c.get(f"/dedicated/server/{service_name}")
    commercial = info.get("commercialRange") or ""
    if "KS-5-A" not in commercial or "E-2274G" not in commercial:
        continue
    print(json.dumps({
        "service_name": service_name,
        "public_ip": info.get("ip"),
        "datacenter": info.get("datacenter"),
        "commercial_range": commercial,
        "state": info.get("state"),
        "ovh_secret": os.environ.get("OVH_ACCOUNT_SECRET", ""),
    }, sort_keys=True))
PY
done

mkdir -p "$(dirname "$OUTPUT")"
{
  echo "[ks5_control_plane]"
  sort -u "$tmp" | jq -s -r '
    sort_by(.service_name) |
    to_entries[] |
    "ks5-cp-\(.key + 1) ansible_host=\(.value.public_ip) public_ip=\(.value.public_ip) ovh_service_name=\(.value.service_name) ovh_datacenter=\(.value.datacenter) ovh_secret=\(.value.ovh_secret) commercial_range=\"\(.value.commercial_range)\""
  '
  echo
  echo "[existing_workers]"
  echo "ubuntu ansible_host=${CURRENT_HOME_NODE_IP:-100.83.56.98} node_role=dev-fast"
  echo "sauvage ansible_host=${CURRENT_SAUVAGE_TAILSCALE_IP:-100.109.183.9} node_role=heavy-worker"
  echo
  echo "[ks5_control_plane:vars]"
  echo "ansible_user=ubuntu"
  echo
  echo "[existing_workers:vars]"
  echo "ansible_user=ubuntu"
} >"$OUTPUT"

count="$(awk '/^ks5-cp-/ { n++ } END { print n+0 }' "$OUTPUT")"
echo "written=$OUTPUT ks5_count=$count"
if ! jq -e --arg dc "$REQUIRED_DATACENTER_PREFIX" -s 'all(.[]; ((.datacenter // "") | startswith($dc)))' "$tmp" >/dev/null; then
  echo "WARN: at least one KS-5-A is outside required datacenter prefix '$REQUIRED_DATACENTER_PREFIX'" >&2
  exit 4
fi
if [[ "$count" -lt 3 ]]; then
  echo "WARN: expected 3 KS-5-A servers; OVH currently exposes $count" >&2
  exit 3
fi
