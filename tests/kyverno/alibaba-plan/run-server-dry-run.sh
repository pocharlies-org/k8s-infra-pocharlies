#!/usr/bin/env bash
# DGX-626: server-side dry-run of the fixtures against the live cluster.
# Nothing is created: every call is --dry-run=server. Run it AFTER ArgoCD has
# synced the ClusterPolicy externalsecret-alibaba-plan-only-litellm.
#
#   deny-*.yaml   must be DENIED (exit != 0, message names DGX-619), in a
#                 namespace that is not litellm (TEST_NS, default: default)
#   allow-*.yaml  must be ADMITTED (exit 0); the allow-litellm-* ones keep
#                 their namespace litellm, the others go to TEST_NS
#
# usage: KUBECONFIG=~/.kube/config [TEST_NS=default] ./run-server-dry-run.sh
# exit 0 only if every case behaves as expected.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
KUBECTL=(kubectl --kubeconfig "${KUBECONFIG:-$HOME/.kube/config}")
TEST_NS="${TEST_NS:-default}"
bad=0

"${KUBECTL[@]}" get clusterpolicy externalsecret-alibaba-plan-only-litellm >/dev/null 2>&1 \
  || echo "NOTE: the ClusterPolicy is not in the cluster yet; every deny case will show as FAIL (control run)."

for f in "$DIR"/deny-*.yaml "$DIR"/allow-*.yaml; do
  name="$(basename "$f" .yaml)"
  manifest="$(sed "s/namespace: dgx626-test/namespace: ${TEST_NS}/" "$f")"
  out="$(printf '%s\n' "$manifest" | "${KUBECTL[@]}" apply --dry-run=server -f - 2>&1)"
  rc=$?
  case "$name" in
    deny-*)
      if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q 'DGX-619'; then
        echo "PASS  $name  DENIED: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"
      else
        echo "FAIL  $name  expected DENIED, got rc=$rc: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"; bad=$((bad+1))
      fi;;
    allow-*)
      if [ $rc -eq 0 ]; then
        echo "PASS  $name  admitted: $out"
      else
        echo "FAIL  $name  expected ADMITTED, got rc=$rc: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-160)"; bad=$((bad+1))
      fi;;
  esac
done
echo "failures: $bad"
exit $((bad > 0))
