#!/bin/sh
set -eu

umask 077

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-agentgateway-social-mcp}"
REDIRECT_URI="${REDIRECT_URI:-https://chat.e-dani.com/oauth/clients/mcp:social/callback}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
PKCE_METHOD="${PKCE_METHOD:-S256}"
RECONCILE_CONTRACT_VERSION="${RECONCILE_CONTRACT_VERSION:-1}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-agentgateway-social-admin.config

cleanup() {
  rm -f "${ADMIN_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${CLIENT_ID}" "$1"
}

# Immutable identity of this reconciler: a PUBLIC PKCE browser client only.
# It carries no secret, no service account and no realm role; it exists so the
# gateway can short-circuit MCP DCR against a pre-registered public client and
# Open WebUI can run the authorization-code + PKCE flow. Pinning these keeps a
# future edit from silently widening a browser client into a confidential or
# direct-grant one.
[ "${CLIENT_ID}" = "agentgateway-social-mcp" ] || fail "CLIENT_ID is immutable"
[ "${REALM}" = "edani" ] || fail "REALM is immutable"
[ "${MAPPER_NAME}" = "aud-mcp" ] || fail "MAPPER_NAME is immutable"
[ "${PKCE_METHOD}" = "S256" ] || fail "PKCE_METHOD is immutable"
[ "${RECONCILE_CONTRACT_VERSION}" = "1" ] || fail "unsupported reconcile contract version"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "unsupported MODE=${MODE}" ;;
esac

nonempty_lines() {
  sed '/^[[:space:]]*$/d'
}

line_count() {
  nonempty_lines | wc -l | tr -d '[:space:]'
}

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

resolve_client_optional() {
  rows="$(kget clients -q "clientId=${CLIENT_ID}" --fields id --format csv --noquotes | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate client ${CLIENT_ID}"
  printf '%s' "${rows}"
}

require_client() {
  uuid="$(resolve_client_optional)"
  [ -n "${uuid}" ] || fail "client ${CLIENT_ID} is missing"
  printf '%s' "${uuid}"
}

client_field() {
  kget "clients/$1" --fields "$2" --format csv --noquotes | nonempty_lines
}

assert_client_boolean() {
  actual="$(client_field "$1" "$2")"
  [ "${actual}" = "$3" ] || fail "client field $2 expected $3"
}

upsert_client() {
  uuid="$(resolve_client_optional)"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  # publicClient=true and no secret: the browser holds no secret and the
  # gateway short-circuits MCP DCR to this pre-registered client. The flow is
  # authorization-code + PKCE only, so direct access, implicit and service
  # accounts stay off and fullScopeAllowed stays false (no realm role is ever
  # emitted by this client).
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=true \
    -s standardFlowEnabled=true \
    -s directAccessGrantsEnabled=false \
    -s implicitFlowEnabled=false \
    -s serviceAccountsEnabled=false \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s "redirectUris=[\"${REDIRECT_URI}\"]" \
    -s "attributes.\"pkce.code.challenge.method\"=${PKCE_METHOD}" >/dev/null 2>&1 || \
    fail "failed to reconcile ${CLIENT_ID}"
  CLIENT_UUID="$(require_client)"
}

filter_mapper_id() {
  expected="$1"
  while IFS=, read -r mapper_id mapper_name; do
    if [ "${mapper_name}" = "${expected}" ]; then
      printf '%s\n' "${mapper_id}"
    fi
  done
}

mapper_uuid_optional() {
  rows="$(kget "clients/${CLIENT_UUID}/protocol-mappers/models" \
    --fields id,name --format csv --noquotes | \
    filter_mapper_id "${MAPPER_NAME}" | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate mapper ${MAPPER_NAME}"
  printf '%s' "${rows}"
}

upsert_audience_mapper() {
  mapper_uuid="$(mapper_uuid_optional)"
  endpoint="clients/${CLIENT_UUID}/protocol-mappers/models"
  action=create
  if [ -n "${mapper_uuid}" ]; then
    endpoint="${endpoint}/${mapper_uuid}"
    action=update
  fi
  # House audience-mapper pattern (verified on agentgateway-mcp): the MCP
  # resource audience lands in access and introspection tokens only, never in
  # the id token or userinfo.
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "name=${MAPPER_NAME}" \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s "config.\"included.custom.audience\"=${AGENTGATEWAY_AUDIENCE}" \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' \
    -s 'config."userinfo.token.claim"=false' >/dev/null 2>&1 || \
    fail "failed to reconcile audience mapper"
}

verify_client() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient true
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled true
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled false
  redirect="$(client_field "${CLIENT_UUID}" redirectUris)"
  printf '%s' "${redirect}" | grep -Fq "${REDIRECT_URI}" || fail "client redirect URI is missing"
  # kcadm's CSV output does not serialize map fields like `attributes` (it
  # comes back empty), so the PKCE check must read the client with
  # --format json — same house pattern as read_redirect_uris in
  # skirmbooks-sso.sh. Match key and value paired so an S256 living in any
  # other attribute cannot satisfy the check.
  attrs="$(kget "clients/${CLIENT_UUID}" --fields attributes --format json)"
  printf '%s' "${attrs}" | grep -Eq \
    "\"pkce\.code\.challenge\.method\"[[:space:]]*:[[:space:]]*\"${PKCE_METHOD}\"" || \
    fail "client PKCE challenge method is missing"
  [ -n "$(mapper_uuid_optional)" ] || fail "audience mapper missing"
}

rollback_identity() {
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to delete ${CLIENT_ID}"
  fi
  printf '{"client_id":"%s","present":false}\n' "${CLIENT_ID}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    upsert_client
    progress client-reconciled
    upsert_audience_mapper
    progress mapper-reconciled
    verify_client
    printf '{"client_id":"%s","present":true,"public_client":true,"pkce":"%s"}\n' \
      "${CLIENT_ID}" "${PKCE_METHOD}"
    ;;
  audit)
    verify_client
    printf '{"client_id":"%s","present":true,"public_client":true,"pkce":"%s"}\n' \
      "${CLIENT_ID}" "${PKCE_METHOD}"
    ;;
  rollback)
    rollback_identity
    ;;
esac
