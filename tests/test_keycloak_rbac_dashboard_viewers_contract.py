"""/dashboard-viewers: acceso de SOLO VER al panel (SC-4138, lección del acceso temporal de Jordi).

El proxy compartido del panel deja entrar a este grupo, pero no le abre ninguna escritura: los POST
del panel siguen exigiendo sesión (el contrato de middlewares lo fija
test_dgx_lan_sso_secretaria_escrituras_contract.py, con PyYAML en su job) y el backend pide
`/edani-admins` (guarda_cluster.py de dgx-infra). Aquí, sin yaml — el job `keycloak-rbac-contract`
no lo instala —, los dos bordes propios del grupo:

* `allowed_groups` del proxy = exactamente admins + operators + dashboard-viewers (la puerta de login);
* el grupo no aparece en ningún otro manifiesto (no puede acabar habilitando nada más).
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROXY = "platform/keycloak-next/oauth2-proxy.yaml"


def _allowed_groups():
    raw = (ROOT / PROXY).read_text(encoding="utf-8")
    m = re.search(r"^\s*allowed_groups\s*=\s*(\[.*\])", raw, re.MULTILINE)
    assert m, f"{PROXY}: no encuentro allowed_groups"
    return m.group(1)


class DashboardViewers(unittest.TestCase):
    def test_allowed_groups_del_proxy_incluye_el_grupo_de_lectura(self):
        self.assertEqual(_allowed_groups(),
                         '[ "/edani-admins", "/edani-operators", "/dashboard-viewers" ]')

    def test_el_grupo_no_habilita_nada_fuera_del_proxy(self):
        """Drift: /dashboard-viewers solo puede vivir en el cfg del proxy. Que aparezca en cualquier
        otro manifiesto (middlewares, whitelists, chains) significaría que alguien le dio un permiso más."""
        for path in sorted((ROOT / "networking").rglob("*.yaml")) + sorted((ROOT / "platform").rglob("*.yaml")):
            if path.relative_to(ROOT).as_posix() == PROXY:
                continue
            with self.subTest(path.relative_to(ROOT).as_posix()):
                self.assertNotIn("/dashboard-viewers", path.read_text(encoding="utf-8"),
                                 f"{path}: el grupo de solo ver aparece fuera del oauth2-proxy")


if __name__ == "__main__":
    unittest.main()
