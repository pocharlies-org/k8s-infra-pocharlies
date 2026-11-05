#!/bin/sh
set -eu

umask 077

# INFRA-1180 (Request de la sesión tech-lead de INFRA-403; desbloquea la pasada
# de producción de C2, INFRA-616): el cliente público del realm `edani` que abre
# la app nativa photos-ios (pocharlies-org/photos-ios), más el grant humano que
# su contrato de token exige. Mecanismo fijado por el plan de INFRA-403 y por la
# Request: es lo que hay aquí, literal.
#
# Reconcilia (idempotente):
#   1. cliente PUBLICO `photos-app`: Authorization Code + PKCE S256, redirect
#      EXACTO y unico dgx://oauth/callback (sin comodín), NO es el
#      `oauth2-proxy` compartido; fullScopeAllowed=false (el token del usuario
#      solo lleva los roles explícitamente mapeados en el client, no la
#      totalidad de los del usuario — regla de la familia INFRA-45);
#   2. mapper `aud-mcp` (oidc-audience-mapper): aud = mcp.lan.e-dani.com en el
#      access token (lo que verifica el AgentGateway en la ruta /photos,
#      k8s-agentgateway-pocharlies#247; mismo patrón aud-dgx-app del cliente
#      dgx-app, aquí con audience custom);
#   3. scope de roles del cliente: agentgateway-read:photos +
#      photos-confirm-delete mapeados en clients/<uuid>/scope-mappings/realm —
#      con fullScopeAllowed=false esto es lo que hace viajar los roles en el
#      token (patrón agentgateway-read-grants.sh; la ruta /photos exige el
#      primero y el gate de borrado G1 del architect lee el segundo del JWT);
#   4. grant directo de agentgateway-read:photos a Daniel (subject
#      e51253a7-c137-4c6c-9fb9-af9cecd3b147, username me@e-dani.com, mismo pin
#      que photos-confirm-delete-grant-daniel.sh): el usuario de la app. Es la
#      única concesión humana que aplica este hook; photos-confirm-delete NO se
#      concede aquí (lo posee photos-confirm-delete-grant-daniel.sh, wave 25) —
#      este hook solo lo MAPEA en el scope del cliente, que no es una concesión.
#   Y VERIFICA antes de dar el OK (falla si no): los booleanos del cliente, el
#   redirect exacto, PKCE S256, el mapper con su audience, los dos roles en el
#   scope del cliente, el grant directo del usuario, y las claims del token de
#   ejemplo (evaluate-scopes): aud=mcp.lan.e-dani.com y los dos roles en
#   realm_access (lo que el gateway va a leer).
#
# Los dos roles los ALTA y posee el PostSync agentgateway-read-grants.sh
# (wave 20) y photos-confirm-delete-grant-daniel.sh (wave 25): este hook wave
# 25 los exige existentes y no los crea (fail-closed: si faltan, el sync está a
# medias y hay que arreglarlo, no parchearlo desde aquí). La titularidad humana
# de agentgateway-read:photos está declarada en ROLES.yaml y PRINCIPALS.md
# (SC-4414) y tolerada por la allowlist revisada de
# agentgateway-read-grants.sh (PHOTOS_HUMAN_*, precedente SC-3805).
#
# MODE audit: solo las verificaciones. MODE rollback: desactiva el cliente
# (NUNCA lo borra: eliminar un principal es decisión del CTO, PRINCIPALS.md) y
# revoca el grant directo de agentgateway-read:photos a Daniel; un git revert de
# este archivo restaura ambos en el siguiente PostSync.
#
# OJO: corre DENTRO de la imagen de Keycloak, que no trae awk ni jq (SC-1215).
# Solo kcadm + sed/grep/tr/wc/rm/sleep. Nunca imprime secretos ni tokens: solo
# veredictos.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-photos-app}"
REDIRECT_URI="${REDIRECT_URI:-dgx://oauth/callback}"
AUD_MAPPER="${AUD_MAPPER:-aud-mcp}"
AUDIENCE="${AUDIENCE:-mcp.lan.e-dani.com}"
# Los dos roles que el token de la app debe traer (contrato INFRA-402/INFRA-403):
# la lectura de la ruta y el gate humano de borrado.
SCOPED_ROLE_NAMES="${SCOPED_ROLE_NAMES:-agentgateway-read:photos,photos-confirm-delete}"
USER_ID="${USER_ID:-e51253a7-c137-4c6c-9fb9-af9cecd3b147}"
USER_NAME="${USER_NAME:-me@e-dani.com}"
GRANT_ROLE_NAME="${GRANT_ROLE_NAME:-agentgateway-read:photos}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-photos-app-admin.config
KCADM_OUT=/tmp/kcadm-photos-app-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"

progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${CLIENT_ID}" "$1"
}

# Inmutables (contrato con la app pocharlies-org/photos-ios, PhotosAuth.swift,
# y con el gateway): renombrarlos despues del primer merge es un cambio de
# contrato.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${CLIENT_ID}" = "photos-app" ] || fail "CLIENT_ID is immutable"
[ "${REDIRECT_URI}" = "dgx://oauth/callback" ] || fail "REDIRECT_URI is immutable"
[ "${AUD_MAPPER}" = "aud-mcp" ] || fail "AUD_MAPPER is immutable"
[ "${AUDIENCE}" = "mcp.lan.e-dani.com" ] || fail "AUDIENCE is immutable"
[ "${SCOPED_ROLE_NAMES}" = "agentgateway-read:photos,photos-confirm-delete" ] || \
  fail "SCOPED_ROLE_NAMES is immutable; the token contract of photos-ios is fixed by INFRA-402/INFRA-403"
[ "${GRANT_ROLE_NAME}" = "agentgateway-read:photos" ] || fail "GRANT_ROLE_NAME is immutable"
[ "${USER_ID}" = "e51253a7-c137-4c6c-9fb9-af9cecd3b147" ] || fail "USER_ID is immutable"
[ "${USER_NAME}" = "me@e-dani.com" ] || fail "USER_NAME is immutable"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

# `-q clientId=` es un filtro de SUBCADENA en el servidor (dgx-messages-client
# lo documenta); se pide id,clientId y se casa el clientId exacto.
# $1 = client id; imprime el uuid o vacio; >1 fila = fail.
resolve_client_exact() {
  rows="$(kget clients -q "clientId=$1" --fields id,clientId --format csv --noquotes | \
    nonempty_lines | while IFS= read -r line; do
      case "${line}" in
        *,*)
          if [ "${line#*,}" = "$1" ]; then
            printf '%s\n' "${line%%,*}"
          fi
          ;;
      esac
    done)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate client $1"
  printf '%s' "${rows}"
}

require_client_exact() {
  uuid="$(resolve_client_exact "$1")"
  [ -n "${uuid}" ] || fail "client $1 is missing"
  printf '%s' "${uuid}"
}

client_field() {
  kget "clients/$1" --fields "$2" --format csv --noquotes | nonempty_lines
}

assert_client_boolean() {
  actual="$(client_field "$1" "$2")"
  [ "${actual}" = "$3" ] || fail "client $1 field $2 expected $3, got ${actual}"
}

# Devuelve el array INTERNO de un campo lista (`"a", "b"`) sin espacios en los
# bordes (dgx-messages-client.sh: kcadm pinta el JSON en varias lineas).
read_list_field() {
  kget "clients/$1" --fields "$2" --format json | tr -d '\n' | \
    sed -n 's/.*"'"$2"'"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' | \
    sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

assert_exact_list() {
  actual="$(read_list_field "$1" "$2")"
  [ "${actual}" = "\"$3\"" ] || fail "$1 $2 registered is [${actual}], expected exactly [\"$3\"]"
}

assert_empty_list() {
  actual="$(read_list_field "$1" "$2")"
  [ -z "${actual}" ] || fail "$1 $2 must be empty, got [${actual}]"
}

mapper_uuid_optional() {
  # $1 = uuid del cliente, $2 = nombre del mapper.
  rows="$(kget "clients/$1/protocol-mappers/models" \
    --fields id,name --format csv --noquotes | \
    while IFS=, read -r mapper_id mapper_name; do
      [ "${mapper_name}" = "$2" ] && printf '%s\n' "${mapper_id}"
    done | nonempty_lines)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate mapper $2"
  printf '%s' "${rows}"
}

