# Sauvage OpenClaw supported Codex default

Sauvage runs the Telegram OpenClaw gateway as the `ubuntu` user systemd unit
`openclaw-gateway.service`.

The live OpenClaw config is host-local at:

```text
/home/ubuntu/.openclaw/openclaw.json
```

That file contains secrets and must not be committed.

To keep the Telegram agents on the supported Codex route, the user unit has an
`ExecStartPre` guard:

```text
/home/ubuntu/.config/systemd/user/openclaw-gateway.service.d/05-supported-codex-default.conf
```

It runs:

```text
/home/ubuntu/.openclaw/bin/enforce-supported-codex-default.sh
```

The guard is idempotent. On each gateway start it:

- forces active OpenClaw agents to `openai/gpt-5.5`,
- keeps `litellm-lab` on `litellm/tooling`,
- sets fallback to `litellm/tooling`,
- removes exact `openai/gpt-5.3-codex` / `gpt-5.3-codex` references,
- writes a timestamped backup in `/home/ubuntu/.openclaw/backups` only when it
  changes the config.

Deploy from this repo with:

```bash
scp scripts/openclaw/enforce-supported-codex-default.sh sauvage:/home/ubuntu/.openclaw/bin/enforce-supported-codex-default.sh
scp scripts/openclaw/openclaw-gateway-supported-codex-default.conf sauvage:/home/ubuntu/.config/systemd/user/openclaw-gateway.service.d/05-supported-codex-default.conf
ssh sauvage 'chmod 700 ~/.openclaw/bin/enforce-supported-codex-default.sh && systemctl --user daemon-reload && systemctl --user restart openclaw-gateway.service'
```

Verify without printing secrets:

```bash
ssh sauvage 'openclaw models status --json | jq "{defaultModel, routingMode, runtimeDefaultProfile, oauthUsable}"'
ssh sauvage 'jq "{default:.agents.defaults.model, badRefs:[paths(scalars) as $p | select(getpath($p) == \"openai/gpt-5.3-codex\" or getpath($p) == \"gpt-5.3-codex\") | $p]}" ~/.openclaw/openclaw.json'
ssh sauvage 'systemctl --user status openclaw-gateway.service --no-pager'
```
