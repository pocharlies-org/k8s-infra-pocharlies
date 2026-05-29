#!/usr/bin/env bash
set -euo pipefail

kubectl get nodes -L node-pool,storage,db-storage,workload,topology,region

echo "== production pods still on home-dev/x86 =="
kubectl get pods -A -o json | jq -r '
  [
    .items[]
    | select(.spec.nodeName == "ubuntu")
    | select(.metadata.namespace as $ns | ["kube-system","longhorn-system","velero"] | index($ns) | not)
    | .metadata.namespace
  ]
  | group_by(.)
  | map({namespace: .[0], pods: length})
  | sort_by(.namespace)
  | .[]
  | [.namespace, .pods] | @tsv
'

echo "== stateful pods =="
kubectl get pods -A -o json | jq -r '
  .items[]
  | select((.metadata.name | test("postgres|rabbitmq|qdrant|falkor|brain"; "i")) or (.metadata.namespace | test("databases|brain"; "i")))
  | select(.status.phase != "Succeeded")
  | [.metadata.namespace, .metadata.name, (.status.phase // "Unknown"), (.spec.nodeName // "<pending>")] | @tsv
'
