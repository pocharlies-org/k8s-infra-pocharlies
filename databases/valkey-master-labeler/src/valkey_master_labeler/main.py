"""Etiquetador de master valkey por eventos (SC-5880).

Sustituye las dos copias del bucle `sleep 20` + `kubectl exec valkey-cli
role` (databases/shared-valkey y skirmshop/labels-valkey). Fuentes de
verdad, todas eventos:

  * arranque: `SENTINEL get-master-addr-by-name` (lectura level-triggered);
  * pub/sub de Sentinel: canal `+switch-master`;
  * watch de Kubernetes sobre los pods del StatefulSet (un pod recreado
    nace sin la etiqueta y puede no haber ningún failover nunca).

Cada evento dispara la misma reconciliación completa (level-triggered, no
 deltas). No hay bucle de reloj: los únicos `sleep` son backoff de
 reconexión/reintento tras error, que es manejo de fallo, no sondeo.

Parametrizado por env: NAMESPACE, MASTER_NAME, SENTINEL_HOST,
SENTINEL_PORT, SENTINEL_PASSWORD (opcional), POD_SELECTOR.
"""

import logging
import os
import threading
import time

import redis
from kubernetes import client, config, watch

from valkey_master_labeler.decision import LABEL_KEY, LABEL_VALUE, plan_label_patches

log = logging.getLogger("valkey-master-labeler")

SWITCH_MASTER_CHANNEL = "+switch-master"
BACKOFF_START = 1.0
BACKOFF_MAX = 30.0


def load_config():
    def required(name):
        value = os.environ.get(name)
        if not value:
            raise SystemExit(f"{name} is required")
        return value

    return {
        "namespace": required("NAMESPACE"),
        "master_name": required("MASTER_NAME"),
        "sentinel_host": required("SENTINEL_HOST"),
        "sentinel_port": int(os.environ.get("SENTINEL_PORT", "26379")),
        "sentinel_password": os.environ.get("SENTINEL_PASSWORD") or None,
        "pod_selector": required("POD_SELECTOR"),
    }


def sentinel_client(cfg):
    return redis.Redis(
        host=cfg["sentinel_host"],
        port=cfg["sentinel_port"],
        password=cfg["sentinel_password"],
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


def get_master_addr(sentinel, master_name):
    reply = sentinel.execute_command("SENTINEL", "GET-MASTER-ADDR-BY-NAME", master_name)
    if not reply:
        return None
    return reply[0]


def current_pods(k8s, cfg):
    items = k8s.list_namespaced_pod(cfg["namespace"], label_selector=cfg["pod_selector"]).items
    return [
        {"name": p.metadata.name, "ip": p.status.pod_ip, "labels": p.metadata.labels or {}}
        for p in items
    ]


def reconcile(k8s, sentinel, cfg):
    """Reconciliación completa: releer el master de Sentinel y ajustar etiquetas."""
    master_addr = get_master_addr(sentinel, cfg["master_name"])
    pods = current_pods(k8s, cfg)
    for name, value in plan_label_patches(master_addr, pods):
        body = {"metadata": {"labels": {LABEL_KEY: value}}}
        k8s.patch_namespaced_pod(name, cfg["namespace"], body)
        if value == LABEL_VALUE:
            log.info("pod %s: ahora %s=%s (Sentinel: %s)", name, LABEL_KEY, value, master_addr)
        else:
            log.info("pod %s: etiqueta %s quitada (Sentinel: %s)", name, LABEL_KEY, master_addr)


def pubsub_loop(sentinel, cfg, trigger):
    """Hilo: SUBSCRIBE `+switch-master`. Cada mensaje dispara la reconciliación."""
    backoff = BACKOFF_START
    while True:
        pubsub = None
        try:
            pubsub = sentinel.pubsub()
            pubsub.subscribe(SWITCH_MASTER_CHANNEL)
            backoff = BACKOFF_START
            log.info("subscrito a %s en %s:%s", SWITCH_MASTER_CHANNEL,
                     cfg["sentinel_host"], cfg["sentinel_port"])
            for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = (message.get("data") or "").split()
                # "+switch-master <master> <old-ip> <old-port> <new-ip> <new-port>"
                if len(data) >= 5 and data[0] != cfg["master_name"]:
                    continue
                log.info("+switch-master: %s", message.get("data"))
                trigger()
        except Exception as exc:
            log.warning("pubsub de Sentinel caído (%s); reconecto en %.0fs", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:
                    pass


def watch_loop(k8s, cfg, trigger):
    """Hilo: watch de los pods del selector. Un pod recreado nace sin etiqueta."""
    backoff = BACKOFF_START
    while True:
        w = watch.Watch()
        try:
            for event in w.stream(
                k8s.list_namespaced_pod, cfg["namespace"], label_selector=cfg["pod_selector"]
            ):
                backoff = BACKOFF_START
                pod = event["object"]
                log.debug("evento %s sobre %s", event["type"], pod.metadata.name)
                trigger()
        except Exception as exc:
            # Incluye 410 Gone (resourceVersion viejo): se re-lista con un
            # Watch nuevo y se sigue; el reintento con backoff es error, no sondeo.
            log.warning("watch de pods caído (%s); re-listo en %.0fs", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config()
    config.load_incluster_config()
    k8s = client.CoreV1Api()
    sentinel = sentinel_client(cfg)

    event = threading.Event()

    def trigger():
        event.set()

    threading.Thread(target=pubsub_loop, args=(sentinel, cfg, trigger), daemon=True).start()
    threading.Thread(target=watch_loop, args=(k8s, cfg, trigger), daemon=True).start()

    log.info(
        "etiquetador iniciado: ns=%s master=%s sentinel=%s:%s selector=%s",
        cfg["namespace"], cfg["master_name"], cfg["sentinel_host"],
        cfg["sentinel_port"], cfg["pod_selector"],
    )
    backoff = BACKOFF_START
    while True:
        try:
            reconcile(k8s, sentinel, cfg)
            backoff = BACKOFF_START
        except Exception as exc:
            log.error("reconciliación fallida (%s); reintento en %.0fs", exc, backoff)
            event.wait(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX)
            event.set()
            continue
        # Sin reloj: dormido hasta que un evento (pubsub/watch) despierta.
        event.wait()


if __name__ == "__main__":
    main()
