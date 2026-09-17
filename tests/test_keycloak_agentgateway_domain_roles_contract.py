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
        self.assertIn("ALLOWED_SERVICE_ACCOUNTS is immutable", script)
        self.assertIn(
            'EXPECTED_ALLOWED_SERVICE_ACCOUNTS="agentgateway-write:media=service-account-chat-agentgateway"',
            script,
        )
        self.assertIn('roles/${role}/users', script)
        self.assertIn('roles/${role}/groups', script)
        self.assertIn("must remain non-composite", script)
        self.assertIn('"human_assigned":false', script)
        self.assertNotIn("add-roles", script)
        self.assertNotIn("set -x", script)

    @staticmethod
    def _run_reconciler(role_members=None, env_overrides=None):
        """Run the reconciler against a fake kcadm.

        ``role_members`` maps ``roles/<name>/users`` to the usernames Keycloak
        would report as direct holders; every role is reported missing (so it
        gets created) and non-composite, and no role has groups.
        """
        script = BASE / "scripts" / "agentgateway-domain-roles.sh"
        members = "\n".join(
            f'                    {endpoint}) printf \'{users}\\n\'; exit 0 ;;'
            for endpoint, users in (role_members or {}).items()
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = pathlib.Path(temporary_directory)
            kcadm = temporary / "kcadm.sh"
            log = temporary / "kcadm.log"
            log.write_text("")
            kcadm.write_text(textwrap.dedent(f"""\
                #!/bin/sh
                printf '%s\\n' "$*" >>"${{FAKE_KCADM_LOG}}"
                if [ "$1 $2" = "config credentials" ]; then
                  exit 0
                fi
                if [ "$1" = "get" ]; then
                  case "$2" in
{members}
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
            environment.update(env_overrides or {})

            result = subprocess.run(
                ["/bin/sh", str(script)],
                capture_output=True,
                text=True,
                env=environment,
            )
            return result, log.read_text().splitlines()

    def test_reconciler_creates_exactly_ten_roles_without_assigning_them(self):
        result, calls = self._run_reconciler()
        self.assertEqual(0, result.returncode, result.stderr)
        creations = [call for call in calls if call.startswith("create roles ")]
        self.assertEqual(10, len(creations))
        self.assertIn('"roles":10,"created":10,"human_assigned":false,"service_account_grants":0', result.stdout)
        self.assertFalse(any("add-roles" in call for call in calls))

    def test_reconciler_tolerates_only_the_reviewed_chat_service_account(self):
        result, calls = self._run_reconciler({
            "roles/agentgateway-write:media/users": "service-account-chat-agentgateway",
        })
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('"human_assigned":false,"service_account_grants":1', result.stdout)
        self.assertFalse(any("add-roles" in call for call in calls))

    def test_reconciler_rejects_a_human_on_the_allowlisted_role(self):
        result, _ = self._run_reconciler({
            "roles/agentgateway-write:media/users": "dani",
        })
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-write:media is assigned to an unauthorized user", result.stderr)
        self.assertNotIn("dani", result.stderr)

    def test_reconciler_rejects_the_chat_service_account_on_any_other_role(self):
        result, _ = self._run_reconciler({
            "roles/agentgateway-write:synapse/users": "service-account-chat-agentgateway",
        })
        self.assertEqual(1, result.returncode)
        self.assertIn("agentgateway-write:synapse is assigned to a user; dedicated-client rollout is not ready", result.stderr)

    def test_reconciler_rejects_a_second_holder_next_to_the_service_account(self):
        result, _ = self._run_reconciler({
            "roles/agentgateway-write:media/users": "service-account-chat-agentgateway\\ndani",
        })
        self.assertEqual(1, result.returncode)
        self.assertIn("is assigned to an unauthorized user", result.stderr)

    def test_allowlist_is_immutable(self):
        result, calls = self._run_reconciler(
            env_overrides={"ALLOWED_SERVICE_ACCOUNTS": "agentgateway-write:synapse=service-account-chat-agentgateway"},
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("ALLOWED_SERVICE_ACCOUNTS is immutable", result.stderr)
        self.assertEqual([], calls)

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
        self.assertIn("value: agentgateway-write:media=service-account-chat-agentgateway", manifest)
        self.assertNotIn("0.0.0.0/0", manifest)

    def test_kustomize_owns_job_and_script(self):
        kustomization = (BASE / "kustomization.yaml").read_text()
        self.assertIn("agentgateway-domain-roles-job.yaml", kustomization)
        self.assertIn("scripts/agentgateway-domain-roles.sh", kustomization)


if __name__ == "__main__":
    unittest.main()
