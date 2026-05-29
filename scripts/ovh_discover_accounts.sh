#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
SECRETS="${OVH_ACCOUNT_SECRETS:-ovh-claude-eu ovh-ca}"

for secret_name in $SECRETS; do
  echo "== $secret_name =="
  "$ROOT/scripts/with_ovh_env.sh" --secret-name "$secret_name" -- \
    "$PYTHON" "$ROOT/scripts/ovh_install.py" discover
done
