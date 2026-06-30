#!/usr/bin/env bash
set -euo pipefail

CHECK="${OPENCLAW_LAN_HEALTHCHECK_SCRIPT:-$HOME/.openclaw/bin/openclaw-lan-websocket-healthcheck.mjs}"
RESTART_ON_FAIL="${OPENCLAW_LAN_HEALTHCHECK_RESTART_PROXY_ON_FAIL:-1}"

log() {
  printf '[%s] %s\n' "$(date -Iseconds)" "$*" >&2
}

if node "$CHECK"; then
  exit 0
fi

if [[ "$RESTART_ON_FAIL" != "1" ]]; then
  exit 1
fi

log "WebSocket healthcheck failed; restarting openclaw-lan-loopback-proxy.service once"
systemctl --user restart openclaw-lan-loopback-proxy.service
sleep 2
node "$CHECK"
