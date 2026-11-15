import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _route():
    path = ROOT / "networking/traefik-edge/brain-shopify-webhooks-public.yaml"
    return next(
        item
        for item in yaml.safe_load_all(path.open(encoding="utf-8"))
        if item and item.get("kind") == "IngressRoute"
    )


class BrainShopifyWebhooksEdgeContract(unittest.TestCase):
    def test_es_ruta_de_maquina_sin_sso(self):
        # SKIRM-212: Shopify firma los webhooks (HMAC); SSO cortaría la entrega.
        # Fijado aquí para que un futuro cambio de SSO no vuelva a romper la ingesta.
        route = _route()
        rule = route["spec"]["routes"][0]
        self.assertEqual(
            rule["match"], "Host(`brain-k8s.e-dani.com`) && PathPrefix(`/webhooks/shopify`)"
        )
        self.assertEqual(rule["priority"], 2500)
        self.assertNotIn("middlewares", rule)
        service = rule["services"][0]
        self.assertEqual(
            (service["name"], service["namespace"], service["port"]),
            ("skirmshop-brain", "skirmshop-brain-prod", 80),
        )


if __name__ == "__main__":
    unittest.main()
