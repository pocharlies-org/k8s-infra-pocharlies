# OpenClaw Sauvage LAN Trusted-Proxy Cutover

This runbook is the final architecture for `https://openclaw.lan.e-dani.com`:
Traefik-LAN authenticates the browser-side route and OpenClaw accepts only
trusted-proxy headers from the cluster, instead of relying on `auth none` behind
a host loopback proxy.

Current production state after the 2026-07-01 guard fix:

- `openclaw-gateway.service` runs on `sauvage` as user `ubuntu`.
- The gateway listens on `127.0.0.1:18789` with `--bind loopback --auth none`.
- `openclaw-lan-loopback-proxy.service` publishes `100.109.183.9:18789`.
- The proxy is guarded by `ExecStartPre` and reinstalled from
  `~/.openclaw/managed/openclaw-loopback-proxy.mjs` if drift is detected.
- `openclaw-lan-websocket-healthcheck.timer` validates
  `wss://openclaw.lan.e-dani.com/` and expects `connect.challenge`.
- GitOps already injects stable trusted-proxy headers through middleware
  `traefik-lan/openclaw-sauvage-lan-identity`.

## Gate

Do this only in a low-traffic window. It restarts the gateway and changes the
auth contract. Before mutating:

```bash
ssh ubuntu@sauvage.taile0ad27.ts.net '
  set -euo pipefail
  openclaw status --json >/tmp/openclaw-status-before-trusted-proxy.json
  systemctl --user is-active openclaw-gateway.service openclaw-lan-loopback-proxy.service
  systemctl --user is-active openclaw-lan-websocket-healthcheck.timer
'

kubectl -n traefik-lan get middleware openclaw-sauvage-lan-identity -o yaml
kubectl -n argocd get application k8s-infra -o jsonpath="{.status.sync.status}{\" \"}{.status.health.status}{\"\\n\"}"
```

Required before continuing:

- Argo app `k8s-infra` is `Synced Healthy`.
- Middleware `openclaw-sauvage-lan-identity` exists.
- No long-running `openclaw agent` turn is in progress.
- You have a backup path printed before changing config.

## Cutover

```bash
ssh ubuntu@sauvage.taile0ad27.ts.net '
  set -euo pipefail
  STAMP=$(date -u +%Y%m%dT%H%M%SZ)
  BK="$HOME/.openclaw/backups/trusted-proxy-cutover-$STAMP"
  mkdir -p "$BK"

  cp -a "$HOME/.openclaw/openclaw.json" "$BK/openclaw.json.before"
  cp -a "$HOME/.config/systemd/user/openclaw-gateway.service.d" "$BK/openclaw-gateway.service.d.before"
  systemctl --user cat openclaw-gateway.service > "$BK/openclaw-gateway.unit.before"
  systemctl --user cat openclaw-lan-loopback-proxy.service > "$BK/openclaw-lan-loopback-proxy.unit.before"

  python3 - <<'"'"'PY'"'"'
import json, os
path = os.path.expanduser("~/.openclaw/openclaw.json")
with open(path) as fh:
    cfg = json.load(fh)
gateway = cfg.setdefault("gateway", {})
gateway["bind"] = "tailnet"
gateway["auth"] = {
    "mode": "trusted-proxy",
    "trustedProxy": {
        "userHeader": "x-forwarded-user",
        "requiredHeaders": ["x-forwarded-proto", "x-forwarded-host"],
        "allowUsers": ["openclaw-sauvage-lan"],
    },
}
gateway["trustedProxies"] = ["10.42.0.0/16"]
control = gateway.setdefault("controlUi", {})
origins = control.setdefault("allowedOrigins", [])
if "https://openclaw.lan.e-dani.com" not in origins:
    origins.append("https://openclaw.lan.e-dani.com")
tmp = path + ".trusted-proxy.tmp"
with open(tmp, "w") as fh:
    json.dump(cfg, fh, indent=2)
    fh.write("\\n")
os.replace(tmp, path)
PY

  mkdir -p "$HOME/.config/systemd/user/openclaw-gateway.service.d"
  cat > "$HOME/.config/systemd/user/openclaw-gateway.service.d/70-trusted-proxy-lan.conf" <<'"'"'EOF'"'"'
[Service]
ExecStart=
ExecStart=/usr/bin/node /home/ubuntu/.local/lib/node_modules/openclaw/dist/index.js gateway --port 18789 --bind tailnet --auth trusted-proxy
EOF

  systemctl --user disable --now openclaw-lan-loopback-proxy.service
  systemctl --user daemon-reload
  systemctl --user restart openclaw-gateway.service
  sleep 5
  systemctl --user is-active openclaw-gateway.service
  echo "BACKUP=$BK"
'
```

## Validation

```bash
curl -k -sS -o /tmp/openclaw-lan.html \
  -w "http_code=%{http_code} time_total=%{time_total}\\n" \
  --connect-timeout 5 --max-time 10 \
  https://openclaw.lan.e-dani.com/

python3 - <<'"'"'PY'"'"'
import asyncio, websockets
async def main():
    async with websockets.connect(
        "wss://openclaw.lan.e-dani.com/",
        origin="https://openclaw.lan.e-dani.com",
        open_timeout=8,
        close_timeout=1,
    ) as ws:
        msg = await asyncio.wait_for(ws.recv(), timeout=2)
        assert "connect.challenge" in msg, msg
        print("trusted_proxy_wss_ok=true")
asyncio.run(main())
PY

ssh ubuntu@sauvage.taile0ad27.ts.net '
  set -euo pipefail
  openclaw gateway status --json | head -c 4000
  systemctl --user is-active openclaw-gateway.service
'
```

## Rollback

Use the printed `BACKUP` path from the cutover.

```bash
ssh ubuntu@sauvage.taile0ad27.ts.net '
  set -euo pipefail
  BK="<paste-backup-path>"
  cp -a "$BK/openclaw.json.before" "$HOME/.openclaw/openclaw.json"
  rm -f "$HOME/.config/systemd/user/openclaw-gateway.service.d/70-trusted-proxy-lan.conf"
  systemctl --user daemon-reload
  systemctl --user restart openclaw-gateway.service
  systemctl --user enable --now openclaw-lan-loopback-proxy.service
  systemctl --user start openclaw-lan-websocket-healthcheck.service
'
```

Post-rollback validation must again show `wss://openclaw.lan.e-dani.com/`
receiving `connect.challenge`.
