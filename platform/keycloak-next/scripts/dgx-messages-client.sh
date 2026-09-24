#!/bin/sh
set -eu

umask 077

# SC-1233 (P0 de SC-1198) — cliente OIDC propio de dgx-messages en el realm
# `edani`, detras de oauth2-proxy-messages (messages.lan.e-dani.com).
#
# Por que un cliente propio y no el `oauth2-proxy` compartido: social-api
# (SC-1197) solo acepta el access token si `azp=dgx-messages` y `aud` contiene
# `social-api`. Con el cliente compartido el token saldria con
# `azp=oauth2-proxy` y la audiencia de social-api viajaria a las ~90 rutas de
# `sso-chain`.
#
# Lo que reconcilia (idempotente):
#   1. el cliente confidencial `dgx-messages`: standard flow, sin direct grants,
#      sin service account, fullScopeAllowed=false, redirect EXACTO (sin
#      comodin), webOrigins y post-logout redirect del propio host, PKCE S256;
#   2. el mapper Audience `social-api` SOLO en el access token (el ID token sigue
#      con aud=dgx-messages, que es lo que valida oauth2-proxy);
#   3. el mapper de grupos (full.path) para `allowed_groups` del proxy.
# Y lo que VERIFICA antes de dar el OK (falla si no):
#   - el redirect registrado es exactamente REDIRECT_URI y nada mas;
#   - un access token de ejemplo para CHECK_USER_ID (Admin API
#     evaluate-scopes/generate-example-access-token) lleva azp=dgx-messages,
#     aud con social-api y un grupo /edani-*;
#   - el ID token de ejemplo NO lleva social-api en aud.
#
# OJO: corre DENTRO de la imagen de Keycloak, que no trae awk (SC-1215). Solo
# sed/grep/tr/wc/rm/sleep. Nunca imprime el secreto ni un token: solo veredictos.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-dgx-messages}"
REDIRECT_URI="${REDIRECT_URI:-https://messages.lan.e-dani.com/oauth2/callback}"
WEB_ORIGIN="${WEB_ORIGIN:-https://messages.lan.e-dani.com}"
POST_LOGOUT_REDIRECT_URI="${POST_LOGOUT_REDIRECT_URI:-https://messages.lan.e-dani.com/}"
SOCIAL_AUDIENCE="${SOCIAL_AUDIENCE:-social-api}"
# Usuario con el que se acuña el token de ejemplo (Dani, me@e-dani.com).
CHECK_USER_ID="${CHECK_USER_ID:-e51253a7-c137-4c6c-9fb9-af9cecd3b147}"
AUDIENCE_MAPPER=dgx-messages-social-api-audience
GROUPS_MAPPER=dgx-messages-groups
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-dgx-messages-admin.config

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

# Inmutables: oauth2-proxy-messages fija el client_id y el redirect, social-api
# fija azp y aud. Cambiarlos aqui sin cambiarlos alli rompe el login o la API.
[ "${CLIENT_ID}" = "dgx-messages" ] || fail "CLIENT_ID is immutable"
[ "${REDIRECT_URI}" = "https://messages.lan.e-dani.com/oauth2/callback" ] || fail "REDIRECT_URI is immutable"
[ "${WEB_ORIGIN}" = "https://messages.lan.e-dani.com" ] || fail "WEB_ORIGIN is immutable"
[ "${POST_LOGOUT_REDIRECT_URI}" = "https://messages.lan.e-dani.com/" ] || fail "POST_LOGOUT_REDIRECT_URI is immutable"
[ "${SOCIAL_AUDIENCE}" = "social-api" ] || fail "SOCIAL_AUDIENCE is immutable"
case "${MODE}" in
  ensure|audit)
    [ -n "${DGX_MESSAGES_CLIENT_SECRET:-}" ] || fail "client secret is empty"
    ;;
  rollback) ;;
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

