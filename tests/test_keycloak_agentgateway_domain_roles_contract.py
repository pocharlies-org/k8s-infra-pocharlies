import os
import pathlib
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "keycloak-next"


class KeycloakAgentGatewayDomainRolesContractTest(unittest.TestCase):
    def test_exact_roles_are_created_but_not_assigned(self):
        script = (BASE / "scripts" / "agentgateway-domain-roles.sh").read_text()
        expected = {
            "synapse", "media", "picqer", "skirmshop-plugins", "shopify",
            "social", "workspace", "gsc", "offers",
        }
        for domain in expected:
            self.assertIn(f"agentgateway-write:{domain}", script)
        self.assertIn("ROLE_NAMES is immutable", script)
        self.assertIn('roles/${role}/users', script)
        self.assertIn('roles/${role}/groups', script)
        self.assertIn("must remain non-composite", script)
        self.assertIn('"assigned":false', script)
        self.assertNotIn("add-roles", script)
        self.assertNotIn("set -x", script)

    def test_reconciler_creates_exactly_nine_roles_without_assigning_them(self):
        script = BASE / "scripts" / "agentgateway-domain-roles.sh"
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = pathlib.Path(temporary_directory)
            kcadm = temporary / "kcadm.sh"
            log = temporary / "kcadm.log"
            kcadm.write_text(textwrap.dedent("""\
                #!/bin/sh
                printf '%s\\n' "$*" >>"${FAKE_KCADM_LOG}"
                if [ "$1 $2" = "config credentials" ]; then
                  exit 0
                fi
                if [ "$1" = "get" ]; then
                  case "$2" in
                    roles/*/users|roles/*/groups) exit 0 ;;
                    roles/*)
                      case " $* " in
                        *" --fields id "*) exit 1 ;;
                        *" --fields composite "*) printf 'false\\n'; exit 0 ;;
                      esac
                      ;;
                  esac
                fi
                [ "$1 $2" = "create roles" ] && exit 0
                exit 99
            """))
            kcadm.chmod(0o755)
            environment = os.environ.copy()
            environment.update({
                "KCADM": str(kcadm),
                "FAKE_KCADM_LOG": str(log),
                "KC_BOOTSTRAP_ADMIN_USERNAME": "test-admin",
                "KC_BOOTSTRAP_ADMIN_PASSWORD": "test-password",
            })

            result = subprocess.run(
                ["/bin/sh", str(script)],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            calls = log.read_text().splitlines()
            creations = [call for call in calls if call.startswith("create roles ")]
            self.assertEqual(9, len(creations))
            self.assertIn('"roles":9,"created":9,"assigned":false', result.stdout)
            self.assertFalse(any("add-roles" in call for call in calls))

    def test_job_is_postsync_nonroot_pinned_and_network_limited(self):
        manifest = (BASE / "agentgateway-domain-roles-job.yaml").read_text()
        self.assertIn("argocd.argoproj.io/hook: PostSync", manifest)
        self.assertIn("activeDeadlineSeconds: 900", manifest)
        self.assertIn("automountServiceAccountToken: false", manifest)
        self.assertIn("runAsNonRoot: true", manifest)
        self.assertIn("readOnlyRootFilesystem: true", manifest)
        self.assertIn('capabilities: { drop: ["ALL"] }', manifest)
        self.assertIn("quay.io/keycloak/keycloak:26.6.2@sha256:", manifest)
        self.assertIn("app.kubernetes.io/component: agentgateway-domain-roles", manifest)
        self.assertNotIn("0.0.0.0/0", manifest)

    def test_kustomize_owns_job_and_script(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("agentgateway-domain-roles-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-domain-roles.sh", kustomization)


if __name__ == "__main__":
    unittest.main()
