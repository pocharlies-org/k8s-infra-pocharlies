#!/bin/bash
# CA8 (SC-5299 · épica SC-3637, criterio C5) — simulacro casa apagada 1 h desde OVH.
# 5º intento (13-11): corregido el helper de atlantic. Causas del 4º fallo:
#   1) busybox (docker.io) no extraíble en atlantic — la política restrict-image-registries
#      (Audit) del cluster estandariza en harbor/registry.k8s.io/gcr.io/quay.io.
#   2) al YAML le faltaba el volumen hostPath: sin /host montado, "chroot /host" habría
#      fallado igualmente. Corregido: imagen de la casa (digest paseo-atlantic, ya presente
#      en atlantic → 0 descargas) + /host montado + espera por status.phase=Running.
# Reintentos por nodo al poner y verificar (3 intentos, ssh ConnectTimeout=10); se aborta
# solo tras agotarlos, retirando todo.
# Revisión de seguridad del PR #523 (14-11): el corte ya no inserta reglas desde aquí. Cada nodo
# corre /usr/local/sbin/ca8-cut.sh, que programa los dos timers de vuelta ANTES de la primera
# regla (los orígenes incluyen 100.83.56.98, la IP del x86: un corte lanzado desde el x86 tumba
# su propia sesión ssh). Toda retirada usa /usr/local/sbin/ca8-undo.sh. Los dos guiones los
# instala ansible/playbooks/ca8-scripts.yml (pocharlies-org/k8s-infra-pocharlies).
set -u
export KUBECONFIG="$HOME/.kube/config"
EPOCH=$(date +%s)
TAG="ca8-$EPOCH"
# Claves de host fijadas: known_hosts del x86 (compartido con company-0), sin aceptar claves nuevas.
SSHOPTS="-o ConnectTimeout=10 -o BatchMode=yes -o StrictHostKeyChecking=yes -o ServerAliveInterval=5 -o ServerAliveCountMax=3"
NODOS="ks5-cp-1 ks5-cp-2 ks5-cp-3 atlantic alphalink"
# Solo para el registro: la lista que corta es SOURCES de ca8-cut.sh (la misma).
ORIGENES="100.82.12.28 100.73.153.70 100.93.188.99 100.83.56.98 192.168.50.0/24"
HELPER=ca8-atlantic-helper
IMG=harbor.lan.e-dani.com/homelab/paseo-atlantic@sha256:6e94762849d4c95b1cb85677c32ab7367022d2cd4f4208a994125b8a0a1d34a1
JR="python3 $HOME/.local/libexec/x86-host-runtime/jira_rest.py"
LOG=/tmp/ca8-20261113c.log
VM=http://vmsingle-vm-victoria-metrics-k8s-stack.monitoring.svc:8428
# Guiones del nodo. CUT <tag> <secs>: timers de vuelta (secs y secs+900) y después 5 DROP con
# comentario "ca8-<tag>". UNDO: retira toda regla cuyo comentario empiece por ca8 (idempotente).
# NUNCA un undo a mano: el anterior (sed "s/-A INPUT/-D INPUT/" | sh) no llevaba el comando
# iptables (exit 127) y dejó atlantic cortado el 2026-11-13.
CUT=/usr/local/sbin/ca8-cut.sh
UNDO=/usr/local/sbin/ca8-undo.sh
N_OK=0
RESULTATS=""

ts(){ date -u '+%Y-%m-%dT%H:%M:%SZ'; }
log(){ printf '%s %s\n' "$(ts)" "$*"; }

node_cmd(){ local n=$1 cmd=$2
  case $n in
    ks5-cp-*) ssh $SSHOPTS "root@$n" "$cmd" ;;
    alphalink) ssh $SSHOPTS alphalink "sudo -n sh -c $(printf '%q' "$cmd")" ;;
    atlantic) kubectl exec "$HELPER" -- chroot /host /bin/sh -c "$cmd" ;;
  esac
}

# 3 intentos por operación de nodo; el log del fallo va al registro
retry_nodo(){ local n=$1; shift; local i
  for i in 1 2 3; do
    if "$@" > /tmp/ca8-retry.out 2>&1; then return 0; fi
    log "  $n: intento $i/3 falló → $(tr '\n' ' ' < /tmp/ca8-retry.out | tail -c 160)"
    sleep 5
  done
  return 1
}

reglas_ca8(){ node_cmd "$1" "iptables -S INPUT | grep -c 'comment ca8' || true" | tail -1; }

wipe_nodo(){ local n=$1 c
  node_cmd "$n" "$UNDO" || return 1
  c=$(reglas_ca8 "$n") || return 1
  log "  $n: reglas restantes=$c"
  [ "$c" = "0" ]
}

reglas_tag(){ node_cmd "$1" "iptables -S INPUT | grep -c 'comment $2' || true" | tail -1; }

