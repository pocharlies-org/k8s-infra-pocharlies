#!/bin/sh
set -eu

umask 077

KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-domain-roles.config
ROLE_NAMES="${ROLE_NAMES:-agentgateway-write:synapse,agentgateway-write:media,agentgateway-write:picqer,agentgateway-write:skirmshop-plugins,agentgateway-write:shopify,agentgateway-write:social,agentgateway-write:workspace,agentgateway-write:gsc,agentgateway-write:offers}"
EXPECTED_ROLE_NAMES="agentgateway-write:synapse,agentgateway-write:media,agentgateway-write:picqer,agentgateway-write:skirmshop-plugins,agentgateway-write:shopify,agentgateway-write:social,agentgateway-write:workspace,agentgateway-write:gsc,agentgateway-write:offers"

cleanup() { rm -f "${ADMIN_CONFIG}"; }
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[ "${ROLE_NAMES}" = "${EXPECTED_ROLE_NAMES}" ] || \
  fail "ROLE_NAMES is immutable; update the reviewed reconciler and AgentGateway matrix together"

nonempty_lines() { sed '/^[[:space:]]*$/d'; }

login_admin() {
  attempt=1
  while [ "${attempt}" -le 30 ]; do
    if "${KCADM}" config credentials \
      --config "${ADMIN_CONFIG}" \
      --server "${KEYCLOAK_URL}" \
      --realm master \
      --user "${KC_BOOTSTRAP_ADMIN_USERNAME}" \
      --password "${KC_BOOTSTRAP_ADMIN_PASSWORD}" >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 5
  done
  fail "Keycloak admin login did not become ready"
}

kget() {
  "${KCADM}" get "$@" --config "${ADMIN_CONFIG}" -r "${REALM}"
}

role_exists() {
  role="$1"
  kget "roles/${role}" --fields id >/dev/null 2>&1
}

assert_unassigned_noncomposite() {
  role="$1"
  composite="$(kget "roles/${role}" --fields composite --format csv --noquotes | nonempty_lines)"
  [ "${composite}" = "false" ] || fail "${role} must remain non-composite"

  users="$(kget "roles/${role}/users" --fields username --format csv --noquotes | nonempty_lines)"
  groups="$(kget "roles/${role}/groups" --fields path --format csv --noquotes | nonempty_lines)"
  [ -z "${users}" ] || fail "${role} is assigned to a user; dedicated-client rollout is not ready"
  [ -z "${groups}" ] || fail "${role} is assigned to a group; human/group grants are forbidden"
}

login_admin

created=0
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
  assert_unassigned_noncomposite "${role}"
  IFS=,
done
IFS="${old_ifs}"

printf '{"role_family":"agentgateway-write-domain","roles":9,"created":%s,"assigned":false}\n' "${created}"
