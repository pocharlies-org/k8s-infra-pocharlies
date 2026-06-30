#!/usr/bin/env bash
set -euo pipefail

SOURCE="${OPENCLAW_PROXY_MANAGED_SOURCE:-$HOME/.openclaw/managed/openclaw-loopback-proxy.mjs}"
TARGET="${OPENCLAW_PROXY_TARGET:-$HOME/.openclaw/bin/openclaw-loopback-proxy.mjs}"
EXPECTED_SHA="${OPENCLAW_PROXY_EXPECTED_SHA:-}"
BACKUP_DIR="${OPENCLAW_PROXY_BACKUP_DIR:-$HOME/.openclaw/backups}"

log() {
  printf '[%s] %s\n' "$(date -Iseconds)" "$*" >&2
}

sha256() {
  sha256sum "$1" | awk '{print $1}'
}

if [[ ! -f "$SOURCE" ]]; then
  log "managed proxy source missing: $SOURCE"
  exit 78
fi

if ! command -v node >/dev/null 2>&1; then
  log "node is required to validate the OpenClaw LAN proxy"
  exit 78
fi

node --check "$SOURCE" >/dev/null

source_sha="$(sha256 "$SOURCE")"
if [[ -n "$EXPECTED_SHA" && "$source_sha" != "$EXPECTED_SHA" ]]; then
  log "managed proxy sha mismatch: got=$source_sha expected=$EXPECTED_SHA"
  exit 78
fi

if [[ -f "$TARGET" && "$(sha256 "$TARGET")" == "$source_sha" ]]; then
  log "OpenClaw LAN proxy already enforced: $source_sha"
  exit 0
fi

mkdir -p "$BACKUP_DIR" "$(dirname "$TARGET")"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -f "$TARGET" ]]; then
  backup="$BACKUP_DIR/openclaw-loopback-proxy-${ts}.mjs"
  cp -p "$TARGET" "$backup"
  chmod 600 "$backup"
  log "backed up previous proxy: $backup"
fi

install -m 700 "$SOURCE" "$TARGET"
log "installed managed OpenClaw LAN proxy: $source_sha"
