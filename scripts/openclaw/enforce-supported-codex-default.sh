#!/usr/bin/env bash
set -euo pipefail

CFG="${OPENCLAW_CFG:-$HOME/.openclaw/openclaw.json}"
BACKUP_DIR="${OPENCLAW_BACKUP_DIR:-$HOME/.openclaw/backups}"
PRIMARY="${OPENCLAW_SUPPORTED_PRIMARY:-openai/gpt-5.5}"
FALLBACK="${OPENCLAW_SUPPORTED_FALLBACK:-litellm/tooling}"
BAD_PRIMARY="openai/gpt-5.3-codex"
BAD_SHORT="gpt-5.3-codex"

MANAGED_AGENT_IDS='[
  "main",
  "skirmshop",
  "synapse-skirmshop-local",
  "hogar",
  "social-media",
  "jarvis",
  "synapse",
  "synapse-expenses",
  "synapse-ops-analyst",
  "synapse-unsubscribe",
  "synapse-deep-analysis",
  "synapse-web-operator"
]'

log() {
  printf '[%s] %s\n' "$(date -Iseconds)" "$*" >&2
}

if ! command -v jq >/dev/null 2>&1; then
  log "jq is required to enforce the OpenClaw model policy"
  exit 78
fi

if [[ ! -f "$CFG" ]]; then
  log "OpenClaw config not found: $CFG"
  exit 78
fi

tmp="$(mktemp "${CFG}.supported-codex.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

jq \
  --arg primary "$PRIMARY" \
  --arg fallback "$FALLBACK" \
  --arg badPrimary "$BAD_PRIMARY" \
  --arg badShort "$BAD_SHORT" \
  --argjson managed "$MANAGED_AGENT_IDS" '
  .agents.defaults.model.primary = $primary
  | .agents.defaults.model.fallbacks = [$fallback]
  | if ((.agents.defaults.models? // null) | type) == "object" then
      del(.agents.defaults.models[$badPrimary])
    else
      .
    end
  | if ((.agents.list? // null) | type) == "array" then
      .agents.list |= map(
        . as $agent
        | if ((.models? // null) | type) == "object" then
            del(.models[$badPrimary])
          else
            .
          end
        | if ($managed | index($agent.id)) then
            .model.primary = $primary
            | .model.fallbacks = [$fallback]
          else
            .
          end
      )
    else
      .
    end
  | if ((.models.providers.openai.models? // null) | type) == "array" then
      .models.providers.openai.models |= map(
        select((.id? // .name? // .) != $badShort and (.id? // .name? // .) != $badPrimary)
      )
    else
      .
    end
  ' "$CFG" > "$tmp"

jq empty "$tmp" >/dev/null

bad_refs="$(
  jq \
    --arg badPrimary "$BAD_PRIMARY" \
    --arg badShort "$BAD_SHORT" \
    '[paths(scalars) as $p | select(getpath($p) == $badPrimary or getpath($p) == $badShort) | $p] | length' \
    "$tmp"
)"

if [[ "$bad_refs" != "0" ]]; then
  log "refusing to install config: $bad_refs unsupported model reference(s) remain"
  exit 78
fi

if cmp -s "$CFG" "$tmp"; then
  log "OpenClaw supported Codex default already enforced: $PRIMARY"
  exit 0
fi

mkdir -p "$BACKUP_DIR"
ts="$(date -u +%Y%m%dT%H%M%SZ)"
backup="${BACKUP_DIR}/openclaw-json-supported-codex-default-${ts}.json"
cp -p "$CFG" "$backup"
chmod 600 "$backup"
install -m 600 "$tmp" "$CFG"

log "enforced OpenClaw supported Codex default: $PRIMARY; backup: $backup"