# `-q clientId=` es un filtro de SUBCADENA en el servidor: se piden id,clientId
# y se casa el clientId exacto, para no confundir dgx-messages con un
# dgx-messages-v2 o similar.
resolve_client_optional() {
  rows="$(kget clients -q "clientId=${CLIENT_ID}" --fields id,clientId --format csv --noquotes | \
    nonempty_lines | while IFS= read -r line; do
      case "${line}" in
        *,*)
          if [ "${line#*,}" = "${CLIENT_ID}" ]; then
            printf '%s\n' "${line%%,*}"
          fi
          ;;
      esac
    done)"
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
  [ "${actual}" = "$3" ] || fail "client field $2 expected $3, got ${actual}"
}

# Devuelve el array INTERNO de un campo lista (`"a", "b"`), sin espacios en los
# bordes. kcadm pinta `{ "redirectUris" : [ "a" ] }` en varias lineas.
read_list_field() {
  kget "clients/$1" --fields "$2" --format json | tr -d '\n' | \
    sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' | \
    sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

assert_exact_list() {
  actual="$(read_list_field "$1" "$2")"
  [ "${actual}" = "\"$3\"" ] || fail "$2 registered is [${actual}], expected exactly [\"$3\"]"
}

upsert_client() {
  uuid="$(resolve_client_optional)"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=false \
    -s standardFlowEnabled=true \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s "rootUrl=${WEB_ORIGIN}" \
    -s "baseUrl=${WEB_ORIGIN}/" \
    -s "redirectUris=[\"${REDIRECT_URI}\"]" \
    -s "webOrigins=[\"${WEB_ORIGIN}\"]" \
    -s "attributes.\"post.logout.redirect.uris\"=${POST_LOGOUT_REDIRECT_URI}" \
    -s 'attributes."pkce.code.challenge.method"=S256' \
    -s "secret=${DGX_MESSAGES_CLIENT_SECRET}" >/dev/null 2>&1 || \
    fail "failed to ${action} client ${CLIENT_ID}"
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
    filter_mapper_id "$1" | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate mapper $1"
  printf '%s' "${rows}"
}

mapper_target() {
  mapper_uuid="$(mapper_uuid_optional "$1")"
  MAPPER_ENDPOINT="clients/${CLIENT_UUID}/protocol-mappers/models"
  MAPPER_ACTION=create
  if [ -n "${mapper_uuid}" ]; then
    MAPPER_ENDPOINT="${MAPPER_ENDPOINT}/${mapper_uuid}"
    MAPPER_ACTION=update
  fi
}

upsert_audience_mapper() {
  # Patron de chat-agentgateway-client.sh: la audiencia va SOLO al access token.
  mapper_target "${AUDIENCE_MAPPER}"
  "${KCADM}" "${MAPPER_ACTION}" "${MAPPER_ENDPOINT}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "name=${AUDIENCE_MAPPER}" \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-audience-mapper \
    -s "config.\"included.custom.audience\"=${SOCIAL_AUDIENCE}" \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' >/dev/null 2>&1 || \
    fail "failed to reconcile audience mapper"
}

upsert_groups_mapper() {
  # full.path: allowed_groups de oauth2-proxy-messages casa "/edani-users", no "edani-users".
  mapper_target "${GROUPS_MAPPER}"
  "${KCADM}" "${MAPPER_ACTION}" "${MAPPER_ENDPOINT}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "name=${GROUPS_MAPPER}" \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-group-membership-mapper \
    -s 'config."claim.name"=groups' \
    -s 'config."full.path"=true' \
    -s 'config."id.token.claim"=true' \
    -s 'config."access.token.claim"=true' \
    -s 'config."userinfo.token.claim"=true' \
    -s 'config."introspection.token.claim"=true' >/dev/null 2>&1 || \
    fail "failed to reconcile groups mapper"
}

verify_client() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient false
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled true
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled false
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  # Redirect EXACTO: ni comodin ni una segunda URI colada a mano en la consola.
  assert_exact_list "${CLIENT_UUID}" redirectUris "${REDIRECT_URI}"
  assert_exact_list "${CLIENT_UUID}" webOrigins "${WEB_ORIGIN}"
  attrs="$(kget "clients/${CLIENT_UUID}" --fields attributes --format json | tr -d '\n')"
  printf '%s' "${attrs}" | grep -Eq '"post\.logout\.redirect\.uris"[[:space:]]*:[[:space:]]*"'"${POST_LOGOUT_REDIRECT_URI}"'"' || \
    fail "post.logout.redirect.uris is not ${POST_LOGOUT_REDIRECT_URI}"
  printf '%s' "${attrs}" | grep -Eq '"pkce\.code\.challenge\.method"[[:space:]]*:[[:space:]]*"S256"' || \
    fail "pkce.code.challenge.method is not S256"
  unset attrs
  [ -n "$(mapper_uuid_optional "${AUDIENCE_MAPPER}")" ] || fail "audience mapper missing"
  [ -n "$(mapper_uuid_optional "${GROUPS_MAPPER}")" ] || fail "groups mapper missing"
}

