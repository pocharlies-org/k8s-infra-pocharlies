#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-/home/dibanez/k8s/claude-code-ks5-handoff.tar.gz}"

cd "$ROOT"

tar \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='**/__pycache__' \
  --exclude='terraform/ovh/.terraform' \
  --exclude='terraform/ovh/terraform.tfvars' \
  --exclude='ansible/inventory/generated' \
  --exclude='docs/dns-backups' \
  --exclude='*.tfstate' \
  --exclude='*.tfplan' \
  --exclude='*.secret' \
  --exclude='*.key' \
  -czf "$OUTPUT" \
  README.md \
  .env.example \
  ansible.cfg \
  requirements.txt \
  docs/claude-code-ks5-handoff.md \
  docs/claude-code-ks5-file-manifest.txt \
  docs/runbook.md \
  docs/checklist.md \
  docs/architecture.md \
  docs/disaster-recovery.md \
  docs/dns-backup.md \
  ansible \
  kubernetes \
  networking/traefik-edge \
  networking/external-dns \
  scripts \
  terraform/ovh \
  terraform/cloudflare

chmod 600 "$OUTPUT"
printf 'written=%s\n' "$OUTPUT"
