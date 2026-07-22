from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ExternalDnsContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.values = yaml.safe_load(
            (ROOT / "networking/external-dns/values.yaml").read_text(
                encoding="utf-8"
            )
        )

    def test_lan_zone_is_served_by_the_existing_wildcard(self) -> None:
        self.assertIn("e-dani.com", self.values["domainFilters"])
        self.assertEqual(self.values["excludeDomains"], ["lan.e-dani.com"])
        self.assertEqual(
            self.values["extraArgs"],
            ["--default-targets=192.168.50.240"],
        )

    def test_dns_cleanup_stays_explicit(self) -> None:
        self.assertEqual(self.values["policy"], "upsert-only")
        self.assertEqual(self.values["txtOwnerId"], "k3s-x86-home")


if __name__ == "__main__":
    unittest.main()
