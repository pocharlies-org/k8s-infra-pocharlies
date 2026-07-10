#!/usr/bin/env bash
set -euo pipefail

EXPECTED_VERSION=""
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
EXPECTED_KUBE_CONTEXT="${EXPECTED_KUBE_CONTEXT:-x86-k3s}"
OPENCLAW_SMOKE_REPO="${OPENCLAW_SMOKE_REPO:-}"
OPENCLAW_NAMESPACE="${OPENCLAW_NAMESPACE:-openclaw-qwen36}"
OPENCLAW_ARGO_APPLICATION="${OPENCLAW_ARGO_APPLICATION:-openclaw-qwen36}"

while (($#)); do
  case "$1" in
    --expected-k3s-version) EXPECTED_VERSION="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$EXPECTED_VERSION" ]]; then
  echo "Usage: $0 --expected-k3s-version VERSION" >&2
  exit 2
fi
case "$EXPECTED_VERSION" in
  v1.32.13+k3s1|v1.33.13+k3s1|v1.34.9+k3s1|v1.35.6+k3s1) ;;
  *) echo "Unsupported completed K3s stage: $EXPECTED_VERSION" >&2; exit 2 ;;
esac

fail() { echo "OpenClaw functional gate: FAIL: $*" >&2; exit 1; }
kctl() { "$KUBECTL_BIN" "$@"; }

for command in git jq bash; do
  command -v "$command" >/dev/null 2>&1 || fail "required executable missing: $command"
done
if [[ "$KUBECTL_BIN" == */* ]]; then
  [[ -x "$KUBECTL_BIN" ]] || fail "kubectl is missing or not executable: $KUBECTL_BIN"
  kubectl_path="$(cd "$(dirname "$KUBECTL_BIN")" && pwd -P)/$(basename "$KUBECTL_BIN")"
else
  kubectl_path="$(command -v "$KUBECTL_BIN" || true)"
  [[ -n "$kubectl_path" ]] || fail "kubectl is missing: $KUBECTL_BIN"
fi

context="$(kctl config current-context 2>/dev/null || true)"
[[ "$context" == "$EXPECTED_KUBE_CONTEXT" ]] ||
  fail "kubectl context is '$context', expected '$EXPECTED_KUBE_CONTEXT'"
kctl get --raw=/readyz >/dev/null || fail "Kubernetes API readyz failed"

nodes_json="$(kctl get nodes -o json)"
[[ "$(jq '.items | length' <<<"$nodes_json")" -gt 0 ]] || fail "Kubernetes API returned no nodes"
unexpected_nodes="$(jq --arg version "$EXPECTED_VERSION" '
  [.items[] | select(.status.nodeInfo.kubeletVersion != $version) |
    {name:.metadata.name,version:.status.nodeInfo.kubeletVersion}]
' <<<"$nodes_json")"
[[ "$(jq 'length' <<<"$unexpected_nodes")" == 0 ]] ||
  fail "functional smoke is post-stage only; unexpected node versions: $(jq -c . <<<"$unexpected_nodes")"

[[ -n "$OPENCLAW_SMOKE_REPO" ]] ||
  fail "OPENCLAW_SMOKE_REPO must point to a clean checkout of the deployed OpenClaw revision"
[[ "$OPENCLAW_SMOKE_REPO" == /* ]] || fail "OPENCLAW_SMOKE_REPO must be an absolute path"
[[ -d "$OPENCLAW_SMOKE_REPO/.git" || -f "$OPENCLAW_SMOKE_REPO/.git" ]] ||
  fail "OPENCLAW_SMOKE_REPO is not a Git checkout"
smoke_repo="$(cd "$OPENCLAW_SMOKE_REPO" && pwd -P)"

origin="$(git -C "$smoke_repo" remote get-url origin 2>/dev/null || true)"
if [[ ! "$origin" =~ ^(https://github.com/|git@github.com:|ssh://git@github.com/)pocharlies-org/k8s-openclaw-qwen36-pocharlies(\.git)?$ ]]; then
  fail "unexpected OpenClaw origin: $origin"
fi
[[ -z "$(git -C "$smoke_repo" status --porcelain --untracked-files=normal)" ]] ||
  fail "OpenClaw smoke checkout is dirty"

application_json="$(kctl -n argocd get application.argoproj.io "$OPENCLAW_ARGO_APPLICATION" -o json)"
jq -e --arg namespace "$OPENCLAW_NAMESPACE" '
  .status.sync.status == "Synced" and
  .status.health.status == "Healthy" and
  .spec.destination.namespace == $namespace and
  .spec.source.repoURL == "https://github.com/pocharlies-org/k8s-openclaw-qwen36-pocharlies" and
  .spec.source.path == "helm/openclaw-qwen36"
' <<<"$application_json" >/dev/null || fail "OpenClaw Argo Application is not the expected Synced/Healthy source"
live_revision="$(jq -r '.status.sync.revision // empty' <<<"$application_json")"
repo_revision="$(git -C "$smoke_repo" rev-parse HEAD)"
[[ "$live_revision" =~ ^[0-9a-f]{40}$ && "$repo_revision" == "$live_revision" ]] ||
  fail "smoke checkout $repo_revision does not match deployed Argo revision $live_revision"

required_files=(
  scripts/smoke-social-gateway.sh
  scripts/smoke-workboard.sh
  scripts/smoke-codex-k8s.sh
  scripts/select-ready-pod.jq
  scripts/validate-codex-smoke-result.jq
)
for relative_path in "${required_files[@]}"; do
  [[ -r "$smoke_repo/$relative_path" ]] || fail "required official smoke asset missing: $relative_path"
done
grep -Fq 'codex-smoke-cleanup-contract:v2' "$smoke_repo/scripts/smoke-codex-k8s.sh" ||
  fail "Codex smoke lacks the required verified delete-after-read cleanup contract"
grep -Fq 'openclaw-smoke-session-cleanup-contract:v1' "$smoke_repo/scripts/smoke-codex-k8s.sh" ||
  fail "Codex smoke lacks the required OpenClaw session/transcript cleanup contract"

shim_dir="$(mktemp -d)"
trap 'rm -rf "$shim_dir"' EXIT HUP INT TERM
printf '#!/usr/bin/env bash\nexec %q --context %q "$@"\n' \
  "$kubectl_path" "$EXPECTED_KUBE_CONTEXT" >"$shim_dir/kubectl"
chmod 0755 "$shim_dir/kubectl"
export PATH="$shim_dir:$PATH"
export OPENCLAW_NAMESPACE

(
  cd "$smoke_repo"
  bash scripts/smoke-social-gateway.sh
  bash scripts/smoke-workboard.sh
  bash scripts/smoke-codex-k8s.sh
)

printf 'OpenClaw functional gate: PASS revision=%s k3s=%s\n' "$live_revision" "$EXPECTED_VERSION"