upsert_mapper() {
  # $1 = uuid cliente, $2 = nombre mapper, $3 = protocolMapper, resto = -s ...
  client_uuid="$1"
  mapper_name="$2"
  mapper_kind="$3"
  shift 3
  mapper_uuid="$(mapper_uuid_optional "${client_uuid}" "${mapper_name}")"
  endpoint="clients/${client_uuid}/protocol-mappers/models"
  action=create
  if [ -n "${mapper_uuid}" ]; then
    endpoint="${endpoint}/${mapper_uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "name=${mapper_name}" \
    -s protocol=openid-connect \
    -s "protocolMapper=${mapper_kind}" \
    "$@" >/dev/null 2>&1 || fail "failed to reconcile mapper ${mapper_name}"
}

scope_names() {
  kget "clients/$1/scope-mappings/realm" --fields name --format csv --noquotes | nonempty_lines | sort
}

grant_missing_roles() {
  # $1 = REST collection, $2 = newline list of currently mapped names,
  # $3 = comma list of wanted roles (idiom agentgateway-read-grants.sh).
  collection="$1"
  current="$2"
  wanted="$3"
  missing=""
  old_ifs="${IFS}"
  IFS=,
  for role in ${wanted}; do
    IFS="${old_ifs}"
    if ! printf '%s\n' "${current}" | grep -Fxq "${role}"; then
      role_id="$(kget "roles/${role}" --fields id --format csv --noquotes | nonempty_lines)"
      [ -n "${role_id}" ] || fail "${role} is missing from the realm"
      if [ -n "${missing}" ]; then
        missing="${missing},"
      fi
      missing="${missing}{\"id\":\"${role_id}\",\"name\":\"${role}\"}"
    fi
    IFS=,
  done
  IFS="${old_ifs}"
  if [ -n "${missing}" ]; then
    "${KCADM}" create "${collection}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -b "[${missing}]" >/dev/null 2>&1 || fail "failed to map roles into ${collection}"
  fi
}

assert_wanted_mapped() {
  # $1 = newline list of mapped names, $2 = comma list of wanted roles
  current="$1"
  wanted="$2"
  old_ifs="${IFS}"
  IFS=,
  for role in ${wanted}; do
    IFS="${old_ifs}"
    printf '%s\n' "${current}" | grep -Fxq "${role}" || fail "${role} is not mapped in the expected set"
    IFS=,
  done
  IFS="${old_ifs}"
}

assert_roles_exist() {
  # Los roles los ALTAN otros reconciliadores (wave 20 y su hermano wave 25);
  # este hook los exige y no los crea (fail-closed).
  old_ifs="${IFS}"
  IFS=,
  for role in ${SCOPED_ROLE_NAMES}; do
    IFS="${old_ifs}"
    kget "roles/${role}" --fields id >/dev/null 2>&1 || \
      fail "${role} is missing from the realm: its owner reconciler has not run (this hook never creates it)"
    IFS=,
  done
  IFS="${old_ifs}"
}

user_field() {
  kget "users/${USER_ID}" --fields "$1" --format csv --noquotes | nonempty_lines
}

