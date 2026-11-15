#!/usr/bin/env bash
# SC-3089: muestreo de sincronización de secretos (criterio C2).
# 12 muestras cada 5 min (60 min) de: app ArgoCD `correo`, ExternalSecrets del
# ns `correo` y el ExternalSecret `harbor-runtime-pull` de photos-mcp (el que
# quedó SecretSyncedError por estar photos-mcp en las dos listas del CES).
# Sale 1 en cuanto una muestra ve OutOfSync/NotReady: así falla ANTES del fix
# y termina "OK 12/12 muestras sincronizadas" después.
set -euo pipefail
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
MUESTRAS=12
INTERVALO=300

mal() { # $1 muestra
  echo "MUESTRA $1 FALLA: $2" >&2
  exit 1
}

for i in $(seq 1 "$MUESTRAS"); do
  sync=$(kubectl get application -n argocd correo -o jsonpath='{.status.sync.status}')
  [ "$sync" = "Synced" ] || mal "$i" "app correo $sync"

  bad=$(kubectl get externalsecret -n correo \
    -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].reason' \
    --no-headers | awk '$2!="SecretSynced"{print $1"="$2}')
  [ -z "$bad" ] || mal "$i" "correo: $bad"

  reason=$(kubectl get externalsecret harbor-runtime-pull -n photos-mcp \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].reason}')
  [ "$reason" = "SecretSynced" ] || mal "$i" "photos-mcp/harbor-runtime-pull: ${reason:-sin-condition}"

  echo "muestra $i/$MUESTRAS: correo Synced, ES correo SecretSynced, harbor-runtime-pull SecretSynced"
  [ "$i" -lt "$MUESTRAS" ] && sleep "$INTERVALO"
done

echo "OK $MUESTRAS/$MUESTRAS muestras sincronizadas"
