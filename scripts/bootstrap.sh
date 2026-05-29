#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXECUTE=0
PHASE="${1:-plan}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON=python3
fi

if [[ "${2:-}" == "--execute" ]]; then
  EXECUTE=1
fi

run() {
  printf '+ %s\n' "$*"
  if [[ "$EXECUTE" == "1" ]]; then
    "$@"
  fi
}

require_env_name() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required env var: $name" >&2
    exit 1
  fi
}

case "$PHASE" in
  plan)
    run "$ROOT/scripts/preflight.sh"
    run "$ROOT/scripts/with_ovh_env.sh" -- "$PYTHON" "$ROOT/scripts/ovh_install.py" catalog \
      --offer-name KS-5-A \
      --require "Intel Xeon E-2274G" \
      --require "SSD NVMe" \
      --require "Soft RAID" \
      --reject HDD \
      --reject SATA
    run bash -lc "cd '$ROOT/terraform/ovh' && (tofu init && tofu plan || terraform init && terraform plan)"
    ;;
  install-ubuntu)
    require_env_name CONFIRM_OVH_REINSTALL
    if [[ "$CONFIRM_OVH_REINSTALL" != "install-ubuntu-24.04" ]]; then
      echo "Set CONFIRM_OVH_REINSTALL=install-ubuntu-24.04" >&2
      exit 1
    fi
    if [[ "$#" -lt 2 ]]; then
      echo "Usage: scripts/bootstrap.sh install-ubuntu --execute --service-name <server> [--service-name <server> ...]" >&2
      exit 1
    fi
    shift
    [[ "${1:-}" == "--execute" ]] && shift
    run "$ROOT/scripts/with_ovh_env.sh" -- "$PYTHON" "$ROOT/scripts/ovh_install.py" install-ubuntu "$@" --fallback-no-raid
    ;;
  ansible)
    run bash -lc "cd '$ROOT/ansible' && ansible-galaxy collection install -r requirements.yml"
    run bash -lc "cd '$ROOT/ansible' && ansible-playbook -i inventory/generated/ks5.ini playbooks/bootstrap-ks5.yml"
    ;;
  dns)
    require_env_name PUBLIC_EDGE_TARGETS
    run "$PYTHON" "$ROOT/scripts/cloudflare_backup.py" backup-json --output "$ROOT/docs/dns-backups/pre-ks5.json"
    run "$PYTHON" "$ROOT/scripts/cloudflare_backup.py" backup-bind --output "$ROOT/docs/dns-backups/pre-ks5.bind"
    run "$PYTHON" "$ROOT/scripts/update_external_dns_targets.py" --repo-root "$ROOT" --targets "$PUBLIC_EDGE_TARGETS" --write
    ;;
  verify)
    run "$ROOT/scripts/verify.sh" --all
    ;;
  *)
    echo "Unknown phase: $PHASE" >&2
    echo "Phases: plan, install-ubuntu, ansible, dns, verify" >&2
    exit 1
    ;;
esac