resolve_user() {
  # OWU-80 limit: si el subject no está en el realm, falla en seco. Este hook
  # nunca crea, edita ni habilita usuarios.
  kget "users/${USER_ID}" --fields id >/dev/null 2>&1 || \
    fail "user ${USER_ID} does not exist in realm ${REALM}: refusing to create a human user"
  username="$(user_field username)"
  [ "${username}" = "${USER_NAME}" ] || \
    fail "user ${USER_ID} is ${username}, not the pinned ${USER_NAME}: refusing to continue"
  [ "$(user_field enabled)" = "true" ] || fail "user ${USER_NAME} is disabled: refusing to grant"
  sa_client="$(user_field serviceAccountClientId)"
  case "${sa_client}" in
    ""|null) ;;
    *) fail "user ${USER_ID} is the service account of ${sa_client}: this hook grants to the human user only" ;;
  esac
}

user_has_direct_role() {
  kget "users/${USER_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${GRANT_ROLE_NAME}"
}

upsert_client() {
  progress "${CLIENT_ID}" upsert
  uuid="$(resolve_client_exact "${CLIENT_ID}")"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=true \
    -s standardFlowEnabled=true \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s "redirectUris=[\"${REDIRECT_URI}\"]" \
    -s 'webOrigins=[]' \
    -s 'attributes."pkce.code.challenge.method"=S256' >/dev/null 2>&1 || \
    fail "failed to ${action} client ${CLIENT_ID}"
  CLIENT_UUID="$(require_client_exact "${CLIENT_ID}")"
  # aud-mcp: la audience que verifica el AgentGateway (k8s-agentgateway#247).
  # access token sí, id token no (la app no lo lee), introspección sí (patrón
  # aud-dgx-app). included.client.audience=false: el aud del token es
  # EXACTAMENTE la audience del gateway, no se añade el clientId.
  upsert_mapper "${CLIENT_UUID}" "${AUD_MAPPER}" oidc-audience-mapper \
    -s 'config."included.client.audience"=false' \
    -s "config.\"included.custom.audience\"=${AUDIENCE}" \
    -s 'config."access.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=true' \
    -s 'config."userinfo.token.claim"=false'
}

grant_daniel_read_role() {
  progress "${CLIENT_ID}" grant
  resolve_user
  if user_has_direct_role; then
    return 0
  fi
  # kcadm add-roles: el exit code no se fía (SC-1215); la lectura post-ensure
  # de verify_client_state es la aserción real.
  if ! "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
    --uid "${USER_ID}" --rolename "${GRANT_ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
    fail "failed to map ${GRANT_ROLE_NAME} to ${USER_NAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
}

verify_client_state() {
  CLIENT_UUID="$(require_client_exact "${CLIENT_ID}")"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient true
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled true
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled false
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  # Redirect EXACTO: ni comodín ni una segunda URI colada a mano.
  assert_exact_list "${CLIENT_UUID}" redirectUris "${REDIRECT_URI}"
  assert_empty_list "${CLIENT_UUID}" webOrigins
  # OJO kcadm 26.6.2 (dgx-messages-client.sh): el campo-objeto `attributes` sin
  # subcampos se imprime vacio por el filtro cliente de kcadm; se casa sobre la
  # representacion COMPLETA (sin --fields): NUNCA se imprime, solo se grep-a.
  client="$(kget "clients/${CLIENT_UUID}" --format json | tr -d '\n')"
  printf '%s' "${client}" | grep -Eq '"pkce\.code\.challenge\.method"[[:space:]]*:[[:space:]]*"S256"' || \
    { unset client; fail "client pkce.code.challenge.method is not S256"; }
  unset client
  mapper_uuid="$(mapper_uuid_optional "${CLIENT_UUID}" "${AUD_MAPPER}")"
  [ -n "${mapper_uuid}" ] || fail "mapper ${AUD_MAPPER} missing on ${CLIENT_ID}"
  mapper="$(kget "clients/${CLIENT_UUID}/protocol-mappers/models/${mapper_uuid}" --format json | tr -d '\n')"
  printf '%s' "${mapper}" | grep -Eq "\"included\.custom\.audience\"[[:space:]]*:[[:space:]]*\"${AUDIENCE}\"" || \
    { unset mapper; fail "mapper ${AUD_MAPPER} does not carry the audience ${AUDIENCE}"; }
  unset mapper
  # Scope de roles del cliente: los dos del contrato, mapeados.
  assert_wanted_mapped "$(scope_names "${CLIENT_UUID}")" "${SCOPED_ROLE_NAMES}"
  # Grant directo del usuario (el otro lado del contrato del token).
  user_has_direct_role || \
    fail "post-ensure assertion failed: ${GRANT_ROLE_NAME} is not in the direct realm-role mappings of ${USER_NAME}"
}

