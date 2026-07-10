#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:---static}"
CHART_VERSION="1.11.2"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

need() {
  command -v "$1" >/dev/null || fail "missing required tool: $1"
}

assert_pattern() {
  local pattern="$1" file="$2"
  rg -q -- "$pattern" "$file" || fail "missing pattern '$pattern' in $file"
}

verify_static() {
  need helm
  need kubectl
  need rg

  local tmp
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN

  helm template longhorn longhorn \
    --repo https://charts.longhorn.io \
    --version "$CHART_VERSION" \
    --namespace longhorn-system \
    --values "$ROOT/storage/longhorn/values.yaml" \
    >"$tmp/longhorn-rendered.yaml"

  kubectl kustomize "$ROOT" >"$tmp/infra-rendered.yaml"
  kubectl kustomize "$ROOT/kubernetes/storage" >"$tmp/storage-rendered.yaml"

  local -a ansible_cmd ansible_galaxy_cmd
  if command -v ansible-playbook >/dev/null; then
    ansible_cmd=(ansible-playbook)
    ansible_galaxy_cmd=(ansible-galaxy)
  elif command -v uvx >/dev/null; then
    ansible_cmd=(uvx --from ansible-core ansible-playbook)
    ansible_galaxy_cmd=(uvx --from ansible-core ansible-galaxy)
  else
    fail "missing ansible-playbook (or uvx fallback)"
  fi

  ANSIBLE_COLLECTIONS_PATH="$tmp/collections" "${ansible_galaxy_cmd[@]}" collection install \
    -r "$ROOT/ansible/requirements.yml" \
    -p "$tmp/collections" >/dev/null

  ANSIBLE_COLLECTIONS_PATH="$tmp/collections" "${ansible_cmd[@]}" --syntax-check \
    -i "$ROOT/ansible/inventory/ks5.example.ini" \
    "$ROOT/ansible/playbooks/longhorn-prereqs.yml" >/dev/null
  ANSIBLE_COLLECTIONS_PATH="$tmp/collections" "${ansible_cmd[@]}" --syntax-check \
    -i "$ROOT/ansible/inventory/ks5.example.ini" \
    "$ROOT/ansible/playbooks/enable-sauvage-longhorn-attach-only.yml" >/dev/null

  assert_pattern 'create-default-disk-labeled-nodes: true' "$tmp/longhorn-rendered.yaml"
  assert_pattern 'storage-over-provisioning-percentage: "110"' "$tmp/longhorn-rendered.yaml"
  assert_pattern 'default-replica-count: .*v1.*v2' "$tmp/longhorn-rendered.yaml"
  assert_pattern 'storage-longhorn: "true"' "$tmp/longhorn-rendered.yaml"
  assert_pattern 'key: role' "$tmp/longhorn-rendered.yaml"
  assert_pattern 'value: edge' "$tmp/longhorn-rendered.yaml"
  assert_pattern 'key: pocharlies.io/pool' "$tmp/longhorn-rendered.yaml"

  assert_pattern 'name: longhorn-openclaw-encrypted' "$tmp/storage-rendered.yaml"
  assert_pattern 'encrypted: "true"' "$tmp/storage-rendered.yaml"
  assert_pattern 'nodeSelector: ks5-nvme' "$tmp/storage-rendered.yaml"
  assert_pattern 'diskSelector: nvme' "$tmp/storage-rendered.yaml"
  assert_pattern 'numberOfReplicas: "3"' "$tmp/storage-rendered.yaml"
  assert_pattern 'csi.storage.k8s.io/provisioner-secret-name: \$\{pvc\.name\}' "$tmp/storage-rendered.yaml"
  assert_pattern 'csi.storage.k8s.io/node-expand-secret-namespace: \$\{pvc\.namespace\}' "$tmp/storage-rendered.yaml"

  echo "Sauvage/Longhorn static verification OK (chart $CHART_VERSION)"
}

ready_pods_on_sauvage() {
  local selector="$1"
  kubectl -n longhorn-system get pods \
    -l "$selector" --field-selector spec.nodeName=sauvage -o json \
    | jq '[.items[] | select(.status.conditions[]? | .type == "Ready" and .status == "True")] | length'
}

verify_live() {
  need helm
  need kubectl
  need jq

  local chart
  chart="$(helm -n longhorn-system list -o json | jq -r '.[] | select(.name == "longhorn") | .chart')"
  [[ "$chart" == "longhorn-$CHART_VERSION" ]] || fail "live chart is $chart, expected longhorn-$CHART_VERSION"

  kubectl get node sauvage -o json | jq -e '
    .metadata.labels["storage-longhorn"] == "true" and
    (.status.conditions | any(.type == "Ready" and .status == "True"))
  ' >/dev/null || fail "Sauvage is not Ready/admitted"

  kubectl -n longhorn-system get nodes.longhorn.io sauvage -o json | jq -e '
    .spec.allowScheduling == false and
    ([.spec.disks[]? | select(.allowScheduling == true)] | length == 0)
  ' >/dev/null || fail "Sauvage is replica-schedulable"

  local replicas
  replicas="$(kubectl -n longhorn-system get replicas.longhorn.io \
    -l longhornnode=sauvage -o json | jq '.items | length')"
  [[ "$replicas" == "0" ]] || fail "$replicas replica(s) found on Sauvage"

  [[ "$(ready_pods_on_sauvage app=longhorn-manager)" -ge 1 ]] \
    || fail "Longhorn manager is not Ready on Sauvage"
  [[ "$(ready_pods_on_sauvage app=longhorn-csi-plugin)" -ge 1 ]] \
    || fail "Longhorn CSI plugin is not Ready on Sauvage"
  [[ "$(ready_pods_on_sauvage longhorn.io/component=engine-image)" -ge 1 ]] \
    || fail "Longhorn engine image is not Ready on Sauvage"
  [[ "$(ready_pods_on_sauvage longhorn.io/component=instance-manager)" -ge 1 ]] \
    || fail "Longhorn instance manager is not Ready on Sauvage"

  kubectl get storageclass longhorn-openclaw-encrypted -o json | jq -e '
    .provisioner == "driver.longhorn.io" and
    .reclaimPolicy == "Retain" and
    .allowVolumeExpansion == true and
    .parameters.encrypted == "true" and
    .parameters.numberOfReplicas == "3" and
    .parameters.nodeSelector == "ks5-nvme" and
    .parameters.diskSelector == "nvme" and
    .parameters["csi.storage.k8s.io/provisioner-secret-name"] == "${pvc.name}" and
    .parameters["csi.storage.k8s.io/provisioner-secret-namespace"] == "${pvc.namespace}" and
    .parameters["csi.storage.k8s.io/node-expand-secret-name"] == "${pvc.name}" and
    .parameters["csi.storage.k8s.io/node-expand-secret-namespace"] == "${pvc.namespace}"
  ' >/dev/null || fail "encrypted CODEX_HOME StorageClass drifted"

  echo "Sauvage/Longhorn live verification OK"
}

case "$MODE" in
  --static) verify_static ;;
  --live) verify_live ;;
  *) fail "usage: $0 [--static|--live]" ;;
esac
