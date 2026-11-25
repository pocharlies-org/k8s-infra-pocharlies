"""SC-5880: el bucle de main no gira en caliente y el pubsub no se queda sordo.

Lo que security midió (rechazo de #553): `event.wait()` sin `clear()` reconciliaba
sin pausa tras el primer evento, y `socket_timeout=5` cortaba `listen()` en reposo.
"""
import sys
import threading
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "databases" / "valkey-master-labeler" / "src"))

# Sin red ni clúster: dobles mínimos de los paquetes que main importa.
# (un directorio `kubernetes/` del repo se importa como namespace package vacío).
try:
    import redis  # noqa: F401
except ImportError:
    sys.modules["redis"] = types.SimpleNamespace(Redis=object)
try:
    from kubernetes import client, config, watch  # noqa: F401
except ImportError:
    _k = types.SimpleNamespace()
    sys.modules["kubernetes"] = types.SimpleNamespace(client=_k, config=_k, watch=_k)

from valkey_master_labeler import main as m  # noqa: E402


class ServeTest(unittest.TestCase):
    def _run(self, event, fn):
        threading.Thread(target=m.serve, args=(event, fn), daemon=True).start()

    def test_una_pasada_al_arrancar_y_una_por_evento(self):
        event, calls = threading.Event(), []
        self._run(event, lambda: calls.append(1))
        time.sleep(0.2)
        self.assertEqual(len(calls), 1)          # arranque, y luego duerme
        event.set()
        time.sleep(0.2)
        self.assertEqual(len(calls), 2)          # un evento → una pasada, no un bucle caliente
        time.sleep(0.3)
        self.assertEqual(len(calls), 2)

    def test_evento_durante_la_pasada_provoca_otra(self):
        event, calls = threading.Event(), []

        def slow():
            calls.append(1)
            if len(calls) == 1:
                event.set()                      # llega mientras se reconcilia
        self._run(event, slow)
        time.sleep(0.3)
        self.assertEqual(len(calls), 2)


class PubsubTest(unittest.TestCase):
    def test_resuscribir_dispara_reconciliacion_y_mensaje_tambien(self):
        triggers = []

        class _PS:
            def subscribe(self, ch): pass
            def close(self): pass
            def listen(self):
                yield {"type": "subscribe", "data": 1}
                yield {"type": "message", "data": "shared-cache-master 10.0.0.1 6379 10.0.0.2 6379"}
                yield {"type": "message", "data": "otro-master 10.0.0.1 6379 10.0.0.2 6379"}
                raise KeyboardInterrupt          # sale del bucle infinito del test

        class _Client:
            def pubsub(self): return _PS()

        with self.assertRaises(KeyboardInterrupt):
            m.pubsub_loop(_Client(), {"master_name": "shared-cache-master", "sentinel_host": "s",
                                       "sentinel_port": 26379}, lambda: triggers.append(1))
        self.assertEqual(len(triggers), 2)       # al suscribirse + el +switch-master propio

    def test_cliente_de_pubsub_sin_socket_timeout(self):
        seen = {}

        class _Redis:
            def __init__(self, **kw): seen.update(kw)
        orig = m.redis.Redis
        m.redis.Redis = _Redis
        try:
            m.sentinel_client({"sentinel_host": "s", "sentinel_port": 1, "sentinel_password": None},
                              socket_timeout=None)
        finally:
            m.redis.Redis = orig
        self.assertIsNone(seen["socket_timeout"])
        self.assertTrue(seen["socket_keepalive"])


if __name__ == "__main__":
    unittest.main()