example_token() {
  # Admin API "Client scopes > Evaluate": devuelve las CLAIMS (JSON ya
  # decodificado, sin firma) que llevaria un token de este cliente para ese
  # usuario. No crea sesion ni token utilizable.
  kget "clients/${CLIENT_UUID}/evaluate-scopes/$1" \
    -q scope=openid -q "userId=${CHECK_USER_ID}" | tr -d '\n'
}

verify_example_claims() {
  access="$(example_token generate-example-access-token)" || fail "example access token failed"
  [ -n "${access}" ] || fail "example access token is empty"
  printf '%s' "${access}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${CLIENT_ID}"'"' || \
    fail "example access token has wrong azp (expected ${CLIENT_ID})"
  # aud sale como cadena si es una sola audiencia y como array si hay varias.
  printf '%s' "${access}" | grep -Eq '"aud"[[:space:]]*:[[:space:]]*(\[[^]]*)?"'"${SOCIAL_AUDIENCE}"'"' || \
    fail "example access token aud does not contain ${SOCIAL_AUDIENCE}"
  printf '%s' "${access}" | grep -Eq '"groups"[[:space:]]*:[[:space:]]*\[[^]]*"/edani-(admins|operators|users)"' || \
    fail "example access token has no /edani-* group with full path"
  unset access
  idt="$(example_token generate-example-id-token)" || fail "example id token failed"
  [ -n "${idt}" ] || fail "example id token is empty"
  printf '%s' "${idt}" | grep -Eq '"aud"[[:space:]]*:[[:space:]]*(\[[^]]*)?"'"${CLIENT_ID}"'"' || \
    fail "example id token aud does not contain ${CLIENT_ID}"
  if printf '%s' "${idt}" | grep -Fq "\"${SOCIAL_AUDIENCE}\""; then
    fail "example id token carries ${SOCIAL_AUDIENCE}; the audience mapper must stay access-token only"
  fi
  unset idt
}

rollback_client() {
  uuid="$(resolve_client_optional)"
  if [ -n "${uuid}" ]; then
    "${KCADM}" delete "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to delete ${CLIENT_ID}"
  fi
  [ -z "$(resolve_client_optional)" ] || fail "client ${CLIENT_ID} remains after rollback"
  printf '{"client_id":"%s","present":false}\n' "${CLIENT_ID}"
}

report_ok() {
  printf '{"client_id":"%s","present":true,"redirect_uri":"%s","redirect_exact":true,"azp":"%s","aud_contains":"%s","id_token_aud_clean":true}\n' \
    "${CLIENT_ID}" "${REDIRECT_URI}" "${CLIENT_ID}" "${SOCIAL_AUDIENCE}"
}

login_admin
progress authenticated
case "${MODE}" in
  ensure)
    upsert_client
    progress client-reconciled
    upsert_audience_mapper
    upsert_groups_mapper
    progress mappers-reconciled
    verify_client
    progress client-verified
    verify_example_claims
    report_ok
    ;;
  audit)
    verify_client
    verify_example_claims
    report_ok
    ;;
  rollback)
    rollback_client
    ;;
esac
