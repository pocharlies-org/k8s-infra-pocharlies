#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_RG_DIR="/usr/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/path"
if [[ -x "$CODEX_RG_DIR/rg" ]]; then
  export PATH="$CODEX_RG_DIR:$PATH"
fi
RUNTIME_ENV="${RUNTIME_ENV:-/home/dibanez/k8s/ks5-ha.runtime.env}"
LOG_FILE="${AUTOPILOT_LOG:-/home/dibanez/k8s/ks5-ha-autopilot.log}"
LOCK_FILE="${AUTOPILOT_LOCK:-/tmp/ks5-ha-autopilot.lock}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
INVENTORY="$ROOT/ansible/inventory/generated/ks5.ini"
WAIT_SECONDS="${OVH_WAIT_SECONDS:-28800}"
WAIT_INTERVAL="${OVH_WAIT_INTERVAL:-300}"

mkdir -p "$(dirname "$LOG_FILE")" "$ROOT/ansible/inventory/generated" "$ROOT/docs/dns-backups"
touch "$LOG_FILE"
chmod 600 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

if [[ ! -r "$RUNTIME_ENV" ]]; then
  echo "Runtime env not found: $RUNTIME_ENV" >&2
  exit 2
fi

source "$RUNTIME_ENV"

if [[ ! -x "$PYTHON" ]]; then
  PYTHON=python3
fi

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "Missing required env var: $name" >&2
    exit 2
  fi
}

