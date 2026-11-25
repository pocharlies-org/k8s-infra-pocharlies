"""Decisión pura del etiquetador de master valkey (SC-5880).

Sin reloj y sin I/O: dada la dirección que Sentinel reporta como master y
la lista de pods, decide qué pod lleva `valkey-role=master` y a cuáles se
les quita la etiqueta. Level-triggered: el llamador re-ejecuta esta
decisión ante cada evento (arranque, `+switch-master`, watch de pods).
"""

LABEL_KEY = "valkey-role"
LABEL_VALUE = "master"


def pod_matches_master_addr(name, ip, master_addr):
    """True si este pod es el que Sentinel reporta como master.

    Sentinel corre con `resolve-hostnames`/`announce-hostnames yes`, así que
    `get-master-addr-by-name` responde con el FQDN del pod
    (`<pod>.<headless>.<ns>.svc.cluster.local`); según configuración puede
    responder con la IP desnuda. Se casa por nombre de pod (FQDN → primera
    etiqueta) o por IP.
    """
    if not master_addr:
        return False
    first_label = master_addr.split(".")[0]
    return name in (master_addr, first_label) or (ip is not None and ip == master_addr)


def plan_label_patches(master_addr, pods):
    """Parches de etiqueta necesarios para que la realidad iguale a Sentinel.

    `pods`: iterable de dicts con claves `name`, `ip` y `labels`.
    Devuelve una lista de `(nombre_pod, valor)` donde `valor` es
    `LABEL_VALUE` (poner `valkey-role=master`) o `None` (quitar la
    etiqueta). Lista vacía cuando no hay nada que cambiar — incluido el
    caso de que ningún pod case con la dirección reportada: una respuesta
    de Sentinel que no corresponde a ningún pod (p. ej. un pod aún no
    creado tras un failover) nunca debe dejar sin etiqueta a todos, porque
    eso dejaría los Services `*-master` sin endpoints.
    """
    patches = []
    matched = False
    for pod in pods:
        labels = pod.get("labels") or {}
        if pod_matches_master_addr(pod["name"], pod.get("ip"), master_addr):
            matched = True
            if labels.get(LABEL_KEY) != LABEL_VALUE:
                patches.append((pod["name"], LABEL_VALUE))
        elif labels.get(LABEL_KEY) is not None:
            patches.append((pod["name"], None))
    if not matched:
        return []
    return patches
