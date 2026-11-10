"""INFRA-1284: the shared dashboard oauth2-proxy (`keycloak/oauth2-proxy`) must refresh the
session before the access token it passes on in `Authorization` expires.

Realm edani: accessTokenLifespan=300 s. With `cookie_refresh = "1h"` the dashboard backend
(DGX-807) got an expired JWT ~55 of every 60 min and answered 403 ExpiredSignatureError.
"""
import pathlib
import re
import unittest

import yaml


PROXY = pathlib.Path(__file__).resolve().parents[1] / "platform" / "keycloak-next" / "oauth2-proxy.yaml"
ACCESS_TOKEN_LIFESPAN_S = 300
SSO_SESSION_IDLE_TIMEOUT_S = 7 * 24 * 3600
_UNITS = {"s": 1, "m": 60, "h": 3600}


def _seconds(value):
    total = sum(int(n) * _UNITS[u] for n, u in re.findall(r"(\d+)([smh])", value.strip('"')))
    assert total, f"unparseable duration {value!r}"
    return total


class Oauth2ProxyRefreshContract(unittest.TestCase):
    def setUp(self):
        docs = [d for d in yaml.safe_load_all(PROXY.read_text()) if d]
        cm = next(d for d in docs if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "oauth2-proxy-config")
        self.cfg = {}
        for line in cm["data"]["oauth2_proxy.cfg"].splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                key, _, value = line.partition("=")
                self.cfg[key.strip()] = value.strip()

    def test_refresh_before_access_token_expires(self):
        self.assertEqual(self.cfg["pass_access_token"], "true")
        self.assertEqual(self.cfg["set_authorization_header"], "true")
        refresh = _seconds(self.cfg["cookie_refresh"])
        self.assertLess(refresh, ACCESS_TOKEN_LIFESPAN_S)
        self.assertLess(refresh, SSO_SESSION_IDLE_TIMEOUT_S)
        self.assertEqual(self.cfg["cookie_refresh"], '"4m"')


if __name__ == "__main__":
    unittest.main()