# corte en el nodo con ca8-cut.sh: undo a undo_s y respaldo a undo_s+900 programados ANTES de
# la primera regla; el comentario queda "ca8-<tag sin ca8->" = $tag. Verifica 5 reglas.
# Reintento idempotente: si un intento anterior ya cortó (y su ssh cayó después) no se corta
# dos veces; si quedó a medias, se retira con UNDO antes de repetir.
poner_corte(){ local n=$1 tag=$2 undo_s=$3 c
  c=$(reglas_tag "$n" "$tag") || return 1
  [ "$c" = "5" ] && return 0
  if [ "$c" != "0" ]; then node_cmd "$n" "$UNDO" >/dev/null || return 1; fi
  node_cmd "$n" "$CUT ${tag#ca8-} $undo_s" >/dev/null || return 1
  c=$(reglas_tag "$n" "$tag") || return 1
  [ "$c" = "5" ]
}

abortar(){ local n
  log "ABORTO: retirando reglas en todos los nodos"
  for n in $NODOS; do retry_nodo "$n" wipe_nodo "$n" || log "  $n: NO SE PUISO VERIFICAR LIMPIO"; done
}

final(){ local veredicto=$1
  log "$veredicto"
  $JR attach --rol devops SC-5299 "$LOG" --as nota-devops-ca8-registro.md >/dev/null 2>&1 \
    && log "registro adjuntado a SC-5299 como nota-devops-ca8-registro.md" \
    || log "AVISO: no se pudo adjuntar el registro"
}

limpiar(){ local n
  for n in $NODOS; do node_cmd "$n" "$UNDO" >/dev/null 2>&1 || true; done
  kubectl delete pod "$HELPER" --ignore-not-found >/dev/null 2>&1 || true
}
trap limpiar EXIT

# ---------- preflight ----------
log "=== CA8 re-lanzamiento (SC-5299 / C5) — casa apagada 1 h desde OVH · tag $TAG ==="
log "Nodos cortados: $NODOS · Orígenes descartados: $ORIGENES"
log "salvage: sauvage NO se corta (sudo con contraseña) — hueco de fidelidad declarado"

PHASE=$(kubectl get cm -n comfyui gpu-arbiter-state -o jsonpath='{.data.compute_mode}' 2>/dev/null | grep -o '"phase":"[a-z]*"' | head -1 | cut -d'"' -f4)
if [ "$PHASE" != "ready" ]; then log "BLOQUEO: gpu-arbiter-state phase=$PHASE (exigido ready)"; final "CA8: NO CUMPLE — BLOQUEO preflight (phase=$PHASE)"; exit 2; fi
log "Pre: gpu-arbiter-state phase=ready (solo lectura)"

kubectl delete pod "$HELPER" --ignore-not-found --wait=true --timeout=60s >/dev/null 2>&1
kubectl apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata: {name: $HELPER, namespace: default}
spec:
  nodeName: atlantic
  hostPID: true
  hostNetwork: true
  volumes:
  - name: host
    hostPath: {path: /}
  containers:
  - name: sh
    image: $IMG
    imagePullPolicy: IfNotPresent
    command: ["sleep","5400"]
    securityContext: {privileged: true}
    volumeMounts:
    - {name: host, mountPath: /host}
    resources: {limits: {memory: "64Mi", cpu: "100m"}, requests: {memory: "32Mi", cpu: "10m"}}
YAML
kubectl wait --for=jsonpath='{.status.phase}'=Running pod/$HELPER --timeout=180s || { log "BLOQUEO: helper de atlantic no arranca"; kubectl describe pod $HELPER 2>&1 | sed -n '/^Events:/,$p'; final "CA8: NO CUMPLE — BLOQUEO preflight (helper atlantic)"; exit 2; }

log "Pre: sin restos ca8, guiones instalados y nodos alcanzables (3 intentos por nodo)"
for n in $NODOS; do
  if ! retry_nodo "$n" node_cmd "$n" "test -x $CUT && test -x $UNDO && iptables -S INPUT >/dev/null && iptables -S INPUT | grep -c 'comment ca8' | grep -qx 0"; then
    log "BLOQUEO: $n no responde o tiene restos ca8 tras 3 intentos"; abortar; final "CA8: NO CUMPLE — BLOQUEO preflight ($n)"; exit 2
  fi
done
log "Pre: sin restos ca8 en los 5 nodos. Guiones instalados."

# ---------- pre-test: corte de 2 min en atlantic ----------
log "PRE-TEST: corte de 2 min en atlantic con $CUT (vuelta a 120 s, respaldo a 1020 s)"
if ! retry_nodo atlantic poner_corte atlantic "ca8-pretest-$EPOCH" 120; then
  log "PRE-TEST NO: no se pudieron poner 5 reglas verificadas en atlantic"; abortar; final "CA8: NO CUMPLE — BLOQUEO pre-test"; exit 2
