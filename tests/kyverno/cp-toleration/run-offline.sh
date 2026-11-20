#!/usr/bin/env bash
# SC-6096: offline check of control-plane-toleration-allowlist (platform/kyverno/policies.yaml)
# with the Kyverno CLI (same version as the cluster, v1.18.x). No cluster needed.
# This is a MUTATE policy: "pass" means the toleration was added (allow-*), "skip" means the
# allowlist conditions did not match and the pod is left untouched (deny-*).
# Each fixture's first line `# user: <username>` is the requester the API server would see.
# usage: ./run-offline.sh [path-to-kyverno-binary]
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
K="${1:-kyverno}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
python3 - "$DIR/../../../platform/kyverno/policies.yaml" "$TMP/policy.yaml" <<'PY'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d]
pol = [d for d in docs if d["metadata"]["name"] == "control-plane-toleration-allowlist"][0]
yaml.safe_dump(pol, open(sys.argv[2], "w"))
PY
bad=0
for f in "$DIR"/allow-*.yaml "$DIR"/deny-*.yaml; do
  name="$(basename "$f" .yaml)"
  user="$(sed -n '1s/^# user: //p' "$f")"
  printf 'apiVersion: cli.kyverno.io/v1alpha1\nkind: UserInfo\nmetadata:\n  name: u\nuserInfo:\n  username: "%s"\n' "$user" > "$TMP/user.yaml"
  summary="$("$K" apply "$TMP/policy.yaml" --resource "$f" --userinfo "$TMP/user.yaml" 2>&1 | grep -E 'pass:.*fail:' | tail -1)"
  passes="$(printf '%s' "$summary" | sed -E 's/.*pass: ([0-9]+).*/\1/')"
  case "$name" in
    allow-*) [ "$passes" = "1" ] && echo "PASS  $name  ($summary)" || { echo "FAIL  $name  ($summary)"; bad=$((bad+1)); };;
    deny-*)  [ "$passes" = "0" ] && echo "PASS  $name  ($summary)" || { echo "FAIL  $name  ($summary)"; bad=$((bad+1)); };;
  esac
done
echo "failures: $bad"
exit $((bad > 0))