verify_example_token() {
  # evaluate-scopes (idiom openwebui-ios-client.sh): simula la emisión del
  # access token del usuario por este cliente, sin credenciales. Es lo que el
  # gateway va a leer: aud exacta + los dos roles en realm_access.
  access="$(kget "clients/${CLIENT_UUID}/evaluate-scopes/generate-example-access-token" \
    -q scope=openid -q "userId=${USER_ID}" | tr -d '\n')" || fail "example access token failed"
  [ -n "${access}" ] || fail "example access token is empty"
  printf '%s' "${access}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${CLIENT_ID}"'"' || \
    fail "example access token has wrong azp (expected ${CLIENT_ID})"
  printf '%s' "${access}" | grep -Eq "\"aud\"[[:space:]]*:[[:space:]]*(\"${AUDIENCE}\"|\[[^]]*\"${AUDIENCE}\")" || \
    fail "example access token has no aud ${AUDIENCE}"
  old_ifs="${IFS}"
  IFS=,
  for role in ${SCOPED_ROLE_NAMES}; do
    IFS="${old_ifs}"
    # realm_access.roles: array de nombres; se casa el rol exacto entre comillas.
    printf '%s' "${access}" | grep -Eq "\"realm_access\"[^}]*\"roles\"[^]]*\"${role}\"" || \
      { unset access; fail "example access token does not carry realm role ${role}"; }
    IFS=,
  done
  IFS="${old_ifs}"
  unset access
}

report() {
  printf '{"client_id":"%s","realm":"%s","verdict":"%s"}\n' "${CLIENT_ID}" "${REALM}" "$1"
}

login_admin

case "${MODE}" in
  ensure)
    assert_roles_exist
    upsert_client
    grant_missing_roles "clients/${CLIENT_UUID}/scope-mappings/realm" "$(scope_names "${CLIENT_UUID}")" "${SCOPED_ROLE_NAMES}"
    grant_daniel_read_role
    verify_client_state
    verify_example_token
    report "ensure done"
    ;;
  audit)
    assert_roles_exist
    verify_client_state
    verify_example_token
    report "audit done"
    ;;
  rollback)
    # Desactiva el cliente (NUNCA lo borra) y revoca el grant directo; el scope
    # de roles del cliente queda inerte con el cliente desactivado. Un git
    # revert restaura todo en el siguiente PostSync.
    uuid="$(resolve_client_exact "${CLIENT_ID}")"
    if [ -n "${uuid}" ]; then
      "${KCADM}" update "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s enabled=false > "${KCADM_OUT}" 2>&1 || \
        fail "rollback: failed to disable ${CLIENT_ID}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      assert_client_boolean "${uuid}" enabled false
    fi
    if kget "users/${USER_ID}" --fields id >/dev/null 2>&1 && user_has_direct_role; then
      if ! "${KCADM}" remove-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${USER_ID}" --rolename "${GRANT_ROLE_NAME}" > "${KCADM_OUT}" 2>&1; then
        fail "rollback: failed to remove ${GRANT_ROLE_NAME} from ${USER_NAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      fi
      if user_has_direct_role; then
        fail "rollback: ${GRANT_ROLE_NAME} remains in the direct realm-role mappings of ${USER_NAME}"
      fi
    fi
    report "rollback done"
    ;;
esac
