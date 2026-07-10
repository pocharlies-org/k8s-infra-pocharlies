#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-}"
FROM_VERSION="${2:-}"
TARGET_VERSION="${3:-}"
KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
EXPECTED_KUBE_CONTEXT="${EXPECTED_KUBE_CONTEXT:-x86-k3s}"
export KUBECTL_BIN EXPECTED_KUBE_CONTEXT
NODE=sauvage
NAMESPACE=system-upgrade
SUC_VERSION=v0.19.2
SUC_MANIFEST_SHA256=bdb0efbf63e3296666b223e16ccf70a67ce6343b3446b6495a62254bc076f612
SUC_CRD_SHA256=f8f488252adceaad35c6b322ccd35bfbdb851c19b5796df853e8119ebbd0ca6c
SUC_IMAGE='rancher/system-upgrade-controller:v0.19.2@sha256:34fa058fe453da2e1d6cf9052d2961976d5c7294921f8a6a6fb75098a27b0e89'

fail() { echo "sauvage SUC upgrade: FAIL: $*" >&2; exit 1; }
kctl() { "$KUBECTL_BIN" "$@"; }
slug() { sed -E 's/[^A-Za-z0-9._-]+/-/g' <<<"$1"; }

usage() {
  echo "Usage: $0 install | upgrade FROM_VERSION TARGET_VERSION | rollback CURRENT_VERSION ROLLBACK_VERSION | cleanup" >&2
  exit 2
}

require_controller_context() {
  [[ -x "$KUBECTL_BIN" ]] || command -v "$KUBECTL_BIN" >/dev/null 2>&1 ||
    fail "kubectl is missing: $KUBECTL_BIN"
  [[ "$(kctl config current-context)" == "$EXPECTED_KUBE_CONTEXT" ]] ||
    fail "unexpected kubectl context"
  kctl get --raw=/readyz >/dev/null
}

require_confirmation() {
  local expected="$1"
  [[ "${CONFIRM_K3S_SAUVAGE_SUC:-}" == "$expected" ]] ||
    fail "set CONFIRM_K3S_SAUVAGE_SUC=$expected"
}

release_image() {
  case "$1" in
    v1.32.13+k3s1)
      echo 'rancher/k3s-upgrade:v1.32.13-k3s1@sha256:a51530d62449b469b7c76ec191117ad1cc3325cab8f0bbcc0991aa6f9a631962'
      ;;
    v1.33.13+k3s1)
      echo 'rancher/k3s-upgrade:v1.33.13-k3s1@sha256:54045ecd5de79a3fe60f6c98da330c582592290020bed33c48ed414e223ee37d'
      ;;
    v1.34.9+k3s1)
      echo 'rancher/k3s-upgrade:v1.34.9-k3s1@sha256:11165b0e53d09f870e339c0a3a5efdf7ea2d693f3d04381c2209883f6690ebcf'
      ;;
    v1.35.6+k3s1)
      echo 'rancher/k3s-upgrade:v1.35.6-k3s1@sha256:ee89420a1a545cbd2b8334161dd4b11ba4836a330f67e71ad1ae5ce005ee3bc6'
      ;;
    *) fail "unsupported target image version: $1" ;;
  esac
}

require_adjacent_upgrade() {
  case "$1->$2" in
    'v1.32.5+k3s1->v1.32.13+k3s1'|'v1.32.13+k3s1->v1.33.13+k3s1'|'v1.33.13+k3s1->v1.34.9+k3s1'|'v1.34.9+k3s1->v1.35.6+k3s1') ;;
    *) fail "unsupported or non-adjacent K3s upgrade: $1 -> $2" ;;
  esac
}

verified_controller_manifests() {
  local destination="$1"
  curl -fL --retry 3 --proto '=https' --tlsv1.2 \
    -o "$destination/crd.yaml" \
    "https://github.com/rancher/system-upgrade-controller/releases/download/$SUC_VERSION/crd.yaml"
  curl -fL --retry 3 --proto '=https' --tlsv1.2 \
    -o "$destination/controller.yaml" \
    "https://github.com/rancher/system-upgrade-controller/releases/download/$SUC_VERSION/system-upgrade-controller.yaml"
  printf '%s  %s\n' "$SUC_CRD_SHA256" "$destination/crd.yaml" | shasum -a 256 -c -
  printf '%s  %s\n' "$SUC_MANIFEST_SHA256" "$destination/controller.yaml" | shasum -a 256 -c -
}

