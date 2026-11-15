"""SC-3063: chequeo periódico de Orphan CR de réplica (replica-data) de Longhorn.

Los Orphan CR de dato huérfano se recrean con cada flap de nodo: Longhorn borra el CR
mientras el nodo está down (DataCleanable=False -> el finalizer NO toca el dato) y al
volver el nodo la detección lo vuelve a crear. El dato se acumula y saca al disco del
umbral de scheduling (keep-causa deployment-degraded:47658437cd, SC-2611/SC-1615).

Este job, cada hora:
  1. comprueba que ningún Replica CR vivo referencia el DataName de cada huérfano;
  2. purga vía oficial (borra el Orphan CR -> el finalizer de longhorn-manager borra el
     dato en disco solo si el nodo está arriba y el disco es válido) los más antiguos
     que GRACE_SECONDS;
  3. avisa: empuja a VictoriaMetrics la cuenta de huérfanos que NO ha podido purgar
     (alerta LonghornOrphanReplicasStale) y su propio sello de ejecución (alerta
     LonghornOrphanWatchNotRunning si el job deja de correr).
"""
import datetime
import json
import os
import subprocess
import urllib.request

GRACE = int(os.environ.get("GRACE_SECONDS", "3600"))
VM = os.environ.get("VM_PUSH_URL", "").rstrip("/")
NS = "longhorn-system"


def kc(*args):
    r = subprocess.run(["kubectl", "-n", NS, *args], capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise SystemExit("kubectl %s -> %s" % (" ".join(args), r.stderr.strip()))
    return r.stdout


now = datetime.datetime.now(datetime.timezone.utc)
orphans = json.loads(kc("get", "orphans.longhorn.io", "-o", "json"))["items"]
replicas = {i["metadata"]["name"] for i in json.loads(kc("get", "replicas.longhorn.io", "-o", "json"))["items"]}
# Sin réplicas vivas es más probable un fallo de lectura que un clúster vacío: no se borra nada.
if not replicas and orphans:
    raise SystemExit("0 réplicas leídas con huérfanos presentes: no se toca nada")

stale_by_node = {}
referenced = 0
purged = []
for o in orphans:
    if o["spec"].get("orphanType") != "replica":
        continue
    if not o["metadata"].get("deletionTimestamp"):
        created = datetime.datetime.fromisoformat(o["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
        if (now - created).total_seconds() < GRACE:
            continue
        name = o["metadata"]["name"]
        data_name = o["spec"]["parameters"].get("DataName", "")
        if data_name in replicas:
            # Un CR vivo referencia el dato: Longhorn lo está usando (reconstrucción en
            # vuelo). No se borra; se cuenta para la alerta.
            referenced += 1
            print("REFERENCIADO (no se toca):", name, data_name)
            continue
        kc("delete", "orphans.longhorn.io", name, "--wait=false")
        purged.append((name, o["spec"].get("nodeID", "?"), data_name))

# Los que siguen aquí tras el barrido son los que el job no ha podido purgar.
still = json.loads(kc("get", "orphans.longhorn.io", "-o", "json"))["items"]
for o in still:
    if o["spec"].get("orphanType") != "replica":
        continue
    created = datetime.datetime.fromisoformat(o["metadata"]["creationTimestamp"].replace("Z", "+00:00"))
    if (now - created).total_seconds() >= GRACE:
        stale_by_node[o["spec"].get("nodeID", "?")] = stale_by_node.get(o["spec"].get("nodeID", "?"), 0) + 1

print("orphan-watch: %d purgados, %d stale (>%ss), %d referenciados" % (len(purged), sum(stale_by_node.values()), GRACE, referenced))
for n, node, dn in purged:
    print("  PURGADO", node, dn)

if VM:
    lines = ["longhorn_orphan_watch_last_success_timestamp %d" % int(now.timestamp())]
    for node, count in stale_by_node.items():
        lines.append('longhorn_orphan_replica_data{node="%s"} %d' % (node, count))
    if referenced:
        lines.append("longhorn_orphan_replica_data_referenced %d" % referenced)
    body = "\n".join(lines) + "\n"
    req = urllib.request.Request(VM + "/api/v1/import/prometheus", data=body.encode(),
                                 headers={"Content-Type": "text/plain"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp.read()
    print("métricas empujadas a", VM)
