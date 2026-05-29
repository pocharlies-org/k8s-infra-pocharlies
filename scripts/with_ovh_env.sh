#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${OVH_SECRET_NAMESPACE:-infra-secrets}"
SECRET_NAME="${OVH_SECRET_NAME:-ovh-claude-eu}"

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --secret-name)
      SECRET_NAME="${2:?missing value for --secret-name}"
      shift 2
      ;;
    --namespace)
      NAMESPACE="${2:?missing value for --namespace}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [[ "$#" -eq 0 ]]; then
  echo "Usage: scripts/with_ovh_env.sh [--secret-name ovh-ca|ovh-claude-eu] [--namespace infra-secrets] -- <command> [args...]" >&2
  exit 2
fi

secret_json="$(kubectl -n "$NAMESPACE" get secret "$SECRET_NAME" -o json)"

decode_key() {
  local key="$1"
  printf '%s' "$secret_json" | jq -r --arg key "$key" '.data[$key] | @base64d'
}

export OVH_ENDPOINT="$(decode_key OVH_ENDPOINT)"
export OVH_APPLICATION_KEY="$(decode_key OVH_APPLICATION_KEY)"
export OVH_APPLICATION_SECRET="$(decode_key OVH_APPLICATION_SECRET)"
export OVH_CONSUMER_KEY="$(decode_key OVH_CONSUMER_KEY)"
export OVH_SUBSIDIARY="$(decode_key OVH_SUBSIDIARY)"

unset secret_json
exec "$@"
