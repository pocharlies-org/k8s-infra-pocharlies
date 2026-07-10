import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"


class OpenClawReadonlyIdentityContractTest(unittest.TestCase):
    def test_clients_are_dedicated_fail_closed_and_never_log_credentials(self):
        script = (BASE / "scripts" / "openclaw-readonly-clients.sh").read_text()
        self.assertIn('UI_CLIENT_ID="${UI_CLIENT_ID:-openclaw-readonly-ui}"', script)
        self.assertIn('filter_mapper_id "${mapper_name}"', script)
        self.assertNotIn("awk -F", script)
        self.assertIn(
            'AGENTGATEWAY_CLIENT_ID="${AGENTGATEWAY_CLIENT_ID:-openclaw-readonly-agentgateway}"',
            script,
        )
        self.assertIn('OPERATOR_EMAIL="${OPERATOR_EMAIL:-info@e-dani.com}"', script)
        self.assertIn('FORBIDDEN_REALM_ROLE="${FORBIDDEN_REALM_ROLE:-agentgateway-write}"', script)
        self.assertIn("standardFlowEnabled=true", script)
        self.assertIn("serviceAccountsEnabled=false", script)
        self.assertIn("standardFlowEnabled=false", script)
        self.assertIn("serviceAccountsEnabled=true", script)
        self.assertGreaterEqual(script.count("fullScopeAllowed=false"), 4)
        self.assertIn("oidc-group-membership-mapper", script)
        self.assertIn("oidc-audience-mapper", script)
        self.assertIn('config.\\"included.custom.audience\\"', script)
        self.assertIn("assert_no_forbidden_role", script)
        self.assertIn("verify_minted_claims", script)
        self.assertIn("mcp.lan.e-dani.com", script)
        self.assertIn("MODE", script)
        self.assertIn("rollback)", script)
        self.assertNotIn("set -x", script)
        self.assertNotIn('echo "${token}"', script)
        self.assertNotIn('echo "${OPENCLAW_READONLY_UI_CLIENT_SECRET}"', script)
        self.assertNotIn('echo "${OPENCLAW_READONLY_AGENTGATEWAY_CLIENT_SECRET}"', script)

    def test_external_secrets_and_postsync_job_are_least_privilege(self):
        manifest = (BASE / "openclaw-readonly-clients.yaml").read_text()
        self.assertEqual(manifest.count("kind: ExternalSecret"), 2)
        self.assertIn("name: openclaw-readonly-ui-secrets", manifest)
        self.assertIn("name: openclaw-readonly-agentgateway-bootstrap", manifest)
        self.assertEqual(manifest.count("key: keycloak-next/openclaw-readonly"), 3)
        self.assertNotIn("key: secret/keycloak-next/openclaw-readonly", manifest)
        self.assertIn("property: ui_client_secret", manifest)
        self.assertIn("property: cookie_secret", manifest)
        self.assertIn("property: agentgateway_client_secret", manifest)
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("argocd.argoproj.io/sync-wave: \"21\"", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("node-pool: ks5-nvme", manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertNotIn("value: agentgateway-write\n            - name: OPENCLAW", manifest)

    def test_oauth_proxy_allows_only_info_and_forwards_no_bearer(self):
        manifest = (BASE / "oauth2-proxy-openclaw-readonly.yaml").read_text()
        self.assertIn("allowed-emails: |\n    info@e-dani.com", manifest)
        self.assertIn(
            'authenticated_emails_file = "/etc/oauth2-proxy/allowed-emails"', manifest
        )
        self.assertNotIn("email_domains =", manifest)
        self.assertIn('pass_access_token = false', manifest)
        self.assertIn('set_authorization_header = false', manifest)
        self.assertIn("authResponseHeaders:\n      - X-Auth-Request-Email\n      - X-Auth-Request-Groups", manifest)
        self.assertNotIn("authResponseHeaders:\n      - Authorization", manifest)
        self.assertIn("name: sso-openclaw-readonly-chain", manifest)
        self.assertIn("name: oauth2-proxy-openclaw-readonly", manifest)
        self.assertIn("replicas: 2", manifest)
        self.assertIn("minAvailable: 1", manifest)
        self.assertIn("preferredDuringSchedulingIgnoredDuringExecution", manifest)
        self.assertIn("topologyKey: kubernetes.io/hostname", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("node-pool: ks5-nvme", manifest)
        self.assertIn("oauth2-proxy:v7.15.2@sha256:", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn("cidr: 100.107.21.89/32", manifest)
        self.assertNotIn("cidr: 10.42.0.0/24", manifest)

    def test_kustomize_wires_reconciler_but_excludes_manual_rollback(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        rollback = (BASE / "manual" / "openclaw-readonly-clients-rollback-job.yaml").read_text()
        self.assertIn("oauth2-proxy-openclaw-readonly.yaml", kustomization)
        self.assertIn("openclaw-readonly-clients.yaml", kustomization)
        self.assertIn("scripts/openclaw-readonly-clients.sh", kustomization)
        self.assertNotIn("manual/openclaw-readonly-clients-rollback-job.yaml", kustomization)
        self.assertIn("value: rollback", rollback)
        self.assertIn("automountServiceAccountToken: false", rollback)
        self.assertIn("node-pool: ks5-nvme", rollback)
        self.assertNotIn("OPENCLAW_READONLY_UI_CLIENT_SECRET", rollback)
        self.assertNotIn("OPENCLAW_READONLY_AGENTGATEWAY_CLIENT_SECRET", rollback)
        self.assertNotIn("openclaw-readonly-ui-secrets", rollback)
        self.assertNotIn("openclaw-readonly-agentgateway-bootstrap", rollback)

    def test_rollback_deletes_exact_clients_without_app_secrets_or_operator_lookup(self):
        script = BASE / "scripts" / "openclaw-readonly-clients.sh"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            ui_marker = tmp_path / "ui-present"
            agentgateway_marker = tmp_path / "agentgateway-present"
            ui_marker.touch()
            agentgateway_marker.touch()
            fake_kcadm = tmp_path / "kcadm.sh"
            fake_kcadm.write_text(
                textwrap.dedent(
                    """\
                    #!/bin/sh
                    command="$1"
                    shift
                    case "$command" in
                      config)
                        exit 0
                        ;;
                      get)
                        endpoint="$1"
                        shift
                        [ "$endpoint" = clients ] || {
                          echo "unexpected lookup: $endpoint" >&2
                          exit 73
                        }
                        query=""
                        for argument in "$@"; do
                          case "$argument" in
                            clientId=*) query="$argument" ;;
                          esac
                        done
                        case "$query" in
                          clientId=openclaw-readonly-ui)
                            [ -e "$FAKE_UI_MARKER" ] && printf '%s\n' ui-uuid
                            ;;
                          clientId=openclaw-readonly-agentgateway)
                            [ -e "$FAKE_AGENTGATEWAY_MARKER" ] && printf '%s\n' agentgateway-uuid
                            ;;
                          *)
                            echo "unexpected client query: $query" >&2
                            exit 74
                            ;;
                        esac
                        ;;
                      delete)
                        case "$1" in
                          clients/ui-uuid) rm -f "$FAKE_UI_MARKER" ;;
                          clients/agentgateway-uuid) rm -f "$FAKE_AGENTGATEWAY_MARKER" ;;
                          *) echo "unexpected delete: $1" >&2; exit 75 ;;
                        esac
                        ;;
                      *)
                        echo "unexpected command: $command" >&2
                        exit 76
                        ;;
                    esac
                    """
                )
            )
            fake_kcadm.chmod(0o755)
            env = os.environ.copy()
            env.update(
                {
                    "MODE": "rollback",
                    "KCADM": str(fake_kcadm),
                    "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                    "KC_BOOTSTRAP_ADMIN_PASSWORD": "not-a-real-secret",
                    "FAKE_UI_MARKER": str(ui_marker),
                    "FAKE_AGENTGATEWAY_MARKER": str(agentgateway_marker),
                }
            )
            env.pop("OPENCLAW_READONLY_UI_CLIENT_SECRET", None)
            env.pop("OPENCLAW_READONLY_AGENTGATEWAY_CLIENT_SECRET", None)
            result = subprocess.run(
                ["/bin/sh", str(script)],
                check=True,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertIn('"present":false', result.stdout)
            self.assertFalse(ui_marker.exists())
            self.assertFalse(agentgateway_marker.exists())

    @unittest.skipUnless(shutil.which("kubectl"), "kubectl is not installed")
    def test_keycloak_kustomization_builds(self):
        result = subprocess.run(
            ["kubectl", "kustomize", str(BASE)],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("keycloak-openclaw-readonly-clients", result.stdout)
        self.assertIn("oauth2-proxy-openclaw-readonly", result.stdout)


if __name__ == "__main__":
    unittest.main()
