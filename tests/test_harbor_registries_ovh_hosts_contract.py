"""INFRA-1099 (INFRA-1022 C1, ronda 2 · INFRA-1276) — el pin de /etc/hosts.

El espejo del registries.yaml apunta a https://harbor.e-dani.com, pero el DNS
del tailnet (MagicDNS -> AdGuard de casa) responde 192.168.50.240 (el Traefik
LAN de la casa) tambien por ese nombre: con la casa inaccesible el pull de una
imagen no cacheada cae en `dial tcp 192.168.50.240:443` (salida literal en la
nota de IT de INFRA-1276). El rol que aplica el registries (apply-registries)
debe fijar el destino del espejo al borde publico en /etc/hosts de los nodos
OVH, por las dos rutas de escritura del rol: la normal (become) y la del
contenedor docker de sauvage (sin sudo, INFRA-937).

Rojo contra el tronco sin el fix: group_vars no define el pin y las tareas no
gestionan /etc/hosts. Verde con el fix.
"""

from pathlib import Path
import ipaddress
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKER_TASKS = ROOT / "ansible/roles/k3s_worker/tasks/registries.yml"
CP_TASKS = ROOT / "ansible/roles/k3s_control_plane/tasks/registries.yml"
WORKER_TEMPLATE = ROOT / "ansible/roles/k3s_worker/templates/registries.yaml.j2"
CP_TEMPLATE = ROOT / "ansible/roles/k3s_control_plane/templates/registries.yaml.j2"
GROUP_VARS = ROOT / "ansible/group_vars/ovh_nodes.yml"
RUNBOOK = ROOT / "docs/runbook-harbor-registries-ovh.md"

PIN_MARKER = "INFRA-1099 harbor-publico"
HARBOR_NAME = "harbor.e-dani.com"
# La casa: traefik-lan en el x86. Cualquier pin que apuntase aqui reproduciria
# la laguna de C1 (INFRA-1276) y esta prohibido por contrato.
HOME_LAN_NET = ipaddress.ip_network("192.168.50.0/24")
# El tailnet (CGNAT 100.64.0.0/10): el pin es al borde PUBLICO (lo midio IT);
# fijar el nombre a una IP del tailnet seria otro mecanismo (split DNS), no
# el que pide INFRA-1276.
TAILNET_NET = ipaddress.ip_network("100.64.0.0/10")


class HarborRegistriesOvhHostsContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.group_vars = yaml.safe_load(GROUP_VARS.read_text(encoding="utf-8"))
        self.worker_tasks = WORKER_TASKS.read_text(encoding="utf-8")
        self.cp_tasks = CP_TASKS.read_text(encoding="utf-8")

    # --- el pin vive en group_vars del grupo ovh_nodes, no hardcodeado -----

    def test_group_vars_define_public_edge_pin(self) -> None:
        self.assertEqual(self.group_vars["harbor_public_hostname"], HARBOR_NAME)
        ips = self.group_vars["harbor_public_edge_ips"]
        self.assertIsInstance(ips, list)
        self.assertGreaterEqual(len(ips), 1)
        for raw in ips:
            ip = ipaddress.ip_address(raw)
            self.assertTrue(
                ip not in HOME_LAN_NET,
                f"{raw} es la red de casa: reproduciria la laguna de C1",
            )
            self.assertTrue(
                ip not in TAILNET_NET,
                f"{raw} es del tailnet: el pin debe ir al borde publico (INFRA-1276)",
            )
            self.assertTrue(ip.is_global, f"{raw} no es una IP publica")

    # --- ambas rutas de escritura gestionan /etc/hosts ---------------------

    def test_become_path_pins_hosts_with_blockinfile(self) -> None:
        for tasks in (self.worker_tasks, self.cp_tasks):
            self.assertIn("ansible.builtin.blockinfile", tasks)
            self.assertIn("/etc/hosts", tasks)
            self.assertIn(PIN_MARKER, tasks)
            self.assertIn("harbor_public_edge_ips", tasks)
            self.assertIn("harbor_registries_enabled", tasks)

    def test_sauvage_docker_path_pins_hosts(self) -> None:
        # ubuntu@sauvage no tiene sudo (INFRA-937): el pin debe escribirse por
        # la misma via docker que ya usa el registries, de forma idempotente.
        for tasks in (self.worker_tasks, self.cp_tasks):
            self.assertIn("registries_write_via_docker", tasks)
            self.assertIn("-v /etc/hosts:", tasks)
            self.assertIn("hosts-changed", tasks)
            self.assertIn("hosts-unchanged", tasks)

    def test_hosts_pin_does_not_restart_k3s(self) -> None:
        # containerd resuelve en cada pull: cambiar /etc/hosts no requiere
        # reiniciar k3s/k3s-agent (a diferencia del registries.yaml).
        for tasks in (self.worker_tasks, self.cp_tasks):
            hosts_block = tasks.split("blockinfile")[1] if "blockinfile" in tasks else ""
            self.assertNotIn("Restart k3s", hosts_block.split("- name:")[0])

    # --- el contrato de la ronda 1 sigue intacto ----------------------------

    def test_mirror_still_targets_public_edge_name(self) -> None:
        for template in (
            WORKER_TEMPLATE.read_text(encoding="utf-8"),
            CP_TEMPLATE.read_text(encoding="utf-8"),
        ):
            self.assertIn(f'"https://{HARBOR_NAME}"', template)

    # --- el runbook cuenta el pin y como re-verificarlo ----------------------

    def test_runbook_documents_the_pin(self) -> None:
        runbook = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("/etc/hosts", runbook)
        self.assertIn(PIN_MARKER, runbook)
        # la re-verificacion de las IPs del borde (Cloudflare puede rotarlas)
        self.assertIn("1.1.1.1", runbook)

    # --- el pin compone UNA linea por IP del borde, con saltos de linea reales ---

    def _pin_template(self, tasks_text: str) -> str:
        """Valor YAML-parseado de `harbor_hosts_pin_lines` (el `block` del blockinfile)."""
        found: list[str] = []

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "harbor_hosts_pin_lines" and isinstance(v, str):
                        found.append(v)
                    walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        for doc in yaml.safe_load_all(tasks_text):
            walk(doc)
        self.assertEqual(len(found), 1, "harbor_hosts_pin_lines debe definirse exactamente una vez")
        return found[0]

    def test_pin_compone_una_linea_por_ip_con_saltos_reales(self) -> None:
        """INFRA-1316 (#502): el bloque escribe una linea por IP del borde publico,
        separadas por saltos de linea REALES, con las dos IPs de group_vars.

        El bug (#498) componia el bloque con un escalar plegado (>-): Jinja no procesa
        escapes, asi que join('\\n') llegaba como backslash-n LITERAL y /etc/hosts
        recibia '\\' 'n' en vez de un salto de linea (verificado con od en atlantic).
        El fix (#502) es un escalar YAML entrecomillado doble: el parser de YAML
        convierte \\n en un salto REAL antes de que Jinja lo vea. Este test es rojo con
        el plegado (no habria chr(10) y quedaria backslash-n) y verde con el
        entrecomillado; es justo la composicion que IT midio destructivamente en
        INFRA-1316 (las dos lineas del pin presentes y efectivas en sauvage).

        No duplica test_group_vars_define_public_edge_pin: aquel valida que las IPs son
        publicas; este valida que las DOS se vierten como lineas separadas (la laguna
        que rompio C1 no era el valor de la IP sino que el bloque no se formaba).
        """
        ips = self.group_vars["harbor_public_edge_ips"]
        self.assertGreaterEqual(len(ips), 2, "el pin debe cubrir las dos IPs del borde de group_vars")
        for tasks in (self.worker_tasks, self.cp_tasks):
            bloque = self._pin_template(tasks)
            # separador REAL: el entrecomillado doble convirtio \n en chr(10)
            self.assertIn("\n", bloque,
                          "el join debe separar con salto de linea REAL (#502), no literal")
            self.assertNotIn("\\n", bloque,
                             "backslash-n literal: regresion al escalar plegado >- de #498 (INFRA-1316)")
            # una linea por IP: producto de las IPs del borde por el nombre, unidas por espacio
            self.assertIn("harbor_public_edge_ips", bloque)
            self.assertIn("harbor_public_hostname", bloque)
            self.assertIn("product", bloque)
            self.assertIn("join", bloque)


if __name__ == "__main__":
    unittest.main()