fi
log "PRE-TEST: 5 reglas puestas, temporizador de vuelta a 120 s — duermo 150 s"
sleep 150
c=$(reglas_ca8 atlantic)
if [ "$c" != "0" ]; then log "PRE-TEST NO: quedan $c reglas — el temporizador de vuelta no funcionó"; abortar; final "CA8: NO CUMPLE — BLOQUEO pre-test (temporizador)"; exit 2; fi
log "PRE-TEST OK: el temporizador de vuelta se ejecutó solo y retiró las 5 reglas de atlantic."

# ---------- T0 ----------
T0=$(date +%s)
T0_ISO=$(date -u -d "@$T0" +%Y-%m-%dT%H:%M:%SZ)
log "T0: aplicando el corte en los 5 nodos OVH (epoch $T0)"
pgrep -f 'tmux -L ses-' | sort > /tmp/ca8-tmux-base
BASE_TMUX=$(wc -l < /tmp/ca8-tmux-base)
BASE_ANALISIS=$(kubectl -n analisis get pods --no-headers 2>/dev/null | awk '{print $1" "$3" "$4}' | head -1)
BASE_SUP_RESTART=$(kubectl -n paseo get pod company-0 -o jsonpath='{.status.containerStatuses[?(@.name=="supervisor")].restartCount}' 2>/dev/null)
log "T0: bases — sesiones tmux=$BASE_TMUX · analisis=$BASE_ANALISIS · supervisor restarts=$BASE_SUP_RESTART"
for n in $NODOS; do
  if retry_nodo "$n" poner_corte "$n" "$TAG" 3600; then
    log "  $n: 5 reglas + 2 timers (60'/75') verificados"
  else
    log "ABORTO: reglas incompletas en $n tras 3 intentos"
    abortar; final "CA8: NO CUMPLE — abortado al aplicar T0 en $n"; exit 1
  fi
done

# ---------- mediciones durante la hora ----------
med(){ local id=$1 nombre=$2; if [ "$3" = "0" ]; then N_OK=$((N_OK+1)); RESULTATS="$RESULTATS $id=PASS"; log "$id PASS — $nombre"; else RESULTATS="$RESULTATS $id=FAIL"; log "$id FAIL — $nombre"; fi; }

# M2: webhook de Jira (comentario de progreso → webhook → log del supervisor)
sleep 120
printf '%s' 'CA8 T0: corte aplicado en los 5 nodos OVH (simulacro casa apagada, SC-5299). Mediciones en curso.' | $JR progreso SC-5299 --rol devops --paso "CA8 T0" >/dev/null 2>&1
sleep 60
EV=$(kubectl -n paseo logs company-0 -c supervisor --since=4m 2>/dev/null | grep -m1 'SC-5299')
if [ -z "$EV" ]; then
  printf '%s' 'CA8: segundo disparo del webhook de prueba (SC-5299).' | $JR progreso SC-5299 --rol devops --paso "CA8 T0 rebote" >/dev/null 2>&1
  sleep 60
  EV=$(kubectl -n paseo logs company-0 -c supervisor --since=3m 2>/dev/null | grep -m1 'SC-5299')
fi
log "M2 evidencia: ${EV:-ninguna línea SC-5299 en el supervisor}"
[ -n "$EV" ]; med M2 "entra un webhook de Jira (log del supervisor)" $?

