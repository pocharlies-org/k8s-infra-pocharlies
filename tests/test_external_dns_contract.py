from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ExternalDnsContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.values_text = (
            ROOT / "networking/external-dns/values.yaml"
        ).read_text(
            encoding="utf-8"
        )

    def test_lan_zone_is_served_by_the_existing_wildcard(self) -> None:
        self.assertRegex(
            self.values_text,
            re.compile(r"^domainFilters:\n(?:  - .+\n)*  - e-dani\.com$", re.MULTILINE),
        )
        self.assertRegex(
            self.values_text,
            re.compile(
                r"^excludeDomains:\n  - lan\.e-dani\.com$",
                re.MULTILINE,
            ),
        )
        self.assertIn(
            "  - --default-targets=192.168.50.240",
            self.values_text,
        )

    def test_dns_cleanup_stays_explicit(self) -> None:
        self.assertRegex(
            self.values_text,
            re.compile(r"^policy: upsert-only(?:\s|$)", re.MULTILINE),
        )
        self.assertRegex(
            self.values_text,
            re.compile(r"^txtOwnerId: k3s-x86-home$", re.MULTILINE),
        )


if __name__ == "__main__":
    unittest.main()
