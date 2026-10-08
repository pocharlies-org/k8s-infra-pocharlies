#!/bin/sh
set -eu

umask 077

KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-domain-roles.config
# agentgateway-write:dgx-control (INFRA-249, CTO decision in ROUTE-ROLES.md)
# is created inert: the gateway already gates compute_mode_set,
# refusal_lambda_set and opencode_restart on it, and it has no entry in
# ALLOWED_SERVICE_ACCOUNTS, so nobody may hold it and those tools stay denied.
ROLE_NAMES="${ROLE_NAMES:-agentgateway-write:synapse,agentgateway-write:media,agentgateway-write:picqer,agentgateway-write:skirmshop-plugins,agentgateway-write:shopify,agentgateway-write:social,agentgateway-write:workspace,agentgateway-write:gsc,agentgateway-write:offers,agentgateway-write:sauvage,agentgateway-write:hermes,agentgateway-write:dgx-control,agentgateway-write:workspace-envio,agentgateway-write:workspace-borrador}"
EXPECTED_ROLE_NAMES="agentgateway-write:synapse,agentgateway-write:media,agentgateway-write:picqer,agentgateway-write:skirmshop-plugins,agentgateway-write:shopify,agentgateway-write:social,agentgateway-write:workspace,agentgateway-write:gsc,agentgateway-write:offers,agentgateway-write:sauvage,agentgateway-write:hermes,agentgateway-write:dgx-control,agentgateway-write:workspace-envio,agentgateway-write:workspace-borrador"
# Dedicated confidential clients reviewed to hold exactly one domain role each,
# as "<role>=<service-account-username>". The client itself is reconciled by a
# later PostSync hook (chat-agentgateway-client.sh); this hook only tolerates
# that single grant. Any other user, any group and any other service account
# still fails the reconcile.
#
# SC-2005 (2026-10-07): the allowlist widens to the four general Hermes
# secretaria service accounts (INFRA-494, epic INFRA-479: per-profile
# secretaria identities that write social and workspace through
# AgentGateway; the grants are owned by the devops creation process in
# k8s-openclaw-qwen36-pocharlies, never by this hook). Same rule as the
# chat pairs above: this hook only tolerates the reviewed holders.
#
# INFRA-676 (2026-10-07, P4b of INFRA-480): two new domain roles for the
# Gmail draft/send split of k8s-agentgateway-pocharlies#186.
# agentgateway-write:workspace-envio (gmail_send, gmail_forward,
# gmail_send_draft, gmail_delete_draft) is held by exactly one service
# account, the dedicated client hermes-enviar of the Hermes `enviar` plugin
# (hermes-enviar-client.sh, sync-wave 24). agentgateway-write:workspace-borrador
# (gmail_create_draft, gmail_update_draft) is created INERT: no allowlist
# entry, so nobody may hold it until the grant to secretaria-skirmshop is
# reviewed, which security (INFRA-640, condition 2) only allows once the
# narrowing of :workspace has propagated to the gateway.
ALLOWED_SERVICE_ACCOUNTS="${ALLOWED_SERVICE_ACCOUNTS:-agentgateway-write:media=service-account-chat-agentgateway,agentgateway-write:social=service-account-chat-agentgateway,agentgateway-write:workspace=service-account-chat-agentgateway,agentgateway-write:gsc=service-account-chat-agentgateway,agentgateway-write:synapse=service-account-chat-agentgateway,agentgateway-write:hermes=service-account-chat-agentgateway,agentgateway-write:social=service-account-hermes-secretaria,agentgateway-write:social=service-account-hermes-secretaria-casa,agentgateway-write:social=service-account-hermes-secretaria-dani,agentgateway-write:social=service-account-hermes-secretaria-leila,agentgateway-write:workspace=service-account-hermes-secretaria,agentgateway-write:workspace=service-account-hermes-secretaria-casa,agentgateway-write:workspace=service-account-hermes-secretaria-dani,agentgateway-write:workspace=service-account-hermes-secretaria-leila,agentgateway-write:workspace-envio=service-account-hermes-enviar}"
EXPECTED_ALLOWED_SERVICE_ACCOUNTS="agentgateway-write:media=service-account-chat-agentgateway,agentgateway-write:social=service-account-chat-agentgateway,agentgateway-write:workspace=service-account-chat-agentgateway,agentgateway-write:gsc=service-account-chat-agentgateway,agentgateway-write:synapse=service-account-chat-agentgateway,agentgateway-write:hermes=service-account-chat-agentgateway,agentgateway-write:social=service-account-hermes-secretaria,agentgateway-write:social=service-account-hermes-secretaria-casa,agentgateway-write:social=service-account-hermes-secretaria-dani,agentgateway-write:social=service-account-hermes-secretaria-leila,agentgateway-write:workspace=service-account-hermes-secretaria,agentgateway-write:workspace=service-account-hermes-secretaria-casa,agentgateway-write:workspace=service-account-hermes-secretaria-dani,agentgateway-write:workspace=service-account-hermes-secretaria-leila,agentgateway-write:workspace-envio=service-account-hermes-enviar"