log() {
  printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

# Mint a fresh, tagged Tailscale auth key from the (non-expiring) OAuth client
# when its credentials are present. This removes the 90-day auth-key refresh:
# the static TAILSCALE_AUTH_KEY becomes a fallback only. Tagged nodes never expire.
mint_authkey_if_oauth() {
  local id_file="${TS_OAUTH_ID_FILE:-/home/dibanez/k8s/.ts-oauth-id}"
  local sec_file="${TS_OAUTH_SECRET_FILE:-/home/dibanez/k8s/.ts-oauth-secret}"
  [[ -r "$id_file" && -r "$sec_file" ]] || return 0
  log "OAuth client creds present; minting a fresh tagged Tailscale auth key."
  local k
  if k="$(TS_OAUTH_ID_FILE="$id_file" TS_OAUTH_SECRET_FILE="$sec_file" \
        "$PYTHON" "$ROOT/scripts/ts_mint_authkey.py" 2> >(tee -a "$LOG_FILE" >&2))"; then
    export TAILSCALE_AUTH_KEY="$k"
    log "Using freshly minted OAuth auth key (overrides static TAILSCALE_AUTH_KEY)."
  else
    log "WARN: OAuth mint failed; falling back to static TAILSCALE_AUTH_KEY if set."
  fi
}

run() {
  log "+ $*"
  "$@"
}

extract_inventory_value() {
  local host="$1"
  local key="$2"
  awk -v host="$host" -v key="$key" '
    $1 == host {
      for (i = 1; i <= NF; i++) {
        if ($i ~ "^" key "=") {
          sub("^" key "=", "", $i)
          gsub(/^"|"$/, "", $i)
          print $i
          exit
        }
      }
    }
  ' "$INVENTORY"
}

already_ssh_ok() {
  local ip="$1"
  ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "ubuntu@$ip" true >/dev/null 2>&1
}

public_edge_targets() {
  local ips=()
  local host ip
  for host in ks5-cp-1 ks5-cp-2 ks5-cp-3; do
    ip="$(extract_inventory_value "$host" public_ip)"
    [[ -n "$ip" ]] || return 1
    ips+=("$ip")
  done
  ips+=("$CURRENT_SAUVAGE_PUBLIC_IP")
  local IFS=,
  printf '%s' "${ips[*]}"
}

production_pods_on_ubuntu() {
  kubectl get pods -A -o json | jq -r '
    [
      .items[]
      | select(.spec.nodeName == "ubuntu")
      | select(.status.phase != "Succeeded")
      | select(.metadata.namespace as $ns | ["kube-system","longhorn-system","velero"] | index($ns) | not)
    ]
    | length
  '
}

wait_for_inventory() {
  local deadline=$((SECONDS + WAIT_SECONDS))
  while true; do
    if "$ROOT/scripts/ks5_inventory_from_ovh.sh" "$INVENTORY"; then
      log "All 3 KS-5-A servers are visible in OVH."
      return 0
    fi
    if (( SECONDS >= deadline )); then
      log "Timed out waiting for 3 KS-5-A servers in OVH."
      return 3
    fi
    log "OVH still does not expose all 3 KS-5-A servers; sleeping ${WAIT_INTERVAL}s."
    sleep "$WAIT_INTERVAL"
  done
}

wait_for_ssh() {
  local host ip deadline
  for host in ks5-cp-1 ks5-cp-2 ks5-cp-3; do
    ip="$(extract_inventory_value "$host" public_ip)"
    log "Waiting for SSH on $host ($ip)."
    ssh-keygen -R "$ip" >/dev/null 2>&1 || true
    deadline=$((SECONDS + 3600))
    until ssh -o BatchMode=yes -o ConnectTimeout=8 -o StrictHostKeyChecking=accept-new "ubuntu@$ip" true >/dev/null 2>&1; do
      if (( SECONDS >= deadline )); then
        echo "Timed out waiting for SSH on $host ($ip)" >&2
        return 4
      fi
      sleep 20
    done
  done
}

install_ubuntu() {
  require_env CONFIRM_OVH_REINSTALL
  local ovh_secret
  ovh_secret="$(awk '/^ks5-cp-1 / { for (i=1;i<=NF;i++) if ($i ~ /^ovh_secret=/) { sub(/^ovh_secret=/, "", $i); print $i; exit } }' "$INVENTORY")"
  ovh_secret="${ovh_secret:-ovh-claude-eu}"

  local install_targets=() wait_targets=()
  local host service ip
  for host in ks5-cp-1 ks5-cp-2 ks5-cp-3; do
    service="$(extract_inventory_value "$host" ovh_service_name)"
    ip="$(extract_inventory_value "$host" public_ip)"
    if [[ -z "$service" || -z "$ip" ]]; then
      echo "Missing service or public_ip for $host in inventory" >&2
      return 1
    fi
    if already_ssh_ok "$ip"; then
      log "Skipping reinstall for $host ($ip): SSH already responding."
      continue
    fi
    install_targets+=(--service-name "$service" --hostname "$host")
    wait_targets+=(--service-name "$service")
  done

  if (( ${#install_targets[@]} == 0 )); then
    log "All 3 KS-5-A hosts already respond to SSH; skipping install_ubuntu."
    return 0
  fi

  run "$ROOT/scripts/with_ovh_env.sh" --secret-name "$ovh_secret" -- "$PYTHON" "$ROOT/scripts/ovh_install.py" install-ubuntu "${install_targets[@]}" --fallback-no-raid
  run "$ROOT/scripts/with_ovh_env.sh" --secret-name "$ovh_secret" -- "$PYTHON" "$ROOT/scripts/ovh_install.py" wait "${wait_targets[@]}"
}

bootstrap_k3s() {
  run ansible-playbook -i "$INVENTORY" "$ROOT/ansible/playbooks/bootstrap-ks5.yml"
  run env EXPECTED_KS5_COUNT=3 "$ROOT/scripts/verify.sh" --ks5
  run env EXPECTED_ETCD_COUNT=4 "$ROOT/scripts/verify.sh" --etcd
  run "$ROOT/scripts/verify.sh" --k8s
}

apply_traefik_and_dns() {
  if [[ "${ALLOW_TRAEFIK_DNS_CUTOVER:-}" != "ok" ]]; then
    log "Skipping Traefik/DNS cutover; ALLOW_TRAEFIK_DNS_CUTOVER is not ok."
    return 0
  fi

  local targets ts
  targets="$(public_edge_targets)"
  export PUBLIC_EDGE_TARGETS="$targets"
  ts="$(date -u +%Y%m%dT%H%M%SZ)"

  run "$PYTHON" "$ROOT/scripts/cloudflare_backup.py" backup-json --output "$ROOT/docs/dns-backups/pre-traefik-ha-$ts.json"
  run "$PYTHON" "$ROOT/scripts/cloudflare_backup.py" backup-bind --output "$ROOT/docs/dns-backups/pre-traefik-ha-$ts.bind"
  run "$PYTHON" "$ROOT/scripts/update_external_dns_targets.py" --repo-root "$ROOT" --targets "$targets" --write

  run kubectl label node sauvage ingress=true --overwrite
  run helm repo add traefik https://traefik.github.io/charts
  run helm repo update
  run helm upgrade --install traefik-edge traefik/traefik -n traefik-edge -f "$ROOT/networking/traefik-edge/values.yaml"
  run kubectl apply -f "$ROOT/networking/traefik-edge/namespace.yaml"
  run kubectl apply -f "$ROOT/networking/traefik-edge/tls-store.yaml"
  run kubectl apply -f "$ROOT/networking/traefik-edge/wildcard-cert.yaml"
  run kubectl apply -f "$ROOT/networking/traefik-edge/static-edge.yaml"
  run kubectl apply -f "$ROOT/networking/traefik-edge/legacy-public-routes.yaml"
  run kubectl apply -f "$ROOT/networking/traefik-edge/affiliate-public.yaml"
  run kubectl apply -f "$ROOT/networking/traefik-edge/harbor-ingressroute.yaml"
  run kubectl apply -f "$ROOT/networking/traefik-edge/firecrawl-edge-auth.yaml"
  run kubectl apply -k "$ROOT/kubernetes/traefik"
  run kubectl -n traefik-edge rollout status ds/traefik-edge --timeout=10m
}

maybe_demote_x86() {
  local prod_count
  prod_count="$(production_pods_on_ubuntu)"
  if [[ "$prod_count" != "0" && "${ALLOW_PRODUCTION_DISRUPTION:-}" != "ok" ]]; then
    log "Stopping before x86 demotion: $prod_count non-system pods still run on ubuntu and ALLOW_PRODUCTION_DISRUPTION is not ok."
    return 0
  fi

  run ansible-playbook -i "$INVENTORY" "$ROOT/ansible/playbooks/demote-x86-to-worker.yml"
}

main() {
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "Another KS-5 autopilot run is already active." >&2
    exit 5
  fi

  log "KS-5 autopilot started."
  mint_authkey_if_oauth
  require_env TAILSCALE_AUTH_KEY
  require_env SSH_PUBLIC_KEY
  require_env K3S_TOKEN
  require_env CLOUDFLARE_API_TOKEN
  require_env CLOUDFLARE_ZONE_ID

  run "$ROOT/scripts/preflight.sh"
  wait_for_inventory
  install_ubuntu
  wait_for_ssh
  bootstrap_k3s
  apply_traefik_and_dns
  maybe_demote_x86
  log "KS-5 autopilot finished."
}

main "$@"