# M3: ArgoCD sincroniza un cambio de prueba (sync forzado no-op en blackbox-exporter)
sleep 660
kubectl -n argocd patch application blackbox-exporter --type=merge -p '{"operation":{"initiator":"cli","sync":{"revision":"HEAD","syncStrategy":{"hook":{}}}}}' >/dev/null 2>&1
OK3=1
for i in 1 2 3 4 5 6; do
  sleep 20
  ST=$(kubectl -n argocd get application blackbox-exporter -o jsonpath='{.status.operationState.phase}|{.status.operationState.finishedAt}' 2>/dev/null)
  PH=${ST%%|*}; FIN=${ST##*|}
  if [ "$PH" = "Succeeded" ] && [ "$FIN" \> "$T0_ISO" ]; then OK3=0; log "M3 evidencia: operationState=$ST"; break; fi
done
[ "$OK3" = "0" ]; med M3 "ArgoCD sincroniza un cambio de prueba (sync forzado en blackbox-exporter)" $?

# M4: analisis espera con la puerta cerrada sin reiniciarse
sleep 2100
AHORA_ANALISIS=$(kubectl -n analisis get pods --no-headers 2>/dev/null | awk '{print $1" "$3" "$4}' | head -1)
log "M4 evidencia: base=[$BASE_ANALISIS] ahora=[$AHORA_ANALISIS]"
[ "$AHORA_ANALISIS" = "$BASE_ANALISIS" ] && [ -n "$AHORA_ANALISIS" ]; med M4 "analisis sin reinicios ni sustituciones durante la hora" $?

# M1: el supervisor barre (BARRIDO_S=120; el intervalo incluye la duración del propio barrido)
MIN=$(( ($(date +%s) - T0) / 60 ))
BARR=$(kubectl -n paseo logs company-0 -c supervisor --since=${MIN}m 2>/dev/null | grep -c 'barrido:')
GAP=$(kubectl -n paseo logs company-0 -c supervisor --since=${MIN}m 2>/dev/null | grep 'barrido:' | awk '{split($1,t,":"); s=t[1]*3600+t[2]*60+t[3]; if(NR>1 && s-prev>max) max=s-prev; prev=s} END{print max+0}')
SUP_RESTART=$(kubectl -n paseo get pod company-0 -o jsonpath='{.status.containerStatuses[?(@.name=="supervisor")].restartCount}' 2>/dev/null)
log "M1 evidencia: $BARR barridos · intervalo máximo ${GAP}s · supervisor restarts $BASE_SUP_RESTART→$SUP_RESTART"
[ "$BARR" -ge 15 ] && [ "$SUP_RESTART" = "$BASE_SUP_RESTART" ]; med M1 "el supervisor barre en la ventana (≥15 barridos, sin reinicio)" $?

# M5: no se trabaja — capacidad 0, ninguna sesión nueva, fallback_alibaba apagado
vmq(){ curl -s --max-time 10 "$VM/api/v1/query" --data-urlencode "query=$1" | sed -n 's/.*"value":\[[0-9.]*,"\([0-9.eE+-]*\)"\].*/\1/p' | head -1; }
FB=$(vmq 'max_over_time(company_fallback_alibaba[60m])')
EJ=$(vmq 'max_over_time(company_llm_en_ejecucion[60m])')
pgrep -f 'tmux -L ses-' | sort > /tmp/ca8-tmux-now
NUEVAS=$(comm -13 /tmp/ca8-tmux-base /tmp/ca8-tmux-now | wc -l)
log "M5 evidencia: fallback_alibaba=${FB:-sin-serie} · llm_en_ejecucion=${EJ:-sin-serie} · sesiones tmux base=$BASE_TMUX nuevas=$NUEVAS"
{ [ -z "$FB" ] || [ "$FB" = "0" ]; } && { [ -z "$EJ" ] || [ "$EJ" = "0" ]; } && [ "$NUEVAS" = "0" ]; med M5 "no se trabaja: capacidad 0, ninguna sesión nueva, fallback_alibaba apagado" $?

# M6: 0 peticiones a la nube (SpendLogs en VM; shortcut: sin métricas por proveedor,
# se mide peticiones totales al proxy — 0 total implica 0 a la nube)
REQ=$(vmq "sum(increase(litellm_proxy_pre_call_total_requests_created[${MIN}m]))")
log "M6 evidencia: peticiones al proxy en la ventana=${REQ:-0} (SpendLogs VM; shortcut declarado)"
[ -z "$REQ" ] || [ "$REQ" = "0" ]; med M6 "0 peticiones a la nube en SpendLogs (VM, ventana $MIN min)" $?

# ---------- vuelta ---------- (tras el undo automático de los 60')
ESPERA=$(( T0 + 3780 - $(date +%s) ))
[ "$ESPERA" -gt 0 ] && sleep "$ESPERA"
log "Vuelta: comprobando que el temporizador de 60' retiró las reglas solo"
VUELTA_OK=1
for n in $NODOS; do
  c=$(reglas_ca8 "$n") || { VUELTA_OK=0; continue; }
  [ "$c" = "0" ] || VUELTA_OK=0
  log "  $n: reglas tras el undo automático=$c"
done
[ "$VUELTA_OK" = "1" ] && log "VUELTA OK: las reglas se retiraron solas en los 5 nodos" || log "VUELTA: borrado central necesario"
log "Borrado central (idempotente) + verificación"
for n in $NODOS; do retry_nodo "$n" wipe_nodo "$n" || log "  $n: sin verificación limpia"; done

# observación post-corte (no entra en las 6): nodos de casa y residente
sleep 180
CASA=$(kubectl get nodes --no-headers 2>/dev/null | awk '/nvidia-dgx|gx10-ec3d|dgx3| ubuntu /{print $1"="$2}' | tr '\n' ' ')
log "Post-vuelta: nodos de casa $CASA (esperado Ready; si NotReady aún, el tailnet tarda — no se toca nada)"

log "Resultado: $RESULTATS"
if [ "$N_OK" = "6" ]; then final "CA8: CUMPLE (6/6)"; else final "CA8: NO CUMPLE ($N_OK/6)"; fi