cleanup() { rm -f "${ADMIN_CONFIG}"; }
trap cleanup EXIT HUP INT TERM

# Mechanical helpers (fail, login_admin, kget, nonempty_lines) come from the
# shared reconcile library (INFRA-477); the reviewed role family, the
# service-account allowlist and the bounded-holder check stay right here.
. "$(dirname "$0")/keycloak-reconcile-lib.sh"

[ "${ROLE_NAMES}" = "${EXPECTED_ROLE_NAMES}" ] || \
  fail "ROLE_NAMES is immutable; update the reviewed reconciler and AgentGateway matrix together"
[ "${ALLOWED_SERVICE_ACCOUNTS}" = "${EXPECTED_ALLOWED_SERVICE_ACCOUNTS}" ] || \
  fail "ALLOWED_SERVICE_ACCOUNTS is immutable; review the dedicated client reconciler and this allowlist together"

role_exists() {
  role="$1"
  kget "roles/${role}" --fields id >/dev/null 2>&1
}

allowed_service_account() {
  # Prints the one service-account username reviewed for role $1, or nothing.
  printf '%s\n' "${ALLOWED_SERVICE_ACCOUNTS}" | tr ',' '\n' | \
    while IFS='=' read -r pair_role pair_user; do
      if [ "${pair_role}" = "$1" ]; then
        printf '%s\n' "${pair_user}"
      fi
    done
}

assert_bounded_noncomposite() {
  role="$1"
  composite="$(kget "roles/${role}" --fields composite --format csv --noquotes | nonempty_lines)"
  [ "${composite}" = "false" ] || fail "${role} must remain non-composite"

  allowed="$(allowed_service_account "${role}")"
  users="$(kget "roles/${role}/users" --fields username --format csv --noquotes | nonempty_lines)"
  groups="$(kget "roles/${role}/groups" --fields path --format csv --noquotes | nonempty_lines)"
  [ -z "${groups}" ] || fail "${role} is assigned to a group; human/group grants are forbidden"
  if [ -n "${users}" ]; then
    [ -n "${allowed}" ] || fail "${role} is assigned to a user; dedicated-client rollout is not ready"
    while IFS= read -r username; do
      printf '%s\n' "${allowed}" | grep -Fxq "${username}" || \
        fail "${role} is assigned to an unauthorized user; only ${allowed} may hold it"
      granted=$((granted + 1))
    done <<EOF
${users}
EOF
  fi
}

login_admin

created=0
granted=0
old_ifs="${IFS}"
IFS=,
for role in ${ROLE_NAMES}; do
  IFS="${old_ifs}"
  if ! role_exists "${role}"; then
    "${KCADM}" create roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "name=${role}" \
      -s "description=Allows explicitly enumerated AgentGateway writes for ${role#agentgateway-write:}" \
      -s composite=false >/dev/null 2>&1 || fail "failed to create ${role}"
    created=$((created + 1))
  fi
  assert_bounded_noncomposite "${role}"
  IFS=,
done
IFS="${old_ifs}"

printf '{"role_family":"agentgateway-write-domain","roles":14,"created":%s,"human_assigned":false,"service_account_grants":%s}\n' \
  "${created}" "${granted}"
