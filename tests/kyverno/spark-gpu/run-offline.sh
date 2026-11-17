#!/usr/bin/env bash
# DGX-1665: offline check of spark-gpu-queue-only (platform/kyverno/policies.yaml) with the
# Kyverno CLI (same version as the cluster, v1.18.x). No cluster needed.
# Each fixture's first line `# user: <username>` is the requester the API server would see.
# Expectation: deny-* => exactly 1 rule fails; allow-* => 0 fails.
# usage: ./run-offline.sh [path-to-kyverno-binary]
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
K="${1:-kyverno}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
python3 - "$DIR/../../../platform/kyverno/policies.yaml" "$TMP/policy.yaml" <<'PY'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1])) if d]
pol = [d for d in docs if d["metadata"]["name"] == "spark-gpu-queue-only"][0]
yaml.safe_dump(pol, open(sys.argv[2], "w"))
PY
bad=0
for f in "$DIR"/deny-*.yaml "$DIR"/allow-*.yaml; do
  name="$(basename "$f" .yaml)"
  user="$(sed -n '1s/^# user: //p' "$f")"
  printf 'apiVersion: cli.kyverno.io/v1alpha1\nkind: UserInfo\nmetadata:\n  name: u\nuserInfo:\n  username: "%s"\n' "$user" > "$TMP/user.yaml"
  summary="$("$K" apply "$TMP/policy.yaml" --resource "$f" --userinfo "$TMP/user.yaml" 2>&1 | grep -E 'pass:.*fail:' | tail -1)"
  fails="$(printf '%s' "$summary" | sed -E 's/.*fail: ([0-9]+).*/\1/')"
  case "$name" in
    deny-*)  [ "$fails" = "1" ] && echo "PASS  $name  ($summary)" || { echo "FAIL  $name  ($summary)"; bad=$((bad+1)); };;
    allow-*) [ "$fails" = "0" ] && echo "PASS  $name  ($summary)" || { echo "FAIL  $name  ($summary)"; bad=$((bad+1)); };;
  esac
done
echo "failures: $bad"
exit $((bad > 0))