install_controller() {
  local temporary
  temporary="$(mktemp -d)"
  verified_controller_manifests "$temporary"
  kctl apply -f "$temporary/crd.yaml" -f "$temporary/controller.yaml"
  kctl -n "$NAMESPACE" set image deployment/system-upgrade-controller \
    "system-upgrade-controller=$SUC_IMAGE"
  kctl -n "$NAMESPACE" rollout status deployment/system-upgrade-controller --timeout=5m
  rm -rf "$temporary"
}

node_version() {
  kctl get node "$NODE" -o jsonpath='{.status.nodeInfo.kubeletVersion}'
}

assert_node_ready() {
  [[ "$(kctl get node "$NODE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')" == True ]] ||
    fail "$NODE is not Ready"
}

apply_plan() {
  local from="$1" target="$2" image="$3" plan="$4" backup_dir
  backup_dir="/host/var/lib/k3s-upgrade-backups/$(slug "$from")"
  kctl apply -f - <<EOF
apiVersion: upgrade.cattle.io/v1
kind: Plan
metadata:
  name: $plan
  namespace: $NAMESPACE
spec:
  concurrency: 1
  version: $target
  nodeSelector:
    matchExpressions:
      - key: kubernetes.io/hostname
        operator: In
        values: [$NODE]
  serviceAccountName: system-upgrade
  jobActiveDeadlineSecs: 1200
  prepare:
    image: $image
    command: ["/bin/sh", "-ceu"]
    args:
      - |
        umask 077
        test -x /host/usr/local/bin/k3s
        mkdir -p $backup_dir
        if [ ! -e $backup_dir/k3s ]; then
          cp -p /host/usr/local/bin/k3s $backup_dir/k3s
          cp -a /host/etc/rancher/k3s $backup_dir/config
          if [ -e /host/etc/systemd/system/k3s-agent.service ]; then
            cp -p /host/etc/systemd/system/k3s-agent.service $backup_dir/
          fi
          sha256sum $backup_dir/k3s >$backup_dir/k3s.sha256
          chmod -R go-rwx $backup_dir
        fi
  upgrade:
    image: $image
EOF
}

wait_for_target() {
  local target="$1" plan="$2" deadline now failed_jobs
  deadline=$((SECONDS + 1200))
  while ((SECONDS < deadline)); do
    if [[ "$(node_version)" == "$target" ]]; then
      assert_node_ready
      return 0
    fi
    failed_jobs="$(kctl -n "$NAMESPACE" get jobs -l "upgrade.cattle.io/plan=$plan" -o json | jq '[.items[] | select((.status.failed // 0) > 0)] | length')"
    ((failed_jobs == 0)) || fail "upgrade Job failed; node remains cordoned"
    sleep 10
  done
  now="$(node_version)"
  fail "timed out waiting for $target; current version is $now and node remains cordoned"
}

upgrade_node() {
  local from="$1" target="$2" image plan confirmation current unschedulable
  require_adjacent_upgrade "$from" "$target"
  image="$(release_image "$target")"
  plan="sauvage-$(slug "$target")"
  confirmation="upgrade-sauvage-to-$(slug "$target")"
  require_confirmation "$confirmation"
  current="$(node_version)"
  unschedulable="$(kctl get node "$NODE" -o jsonpath='{.spec.unschedulable}')"
  if [[ "$current" == "$target" && "$unschedulable" == true ]]; then
    assert_node_ready
    "$(dirname "$0")/k3s_upgrade_gate.sh" post-node \
      --expected-versions "$from,$target" --target-node "$NODE"
    kctl uncordon "$NODE"
    "$(dirname "$0")/k3s_upgrade_gate.sh" preflight \
      --expected-versions "$from,$target"
    kctl -n "$NAMESPACE" delete plan "$plan" --ignore-not-found
    return
  fi
  if [[ "$current" == "$target" && "$unschedulable" != true ]]; then
    kctl -n "$NAMESPACE" delete plan "$plan" --ignore-not-found
    return
  fi
  [[ "$current" == "$from" ]] || fail "$NODE does not run $from"
  assert_node_ready
  [[ "$unschedulable" != true ]] ||
    fail "$NODE is already cordoned"

  "$(dirname "$0")/k3s_upgrade_gate.sh" preflight \
    --expected-versions "$from,$target"

  kctl cordon "$NODE"
  if ! kctl drain "$NODE" --dry-run=server --ignore-daemonsets \
    --delete-emptydir-data --timeout=45m; then
    kctl uncordon "$NODE"
    fail "server-side drain dry-run failed; node was uncordoned"
  fi
  if ! kctl drain "$NODE" --ignore-daemonsets --delete-emptydir-data --timeout=45m; then
    kctl uncordon "$NODE"
    fail "drain failed without PDB bypass; node was uncordoned"
  fi

  apply_plan "$from" "$target" "$image" "$plan"
  wait_for_target "$target" "$plan"
  "$(dirname "$0")/k3s_upgrade_gate.sh" post-node \
    --expected-versions "$from,$target" --target-node "$NODE"
  kctl uncordon "$NODE"
  "$(dirname "$0")/k3s_upgrade_gate.sh" preflight \
    --expected-versions "$from,$target"
  kctl -n "$NAMESPACE" delete plan "$plan" --ignore-not-found
}

rollback_node() {
  local current="$1" rollback="$2" image job backup_dir confirmation
  image="$(release_image "$current")"
  job="sauvage-rollback-$(slug "$rollback")"
  backup_dir="/host/var/lib/k3s-upgrade-backups/$(slug "$rollback")"
  confirmation="rollback-sauvage-to-$(slug "$rollback")"
  require_confirmation "$confirmation"
  [[ "$(node_version)" == "$current" ]] || fail "$NODE does not run $current"
  [[ "$(kctl get node "$NODE" -o jsonpath='{.spec.unschedulable}')" == true ]] ||
    fail "$NODE must remain cordoned for rollback"
  kctl -n "$NAMESPACE" delete job "$job" --ignore-not-found --wait=true
  kctl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: $job
  namespace: $NAMESPACE
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 600
  template:
    spec:
      restartPolicy: Never
      nodeName: $NODE
      hostPID: true
      containers:
        - name: rollback
          image: $image
          imagePullPolicy: IfNotPresent
          command: ["/bin/sh", "-ceu"]
          args:
            - |
              test -f $backup_dir/k3s
              cd $backup_dir
              sha256sum -c k3s.sha256
              install -o root -g root -m 0755 k3s /host/usr/local/bin/k3s.rollback
              mv -f /host/usr/local/bin/k3s.rollback /host/usr/local/bin/k3s
              pid="\$(ps -ef | grep -E '( |/)k3s .*agent' | grep -E -v '(init|grep|channelserver|supervise-daemon)' | awk '{print \$2}')"
              test "\$(echo "\$pid" | wc -w)" = 1
              kill -TERM "\$pid"
          securityContext:
            privileged: true
          volumeMounts:
            - name: host-root
              mountPath: /host
      volumes:
        - name: host-root
          hostPath:
            path: /
            type: Directory
EOF
  kctl -n "$NAMESPACE" wait --for=condition=complete "job/$job" --timeout=10m
  local deadline=$((SECONDS + 600))
  while ((SECONDS < deadline)); do
    if [[ "$(node_version)" == "$rollback" ]]; then
      assert_node_ready
      "$(dirname "$0")/k3s_upgrade_gate.sh" post-node \
        --expected-versions "$rollback,$current" --target-node "$NODE"
      kctl uncordon "$NODE"
      return 0
    fi
    sleep 10
  done
  fail "rollback Job completed but node did not report $rollback"
}

cleanup_controller() {
  local temporary
  [[ "$(kctl -n "$NAMESPACE" get plans.upgrade.cattle.io -o json 2>/dev/null | jq '.items | length')" == 0 ]] ||
    fail "delete or resolve all upgrade Plans before cleanup"
  temporary="$(mktemp -d)"
  verified_controller_manifests "$temporary"
  kctl delete -f "$temporary/controller.yaml" -f "$temporary/crd.yaml" --ignore-not-found
  rm -rf "$temporary"
}

require_controller_context
case "$ACTION" in
  install)
    require_confirmation install-sauvage-system-upgrade-controller
    install_controller
    ;;
  upgrade)
    [[ -n "$FROM_VERSION" && -n "$TARGET_VERSION" ]] || usage
    upgrade_node "$FROM_VERSION" "$TARGET_VERSION"
    ;;
  rollback)
    [[ -n "$FROM_VERSION" && -n "$TARGET_VERSION" ]] || usage
    rollback_node "$FROM_VERSION" "$TARGET_VERSION"
    ;;
  cleanup)
    require_confirmation remove-sauvage-system-upgrade-controller
    cleanup_controller
    ;;
  *) usage ;;
esac
