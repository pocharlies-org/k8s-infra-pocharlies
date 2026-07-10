#!/usr/bin/env bash
set -euo pipefail
set +x
umask 077
ulimit -c 0 >/dev/null 2>&1 || true

EXPECTED_CONTEXT="${EXPECTED_CONTEXT:-x86-k3s}"
[[ "$(kubectl config current-context)" == "$EXPECTED_CONTEXT" ]] || {
  printf 'ERROR: unexpected Kubernetes context\n' >&2
  exit 1
}

ready_es() {
  local namespace="$1" name="$2"
  [[ "$(kubectl -n "$namespace" get externalsecret "$name" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')" == "True" ]]
}

exact_keys() {
  local namespace="$1" name="$2" expected="$3"
  local actual
  actual="$(kubectl -n "$namespace" get secret "$name" -o json | jq -r '.data | keys | sort | join(",")')"
  [[ "$actual" == "$expected" ]]
}

secret_value() {
  kubectl -n "$1" get secret "$2" -o "go-template={{ index .data \"$3\" | base64decode }}"
}

ready_es harbor harbor-s3-credentials
ready_es velero velero-s3-credentials
ready_es monitoring loki-s3-credentials
exact_keys harbor harbor-s3-credentials 'REGISTRY_STORAGE_S3_ACCESSKEY,REGISTRY_STORAGE_S3_SECRETKEY'
exact_keys velero velero-s3-credentials 'cloud'
exact_keys monitoring loki-s3-credentials 'LOKI_S3_ACCESS_KEY,LOKI_S3_SECRET_KEY'

root_user="$(secret_value minio minio-root root-user)"
root_password="$(secret_value minio minio-root root-password)"
harbor_user="$(secret_value harbor harbor-s3-credentials REGISTRY_STORAGE_S3_ACCESSKEY)"
harbor_password="$(secret_value harbor harbor-s3-credentials REGISTRY_STORAGE_S3_SECRETKEY)"
velero_cloud="$(secret_value velero velero-s3-credentials cloud)"
velero_user="$(printf '%s\n' "$velero_cloud" | sed -n 's/^aws_access_key_id=//p')"
velero_password="$(printf '%s\n' "$velero_cloud" | sed -n 's/^aws_secret_access_key=//p')"
loki_user="$(secret_value monitoring loki-s3-credentials LOKI_S3_ACCESS_KEY)"
loki_password="$(secret_value monitoring loki-s3-credentials LOKI_S3_SECRET_KEY)"

for candidate in "$harbor_user" "$harbor_password" "$velero_user" "$velero_password" "$loki_user" "$loki_password"; do
  [[ -n "$candidate" ]]
  [[ "$candidate" != "$root_user" ]]
  [[ "$candidate" != "$root_password" ]]
done

loki_config="$(kubectl -n monitoring get configmap loki -o go-template='{{ index .data "config.yaml" }}')"
[[ "$loki_config" == *'${LOKI_S3_ACCESS_KEY}'* ]]
[[ "$loki_config" == *'${LOKI_S3_SECRET_KEY}'* ]]
[[ "$loki_config" != *"$root_user"* ]]
[[ "$loki_config" != *"$root_password"* ]]

unset root_user root_password harbor_user harbor_password velero_cloud velero_user velero_password loki_user loki_password loki_config candidate

kubectl -n harbor get deployment harbor-registry -o json | jq -e '
  [.spec.template.spec.containers[] | select(.name == "registry" or .name == "registryctl") |
   (.envFrom // [])[]?.secretRef.name] |
  map(select(. == "harbor-s3-credentials")) | length == 2
' >/dev/null

[[ "$(kubectl -n velero get backupstoragelocation default -o jsonpath='{.status.phase}')" == "Available" ]]
[[ "$(kubectl -n velero get backupstoragelocation default -o jsonpath='{.spec.credential.name}')" == "velero-s3-credentials" ]]

kubectl -n monitoring get statefulset loki -o json | jq -e '
  [.spec.template.spec.containers[] | select(.name == "loki")][0] as $loki |
  ($loki.args | index("-config.expand-env=true")) != null and
  ([($loki.envFrom // [])[]?.secretRef.name] | index("loki-s3-credentials")) != null
' >/dev/null

kubectl get --raw '/api/v1/namespaces/minio/services/http:minio-s3:9000/proxy/minio/health/ready' >/dev/null
kubectl get --raw '/api/v1/namespaces/harbor/services/http:harbor:80/proxy/api/v2.0/health' >/dev/null
kubectl get --raw '/api/v1/namespaces/monitoring/services/http:loki:3100/proxy/ready' >/dev/null

printf 'MINIO_WORKLOAD_CUTOVER_RUNTIME_PASS\n'
