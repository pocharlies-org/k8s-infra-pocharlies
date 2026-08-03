from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_documents(relative_path: str) -> list[dict]:
    return [
        document
        for document in yaml.safe_load_all(
            (ROOT / relative_path).read_text(encoding="utf-8")
        )
        if document
    ]


def find_document(
    documents: list[dict], kind: str, name: str
) -> dict:
    for document in documents:
        if (
            document.get("kind") == kind
            and document.get("metadata", {}).get("name") == name
        ):
            return document
    raise AssertionError(f"{kind}/{name} not found")


class SauvageBotContractTest(unittest.TestCase):
    def test_dashboard_stays_dry_run_and_uses_ornith(self) -> None:
        documents = load_documents("kubernetes/apps/sauvage-bot/app.yaml")
        config = find_document(
            documents, "ConfigMap", "sauvage-bot-config"
        )["data"]
        deployment = find_document(
            documents, "Deployment", "sauvage-bot"
        )
        container = deployment["spec"]["template"]["spec"]["containers"][0]

        self.assertEqual(config["DRY"], "true")
        self.assertEqual(config["COMMUNITY_APPLY_ACTIONS"], "false")
        self.assertEqual(config["FILES_SAMPLES"], "/srv/data")
        self.assertEqual(config["SERVER_AUTH"], "")
        self.assertNotIn("SERVER_FORWARD_AUTH_EMAILS", config)
        self.assertEqual(config["OPENAI_MODEL"], "ornith-1.0")
        self.assertEqual(config["TELEGRAM_GROUP"], "-1003672565710")
        self.assertEqual(config["TELEGRAM_GROUPS"], "-1003672565710")
        self.assertEqual(config["COMMUNITY_CHAT_ID"], "-1003672565710")
        self.assertNotIn("COMMUNITY_PRIVATE_CONSENT_TERMS", config)
        self.assertEqual(
            config["COMMUNITY_DASHBOARD_URL"],
            "https://sauvage-bot.e-dani.com",
        )
        self.assertEqual(
            container["image"],
            "ghcr.io/pocharlies/shield@sha256:"
            "f66334f0824f2c14b4766540ac702b0044a127fdc55a696a92ea3b1ddeae34cd",
        )
        self.assertNotIn("TELEGRAM_TOKEN", config)
        self.assertEqual(deployment["spec"]["replicas"], 1)
        self.assertEqual(deployment["spec"]["strategy"]["type"], "Recreate")
        self.assertEqual(
            container["startupProbe"],
            {
                "httpGet": {"path": "/readyz", "port": "probes"},
                "periodSeconds": 5,
                "timeoutSeconds": 3,
                "failureThreshold": 36,
            },
        )
        telegram_token = next(
            variable
            for variable in container.get("env", [])
            if variable["name"] == "TELEGRAM_TOKEN"
        )
        self.assertEqual(
            telegram_token["valueFrom"]["secretKeyRef"],
            {"name": "sauvage-bot-runtime", "key": "TELEGRAM_TOKEN"},
        )
        auth_hash = next(
            variable
            for variable in container.get("env", [])
            if variable["name"] == "SERVER_AUTH_HASH"
        )
        self.assertEqual(
            auth_hash["valueFrom"]["secretKeyRef"],
            {"name": "sauvage-bot-runtime", "key": "SERVER_AUTH_HASH"},
        )

    def test_runtime_secret_contains_only_required_credentials(self) -> None:
        runtime_secret = yaml.safe_load(
            (
                ROOT / "kubernetes/apps/sauvage-bot/secrets.yaml"
            ).read_text(encoding="utf-8")
        )

        self.assertEqual(
            {
                item["secretKey"]
                for item in runtime_secret["spec"]["data"]
            },
            {
                "DB_USER",
                "DB_PASSWORD",
                "OPENAI_TOKEN",
                "TELEGRAM_TOKEN",
                "SERVER_AUTH_HASH",
                "SAUVAGE_INTERNAL_TOKEN",
            },
        )
        self.assertTrue(
            all(
                item["remoteRef"]["key"] == "sauvage-bot"
                for item in runtime_secret["spec"]["data"]
            )
        )

    def test_database_secret_triggers_cnpg_password_reload(self) -> None:
        database_secret = find_document(
            load_documents(
                "databases/postgres-shared/app-credentials.yaml"
            ),
            "ExternalSecret",
            "sauvage-bot-db-credentials",
        )

        self.assertEqual(
            database_secret["spec"]["target"]["template"]["metadata"][
                "labels"
            ]["cnpg.io/reload"],
            "true",
        )

    def test_public_and_lan_routes_pass_basic_auth_to_the_app(self) -> None:
        cases = (
            (
                "networking/traefik-edge/sauvage-bot-public.yaml",
                "edge-sauvage-bot-public",
                "sauvage-bot.e-dani.com",
            ),
            (
                "networking/traefik-lan/sauvage-bot-lan.yaml",
                "lan-sauvage-bot",
                "sauvage-bot.lan.e-dani.com",
            ),
        )

        for path, route_name, hostname in cases:
            with self.subTest(hostname=hostname):
                documents = load_documents(path)
                route = find_document(
                    documents, "IngressRoute", route_name
                )
                rule = route["spec"]["routes"][0]
                self.assertEqual(rule["match"], f"Host(`{hostname}`)")
                self.assertEqual(
                    rule["middlewares"],
                    [{"name": "sauvage-bot-strip-auth-headers"}],
                )
                middleware = find_document(
                    documents, "Middleware", "sauvage-bot-strip-auth-headers"
                )
                stripped_headers = middleware["spec"]["headers"][
                    "customRequestHeaders"
                ]
                self.assertNotIn("Authorization", stripped_headers)
                self.assertEqual(stripped_headers["X-Auth-Request-Email"], "")
                if hostname.endswith(".lan.e-dani.com"):
                    self.assertNotIn("ingressClassName", route["spec"])
                else:
                    self.assertEqual(
                        route["spec"]["ingressClassName"],
                        "traefik-edge",
                    )

        public_route = find_document(
            load_documents(
                "networking/traefik-edge/sauvage-bot-public.yaml"
            ),
            "IngressRoute",
            "edge-sauvage-bot-public",
        )
        annotations = public_route["metadata"]["annotations"]
        self.assertEqual(
            annotations["external-dns.alpha.kubernetes.io/hostname"],
            "sauvage-bot.e-dani.com",
        )
        self.assertEqual(
            annotations[
                "external-dns.alpha.kubernetes.io/cloudflare-proxied"
            ],
            "true",
        )

    def test_only_traefik_can_reach_the_dashboard(self) -> None:
        documents = load_documents(
            "kubernetes/apps/sauvage-bot/networkpolicy.yaml"
        )
        allow_policy = find_document(
            documents, "NetworkPolicy", "sauvage-bot-allow-traefik"
        )
        ingress = allow_policy["spec"]["ingress"]

        self.assertEqual(len(ingress), 1)
        self.assertEqual(
            {
                peer["namespaceSelector"]["matchLabels"][
                    "kubernetes.io/metadata.name"
                ]
                for peer in ingress[0]["from"]
                if "namespaceSelector" in peer
            },
            {"traefik-edge", "traefik-lan", "agentgateway"},
        )
        self.assertEqual(
            {
                peer["ipBlock"]["cidr"]
                for peer in ingress[0]["from"]
                if "ipBlock" in peer
            },
            {
                "100.107.21.89/32",
                "100.71.117.127/32",
                "100.75.189.75/32",
                "100.109.183.9/32",
                "10.42.3.0/32",
                "10.42.4.0/32",
                "10.42.5.0/32",
                "10.42.6.0/32",
            },
        )
        self.assertEqual(
            ingress[0]["ports"],
            [{"protocol": "TCP", "port": 8080}],
        )

    def test_database_role_and_database_are_managed(self) -> None:
        cluster = yaml.safe_load(
            (
                ROOT / "databases/postgres-shared/cluster.yaml"
            ).read_text(encoding="utf-8")
        )
        role = next(
            role
            for role in cluster["spec"]["managed"]["roles"]
            if role["name"] == "sauvage_bot"
        )
        database = find_document(
            load_documents(
                "databases/postgres-shared/app-databases.yaml"
            ),
            "Database",
            "sauvage-bot",
        )

        self.assertTrue(role["login"])
        self.assertEqual(
            role["passwordSecret"]["name"],
            "sauvage-bot-db-credentials",
        )
        self.assertEqual(database["spec"]["name"], "sauvage_bot")
        self.assertEqual(database["spec"]["owner"], "sauvage_bot")

    def test_root_kustomization_includes_every_sauvage_resource(self) -> None:
        root = yaml.safe_load(
            (ROOT / "kustomization.yaml").read_text(encoding="utf-8")
        )

        self.assertTrue(
            {
                "kubernetes/apps/sauvage-bot",
                "networking/traefik-edge/sauvage-bot-public.yaml",
                "networking/traefik-lan/sauvage-bot-lan.yaml",
            }.issubset(set(root["resources"]))
        )


if __name__ == "__main__":
    unittest.main()
