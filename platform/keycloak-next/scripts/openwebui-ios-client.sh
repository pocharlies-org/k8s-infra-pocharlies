#!/bin/sh
set -eu

umask 077

# OWU-116 (S1 de OWU-95) — los dos clientes del realm `edani` que abre la ruta
# bearer de la app nativa (pocharlies-org/openwebui-ios, chat.e-dani.com), y el
# usuario fixture que la prueba. Mecanismo cerrado por security en OWU-115
# (nota id 30461) y detalles fijados por el architect (nota-architect-plan.md
# id 30602, OWU-95): es lo que hay aquí, literal.
#
# Reconcilia (idempotente):
#   1. cliente PUBLICO `openwebui-ios`: PKCE S256, redirect EXACTO y unico
#      owui-ios://auth/callback (sin comodin), NO es el `oauth2-proxy`
#      compartido (condicion 1 de OWU-115: la app tiene cliente propio);
#      mappers `email` y `groups` (full.path) en el access token Y en userinfo
#      (el exchange de OWUI llama SIEMPRE a userinfo); fullScopeAllowed=false.
#   2. cliente CONFIDENCIAL `openwebui-ios-owui`: el que usa Open WebUI para
#      validar el token del usuario (userinfo/introspeccion). Sin redirect:
#      nunca autoriza navegadores. Su secreto llega por el Secret del
#      ExternalSecret de arriba (item 1Password
#      keycloak-next-openwebui-ios-owui, campo client_secret; lo escribe
#      security) y se re-aplica en cada sync (patrón
#      agentgateway-write-fixture-user: Keycloak == 1Password).
#   3. usuario fixture `qa-owu95@e-dani.com` (grupo /edani-users): entra una
#      vez por la web antes de probar (el exchange NO auto-registra); su
#      contrasena vive solo en 1Password (item keycloak-next-qa-owu95, campo
#      password) y llega por FIXTURE_PASSWORD. El grupo /edani-users NO se
#      crea aqui: es un hecho del realm que ya existe (oauth2-proxy-chat lo
#      admite); si falta, este hook falla en seco.
#   4. (OWU-133) mecanismo de introspeccion cruzada del exchange: OWUI valida el
#      token del usuario llamando a token/introspection con sus credenciales
#      (openwebui-ios-owui), y Keycloak 26 solo contesta active=true si el
#      cliente que introspecta ESTA EN LA AUDIENCIA del token (medido: sin aud,
#      introspeccion responde {"active":false} y el exchange de OWUI devuelve
#      400 «Unable to determine which client the token was issued to»). Un
#      public client no lleva aud por defecto y el mapper legacy
#      oidc-audience-mapper ya no existe en KC 26; la via soportada es el
#      Audience Resolve del scope `basic`: un cliente entra en aud si el
#      usuario tiene un ROL DE ESE CLIENTE incluido en un scope asignado. De
#      ahi, cuatro piezas reconciliadas aqui:
#        - rol de cliente `ios-audience` en openwebui-ios-owui;
#        - client scope `openwebui-ios-exchange` (openid-connect) con ese rol
#          en sus scope-mappings;
#        - ese scope, ASIGNADO POR DEFECTO al publico openwebui-ios;
#        - el rol, concedido al grupo /edani-users (así TODOS los usuarios de
#          la app, no solo el fixture).
#      Cuerpo de los POST de role-mappings: REPRESENTACION COMPLETA del rol
#      (id,name,clientRole,composite,containerId) — con [ {"name":...} ] pelado
#      el servidor responde 404 (medido; mismo quirk documentado en
#      admin-keycloack-impersonation-grant.sh).
# Y VERIFICA antes de dar el OK (falla si no): los booleanos de ambos clientes,
# el redirect exacto del publico, PKCE S256, los mappers presentes, las cuatro
# piezas del mecanismo de audiencia, y las claims del token de ejemplo del
# usuario fixture (evaluate-scopes): access token con azp=openwebui-ios,
# aud=openwebui-ios-owui (la regresion de OWU-133), email y groups
# /edani-users; userinfo con email y groups (lo que el exchange va a leer).
#
# OJO: corre DENTRO de la imagen de Keycloak, que no trae awk ni jq (SC-1215).
# Solo kcadm + sed/grep/tr/wc/rm/sleep. Nunca imprime secretos ni tokens:
# solo veredictos.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
PUBLIC_CLIENT_ID="${PUBLIC_CLIENT_ID:-openwebui-ios}"
CONFIDENTIAL_CLIENT_ID="${CONFIDENTIAL_CLIENT_ID:-openwebui-ios-owui}"
REDIRECT_URI="${REDIRECT_URI:-owui-ios://auth/callback}"
GROUP_PATH="${GROUP_PATH:-/edani-users}"
FIXTURE_USERNAME="${FIXTURE_USERNAME:-qa-owu95@e-dani.com}"
# Nombres de perfil del fixture: fijos, no secretos (Keycloak 26 los exige para
# que el login no caiga en «Update Account Information»).
PROFILE_FIRST_NAME="QA"
PROFILE_LAST_NAME="OWU95 Fixture"
EMAIL_MAPPER=openwebui-ios-email
GROUPS_MAPPER=openwebui-ios-groups
# OWU-133: piezas del mecanismo de introspeccion cruzada (ver cabecera 4).
# Inmutables tras el primer merge: renombrarlas es cambio de contrato.
AUDIENCE_ROLE="${AUDIENCE_ROLE:-ios-audience}"
AUDIENCE_SCOPE="${AUDIENCE_SCOPE:-openwebui-ios-exchange}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-openwebui-ios-admin.config
KCADM_OUT=/tmp/kcadm-openwebui-ios-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"

progress() {
  printf '{"client_id":"%s","stage":"%s"}\n' "${1}" "$2"
}

# Inmutables (contrato con dgx-infra k8s/apps/chat/deployment.yaml y con la
# app): renombrarlos despues del primer merge es un cambio de contrato.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${PUBLIC_CLIENT_ID}" = "openwebui-ios" ] || fail "PUBLIC_CLIENT_ID is immutable"
[ "${CONFIDENTIAL_CLIENT_ID}" = "openwebui-ios-owui" ] || fail "CONFIDENTIAL_CLIENT_ID is immutable"
[ "${REDIRECT_URI}" = "owui-ios://auth/callback" ] || fail "REDIRECT_URI is immutable"
[ "${GROUP_PATH}" = "/edani-users" ] || fail "GROUP_PATH is immutable"
[ "${FIXTURE_USERNAME}" = "qa-owu95@e-dani.com" ] || fail "FIXTURE_USERNAME is immutable"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

# `-q clientId=` es un filtro de SUBCADENA en el servidor (dgx-messages-client
# lo documenta): aqui es obligatorio porque `openwebui-ios` es prefijo exacto
# de `openwebui-ios-owui` y una busqueda por subcadena los confundiria. Se
# piden id,clientId y se casa el clientId exacto.
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

upsert_public_client() {
  progress "${PUBLIC_CLIENT_ID}" upsert
  uuid="$(resolve_client_exact "${PUBLIC_CLIENT_ID}")"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${PUBLIC_CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=true \
    -s standardFlowEnabled=true \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=false \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s "redirectUris=[\"${REDIRECT_URI}\"]" \
    -s 'attributes."pkce.code.challenge.method"=S256' >/dev/null 2>&1 || \
    fail "failed to ${action} public client ${PUBLIC_CLIENT_ID}"
  PUBLIC_UUID="$(require_client_exact "${PUBLIC_CLIENT_ID}")"
  # email y groups: access token Y userinfo (el exchange de OWUI llama SIEMPRE
  # a userinfo — nota del architect id 30602 §3). No van al id token: la app no
  # los necesita ahi y OWUI no lo lee.
  upsert_mapper "${PUBLIC_UUID}" "${EMAIL_MAPPER}" oidc-usermodel-attribute-mapper \
    -s 'config."claim.name"=email' \
    -s 'config."user.attribute"=email' \
    -s 'config."access.token.claim"=true' \
    -s 'config."userinfo.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=false'
  upsert_mapper "${PUBLIC_UUID}" "${GROUPS_MAPPER}" oidc-group-membership-mapper \
    -s 'config."claim.name"=groups' \
    -s 'config."full.path"=true' \
    -s 'config."access.token.claim"=true' \
    -s 'config."userinfo.token.claim"=true' \
    -s 'config."id.token.claim"=false' \
    -s 'config."introspection.token.claim"=false'
}

upsert_confidential_client() {
  progress "${CONFIDENTIAL_CLIENT_ID}" upsert
  uuid="$(resolve_client_exact "${CONFIDENTIAL_CLIENT_ID}")"
  endpoint=clients
  action=create
  if [ -n "${uuid}" ]; then
    endpoint="clients/${uuid}"
    action=update
  fi
  # El secreto se re-aplica SIEMPRE (ensure): Keycloak == 1Password, patron
  # agentgateway-write-fixture-user (la clase de incidente SC-1635/SC-1645 fue
  # una deriva Keycloak-vs-1Password). Nunca pasa por stdout: kcadm lo recibe
  # por argv y su respuesta se descarta.
  "${KCADM}" "${action}" "${endpoint}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "clientId=${CONFIDENTIAL_CLIENT_ID}" \
    -s enabled=true \
    -s publicClient=false \
    -s standardFlowEnabled=false \
    -s implicitFlowEnabled=false \
    -s directAccessGrantsEnabled=false \
    -s serviceAccountsEnabled=true \
    -s fullScopeAllowed=false \
    -s protocol=openid-connect \
    -s 'redirectUris=[]' \
    -s 'webOrigins=[]' \
    -s "secret=${OWUI_IOS_OWUI_CLIENT_SECRET}" >/dev/null 2>&1 || \
    fail "failed to ${action} confidential client ${CONFIDENTIAL_CLIENT_ID}"
  CONFIDENTIAL_UUID="$(require_client_exact "${CONFIDENTIAL_CLIENT_ID}")"
}

verify_public_client() {
  PUBLIC_UUID="$(require_client_exact "${PUBLIC_CLIENT_ID}")"
  assert_client_boolean "${PUBLIC_UUID}" enabled true
  assert_client_boolean "${PUBLIC_UUID}" publicClient true
  assert_client_boolean "${PUBLIC_UUID}" standardFlowEnabled true
  assert_client_boolean "${PUBLIC_UUID}" implicitFlowEnabled false
  assert_client_boolean "${PUBLIC_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${PUBLIC_UUID}" serviceAccountsEnabled false
  assert_client_boolean "${PUBLIC_UUID}" fullScopeAllowed false
  # Redirect EXACTO: ni comodin ni una segunda URI colada a mano (condicion 1
  # de OWU-115).
  assert_exact_list "${PUBLIC_UUID}" redirectUris "${REDIRECT_URI}"
  # OJO kcadm 26.6.2 (dgx-messages-client.sh): el campo-objeto `attributes` sin
  # subcampos se imprime vacio por el filtro cliente de kcadm; se casa sobre la
  # representacion COMPLETA (sin --fields), que lleva el secreto — NUNCA se
  # imprime, solo se grep-a.
  client="$(kget "clients/${PUBLIC_UUID}" --format json | tr -d '\n')"
  printf '%s' "${client}" | grep -Eq '"pkce\.code\.challenge\.method"[[:space:]]*:[[:space:]]*"S256"' || \
    { unset client; fail "public client pkce.code.challenge.method is not S256"; }
  unset client
  [ -n "$(mapper_uuid_optional "${PUBLIC_UUID}" "${EMAIL_MAPPER}")" ] || fail "email mapper missing on ${PUBLIC_CLIENT_ID}"
  [ -n "$(mapper_uuid_optional "${PUBLIC_UUID}" "${GROUPS_MAPPER}")" ] || fail "groups mapper missing on ${PUBLIC_CLIENT_ID}"
}

verify_confidential_client() {
  CONFIDENTIAL_UUID="$(require_client_exact "${CONFIDENTIAL_CLIENT_ID}")"
  assert_client_boolean "${CONFIDENTIAL_UUID}" enabled true
  assert_client_boolean "${CONFIDENTIAL_UUID}" publicClient false
  assert_client_boolean "${CONFIDENTIAL_UUID}" standardFlowEnabled false
  assert_client_boolean "${CONFIDENTIAL_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CONFIDENTIAL_UUID}" serviceAccountsEnabled true
  assert_client_boolean "${CONFIDENTIAL_UUID}" fullScopeAllowed false
  # Sin redirect: solo llama a userinfo/introspeccion, nunca autoriza
  # navegadores.
  assert_empty_list "${CONFIDENTIAL_UUID}" redirectUris
}

# --- usuario fixture (patrón agentgateway-write-fixture-user.sh) ------------

resolve_fixture_user_id() {
  ids="$(kget users -q "username=${FIXTURE_USERNAME}" -q exact=true --fields id --format csv --noquotes 2>/dev/null | nonempty_lines)" || return 1
  case "$(printf '%s\n' "${ids}" | sed '/^[[:space:]]*$/d' | wc -l | tr -d '[:space:]')" in
    0) return 1 ;;
    1) printf '%s\n' "${ids}" | sed -n '1p' ;;
    # 2: un realm que el contrato no describe; nunca confundir con "ausente".
    *) return 2 ;;
  esac
}

fixture_user_field() {
  kget "users/${FIXTURE_USER_ID}" --fields "$1" --format csv --noquotes | nonempty_lines
}

assert_fixture_is_human() {
  sa_client="$(fixture_user_field serviceAccountClientId)"
  case "${sa_client}" in
    ""|null) ;;
    *) fail "${FIXTURE_USERNAME} is the service account of ${sa_client}: the fixture must be a human user" ;;
  esac
}

create_fixture_user() {
  # requiredActions=[] y emailVerified=true para que el login del fixture nunca
  # dispare UPDATE_PASSWORD/VERIFY_EMAIL; los nombres de perfil evitan
  # UPDATE_PROFILE. La respuesta se captura, nunca se imprime.
  if ! "${KCADM}" create users --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "username=${FIXTURE_USERNAME}" -s "email=${FIXTURE_USERNAME}" \
    -s enabled=true -s emailVerified=true -s 'requiredActions=[]' \
    -s "firstName=${PROFILE_FIRST_NAME}" -s "lastName=${PROFILE_LAST_NAME}" \
    > "${KCADM_OUT}" 2>&1; then
    fail "failed to create ${FIXTURE_USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
}

profile_names_match() {
  [ "$(fixture_user_field firstName)" = "${PROFILE_FIRST_NAME}" ] && \
    [ "$(fixture_user_field lastName)" = "${PROFILE_LAST_NAME}" ]
}

apply_profile_names() {
  if ! "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "firstName=${PROFILE_FIRST_NAME}" -s "lastName=${PROFILE_LAST_NAME}" \
    > "${KCADM_OUT}" 2>&1; then
    fail "failed to set the profile names of ${FIXTURE_USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
  profile_names_match || \
    fail "post-update assertion failed: ${FIXTURE_USERNAME} lacks the fixed profile names"
}

apply_password() {
  # KC_CLI_PASSWORD es el default de entorno de kcadm 26 para --new-password:
  # el valor llega al servidor sin entrar en argv (SC-1215). No es temporal:
  # el login del fixture tiene que ser scriptable.
  [ -n "${FIXTURE_PASSWORD:-}" ] || \
    fail "FIXTURE_PASSWORD is empty: refusing to apply the fixture password"
  if ! KC_CLI_PASSWORD="${FIXTURE_PASSWORD}" "${KCADM}" set-password \
    --config "${ADMIN_CONFIG}" -r "${REALM}" --userid "${FIXTURE_USER_ID}" \
    > "${KCADM_OUT}" 2>&1; then
    fail "failed to apply the fixture password: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
  fi
}

group_id_for() {
  # El grupo /edani-users es un hecho del realm que ya existe (oauth2-proxy-chat
  # lo admite en allowed_groups); NUNCA se crea aqui. Si falta, fail en seco:
  # quien lo posee decide.
  kget groups --fields id,path --format csv --noquotes 2>/dev/null | nonempty_lines | \
    while IFS=, read -r gid gpath; do
      [ "${gpath}" = "$1" ] && printf '%s\n' "${gid}"
    done | sed -n '1p'
}

user_group_has() {
  kget "users/${FIXTURE_USER_ID}/groups" --fields path --format csv --noquotes 2>/dev/null | \
    nonempty_lines | grep -qxF "${GROUP_PATH}"
}

ensure_fixture_in_group() {
  if user_group_has; then
    return 0
  fi
  gid="$(group_id_for "${GROUP_PATH}")"
  [ -n "${gid}" ] || fail "group ${GROUP_PATH} is missing from realm ${REALM}: it is owned outside this repo (oauth2-proxy-chat admits it); refusing to create it"
  # PUT, no POST: la REST asocia grupos con PUT /users/{uid}/groups/{gid}
  # (sso-app-common.sh: `create` mandaria POST y daria 405).
  "${KCADM}" update "users/${FIXTURE_USER_ID}/groups/${gid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    >/dev/null 2>&1 || fail "failed to put ${FIXTURE_USERNAME} into ${GROUP_PATH}"
  user_group_has || fail "post-write assertion failed: ${FIXTURE_USERNAME} is not in ${GROUP_PATH}"
}

# --- OWU-133: mecanismo de introspeccion cruzada (cabecera, punto 4) ---------
# El Audience Resolve del scope `basic` mete un cliente en `aud` si el usuario
# tiene un rol DE ESE CLIENTE incluido en un scope asignado al cliente que
# autentica. Cuatro piezas: rol en el confidencial, scope openid-connect con
# ese rol en sus scope-mappings, el scope asignado por defecto al publico, y el
# rol concedido al grupo /edani-users (todos los usuarios de la app).

resolve_role_id() {
  # $1 = uuid del cliente, $2 = nombre del rol. Imprime el id o vacio.
  kget "clients/$1/roles/$2" --fields id --format csv --noquotes 2>/dev/null | nonempty_lines | sed -n '1p'
}

resolve_scope_id_exact() {
  # $1 = nombre del scope. `-q name=` puede no filtrar en el servidor (no es
  # parametro de la REST de client-scopes): se casa el nombre EXACTO sobre las
  # filas devueltas (criterio de resolve_client_exact).
  rows="$(kget client-scopes --fields id,name --format csv --noquotes 2>/dev/null | \
    nonempty_lines | while IFS=, read -r sid sname; do
      [ "${sname}" = "$1" ] && printf '%s\n' "${sid}"
    done)"
  [ "$(printf '%s\n' "${rows}" | line_count)" -le 1 ] || fail "duplicate client scope $1"
  printf '%s' "${rows}"
}

role_representation_body() {
  # POST de role-mappings con representacion COMPLETA del rol: con [ {"name":...} ]
  # pelado el servidor responde 404 (medido OWU-133; mismo quirk documentado en
  # admin-keycloack-impersonation-grant.sh). $1 = id del rol, $2 = uuid del
  # cliente contenedor. Escribe en ROLE_BODY.
  printf '[{"id":"%s","name":"%s","clientRole":true,"composite":false,"containerId":"%s"}]' \
    "$1" "${AUDIENCE_ROLE}" "$2" > "${ROLE_BODY}"
}

scope_mapping_has_role() {
  kget "client-scopes/$1/scope-mappings/clients/${CONFIDENTIAL_UUID}" \
    --fields name --format csv --noquotes 2>/dev/null | nonempty_lines | grep -qxF "${AUDIENCE_ROLE}"
}

default_scope_has() {
  kget "clients/${PUBLIC_UUID}/default-client-scopes" --fields name \
    --format csv --noquotes 2>/dev/null | nonempty_lines | grep -qxF "$1"
}

group_has_audience_role() {
  gid="$(group_id_for "${GROUP_PATH}")"
  [ -n "${gid}" ] || return 1
  kget "groups/${gid}/role-mappings/clients/${CONFIDENTIAL_UUID}" \
    --fields name --format csv --noquotes 2>/dev/null | nonempty_lines | grep -qxF "${AUDIENCE_ROLE}"
}

ensure_audience_mechanism() {
  progress "${CONFIDENTIAL_CLIENT_ID}" audience
  ROLE_BODY=/tmp/kcadm-openwebui-ios-role-body.json
  KCADM_TMP_FILES="${KCADM_TMP_FILES} ${ROLE_BODY}"
  ROLE_ID="$(resolve_role_id "${CONFIDENTIAL_UUID}" "${AUDIENCE_ROLE}")"
  if [ -z "${ROLE_ID}" ]; then
    "${KCADM}" create "clients/${CONFIDENTIAL_UUID}/roles" --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "name=${AUDIENCE_ROLE}" \
      -s description="Audiencia del exchange nativo iOS (introspeccion cruzada OWUI, OWU-133)" \
      >/dev/null 2>&1 || fail "failed to create client role ${AUDIENCE_ROLE}"
    ROLE_ID="$(resolve_role_id "${CONFIDENTIAL_UUID}" "${AUDIENCE_ROLE}")"
    [ -n "${ROLE_ID}" ] || fail "post-create assertion failed: role ${AUDIENCE_ROLE} is not resolvable"
  fi
  SCOPE_ID="$(resolve_scope_id_exact "${AUDIENCE_SCOPE}")"
  if [ -z "${SCOPE_ID}" ]; then
    "${KCADM}" create client-scopes --config "${ADMIN_CONFIG}" -r "${REALM}" \
      -s "name=${AUDIENCE_SCOPE}" \
      -s description="Rol de audiencia para el exchange nativo iOS (OWU-133)" \
      -s protocol=openid-connect >/dev/null 2>&1 || fail "failed to create client scope ${AUDIENCE_SCOPE}"
    SCOPE_ID="$(resolve_scope_id_exact "${AUDIENCE_SCOPE}")"
    [ -n "${SCOPE_ID}" ] || fail "post-create assertion failed: scope ${AUDIENCE_SCOPE} is not resolvable"
  fi
  if ! scope_mapping_has_role "${SCOPE_ID}"; then
    role_representation_body "${ROLE_ID}" "${CONFIDENTIAL_UUID}"
    "${KCADM}" create "client-scopes/${SCOPE_ID}/scope-mappings/clients/${CONFIDENTIAL_UUID}" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" -f "${ROLE_BODY}" >/dev/null 2>&1 || \
      fail "failed to map ${AUDIENCE_ROLE} into scope ${AUDIENCE_SCOPE}"
    scope_mapping_has_role "${SCOPE_ID}" || \
      fail "post-write assertion failed: ${AUDIENCE_ROLE} not in ${AUDIENCE_SCOPE}"
  fi
  if ! default_scope_has "${AUDIENCE_SCOPE}"; then
    # PUT, no POST: la REST asigna scopes con PUT /clients/{uuid}/default-client-scopes/{scopeId}
    # (mismo criterio que ensure_fixture_in_group; `create` mandaria POST y daria 404/405).
    "${KCADM}" update "clients/${PUBLIC_UUID}/default-client-scopes/${SCOPE_ID}" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" >/dev/null 2>&1 || \
      fail "failed to put default scope ${AUDIENCE_SCOPE} on ${PUBLIC_CLIENT_ID}"
    default_scope_has "${AUDIENCE_SCOPE}" || \
      fail "post-write assertion failed: ${AUDIENCE_SCOPE} is not a default scope of ${PUBLIC_CLIENT_ID}"
  fi
  if ! group_has_audience_role; then
    gid="$(group_id_for "${GROUP_PATH}")"
    [ -n "${gid}" ] || fail "group ${GROUP_PATH} is missing from realm ${REALM}: it is owned outside this repo; refusing to create it"
    role_representation_body "${ROLE_ID}" "${CONFIDENTIAL_UUID}"
    "${KCADM}" create "groups/${gid}/role-mappings/clients/${CONFIDENTIAL_UUID}" \
      --config "${ADMIN_CONFIG}" -r "${REALM}" -f "${ROLE_BODY}" >/dev/null 2>&1 || \
      fail "failed to grant ${AUDIENCE_ROLE} to group ${GROUP_PATH}"
    group_has_audience_role || \
      fail "post-write assertion failed: ${GROUP_PATH} lacks ${AUDIENCE_ROLE}"
  fi
}

verify_audience_mechanism() {
  [ -n "$(resolve_role_id "${CONFIDENTIAL_UUID}" "${AUDIENCE_ROLE}")" ] || \
    fail "audit: client role ${AUDIENCE_ROLE} is missing on ${CONFIDENTIAL_CLIENT_ID}"
  SCOPE_ID="$(resolve_scope_id_exact "${AUDIENCE_SCOPE}")"
  [ -n "${SCOPE_ID}" ] || fail "audit: client scope ${AUDIENCE_SCOPE} is missing"
  scope_mapping_has_role "${SCOPE_ID}" || \
    fail "audit: ${AUDIENCE_SCOPE} does not map ${AUDIENCE_ROLE}"
  default_scope_has "${AUDIENCE_SCOPE}" || \
    fail "audit: ${AUDIENCE_SCOPE} is not a default scope of ${PUBLIC_CLIENT_ID}"
  group_has_audience_role || \
    fail "audit: group ${GROUP_PATH} lacks ${AUDIENCE_ROLE}: tokens of the app would carry no aud and the exchange would answer 400"
}

# --- verificacion con el token de ejemplo -----------------------------------
# Admin API "Client scopes > Evaluate": las CLAIMS (JSON decodificado, sin
# firma) que llevaria un token del cliente publico para el usuario fixture. No
# crea sesion ni token utilizable (dgx-messages-client.sh).
example_token() {
  # $1 = endpoint (generate-example-access-token | generate-example-userinfo)
  kget "clients/${PUBLIC_UUID}/evaluate-scopes/$1" \
    -q scope=openid -q "userId=${FIXTURE_USER_ID}" | tr -d '\n'
}

verify_example_claims() {
  access="$(example_token generate-example-access-token)" || fail "example access token failed"
  [ -n "${access}" ] || fail "example access token is empty"
  printf '%s' "${access}" | grep -Eq '"azp"[[:space:]]*:[[:space:]]*"'"${PUBLIC_CLIENT_ID}"'"' || \
    fail "example access token has wrong azp (expected ${PUBLIC_CLIENT_ID})"
  # OWU-133: sin aud=openwebui-ios-owui la introspeccion cruzada de OWUI
  # responde active=false y el exchange 400 — es la regresion que vigila esto.
  # forma cadena (un solo aud, KC 26) o array (si alguien anade otro).
  printf '%s' "${access}" | grep -Eq '"aud"[[:space:]]*:[[:space:]]*(\[[^]]*)?"'"${CONFIDENTIAL_CLIENT_ID}"'"' || \
    fail "example access token has no aud=${CONFIDENTIAL_CLIENT_ID}: cross-client introspection would fail (OWU-133)"
  printf '%s' "${access}" | grep -Eq '"email"[[:space:]]*:[[:space:]]*"'"${FIXTURE_USERNAME}"'"' || \
    fail "example access token has no email claim for ${FIXTURE_USERNAME}"
  printf '%s' "${access}" | grep -Eq '"groups"[[:space:]]*:[[:space:]]*\[[^]]*"'"${GROUP_PATH}"'"' || \
    fail "example access token has no ${GROUP_PATH} group with full path"
  unset access
  userinfo="$(example_token generate-example-userinfo)" || fail "example userinfo failed"
  [ -n "${userinfo}" ] || fail "example userinfo is empty"
  # El exchange de OWUI llama SIEMPRE a userinfo (cota OWU-115): email y
  # groups tienen que salir ahi, no solo en el access token.
  printf '%s' "${userinfo}" | grep -Eq '"email"[[:space:]]*:[[:space:]]*"'"${FIXTURE_USERNAME}"'"' || \
    fail "example userinfo has no email claim for ${FIXTURE_USERNAME}"
  printf '%s' "${userinfo}" | grep -Eq '"groups"[[:space:]]*:[[:space:]]*\[[^]]*"'"${GROUP_PATH}"'"' || \
    fail "example userinfo has no ${GROUP_PATH} group"
  unset userinfo
}

report() {
  printf '{"realm":"%s","public_client":"%s","confidential_client":"%s","fixture":"%s","stage":"%s"}\n' \
    "${REALM}" "${PUBLIC_CLIENT_ID}" "${CONFIDENTIAL_CLIENT_ID}" "${FIXTURE_USERNAME}" "$1"
}

login_admin

case "${MODE}" in
  ensure)
    # Fallar ANTES de cualquier mutacion si falta una credencial.
    [ -n "${OWUI_IOS_OWUI_CLIENT_SECRET:-}" ] || \
      fail "OWUI_IOS_OWUI_CLIENT_SECRET is empty: refusing to reconcile the confidential client (1Password item keycloak-next-openwebui-ios-owui, written by security)"
    [ -n "${FIXTURE_PASSWORD:-}" ] || \
      fail "FIXTURE_PASSWORD is empty: refusing to reconcile the fixture (1Password item keycloak-next-qa-owu95)"
    upsert_public_client
    upsert_confidential_client
    verify_public_client
    verify_confidential_client
    # OWU-133: audiencia para la introspeccion cruzada del exchange (cabecera 4).
    ensure_audience_mechanism
    # Fixture: crear si falta, re-enable, nombres, contrasena SIEMPRE (Keycloak
    # == 1Password), y al grupo.
    if FIXTURE_USER_ID="$(resolve_fixture_user_id)"; then
      created=false
    else
      case $? in
        1)
          create_fixture_user
          FIXTURE_USER_ID="$(resolve_fixture_user_id)" || \
            fail "post-create assertion failed: ${FIXTURE_USERNAME} is not resolvable by exact username after create"
          created=true
          ;;
        *)
          fail "the exact username ${FIXTURE_USERNAME} does not resolve to at most one user: refusing to continue"
          ;;
      esac
    fi
    assert_fixture_is_human
    if [ "$(fixture_user_field enabled)" != "true" ]; then
      if ! "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s enabled=true > "${KCADM_OUT}" 2>&1; then
        fail "failed to re-enable ${FIXTURE_USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      fi
      [ "$(fixture_user_field enabled)" = "true" ] || \
        fail "post-update assertion failed: ${FIXTURE_USERNAME} is still disabled"
    fi
    profile_names_match || apply_profile_names
    apply_password
    ensure_fixture_in_group
    verify_example_claims
    report "ensure done (fixture created: ${created})"
    ;;
  audit)
    verify_public_client
    verify_confidential_client
    verify_audience_mechanism
    FIXTURE_USER_ID="$(resolve_fixture_user_id)" || \
      fail "audit: ${FIXTURE_USERNAME} does not exist or does not resolve cleanly in realm ${REALM}"
    assert_fixture_is_human
    [ "$(fixture_user_field enabled)" = "true" ] || fail "audit: ${FIXTURE_USERNAME} is disabled"
    user_group_has || fail "audit: ${FIXTURE_USERNAME} is not in ${GROUP_PATH}"
    # La contrasena no se puede leer por API: su aplicacion es trabajo del
    # ensure (igual que en agentgateway-write-fixture-user.sh).
    verify_example_claims
    report "audit done"
    ;;
  rollback)
    # Desactiva los dos clientes y al fixture; NUNCA borra: eliminar un
    # principal es decision del CTO (PRINCIPALS.md).
    for cid in "${PUBLIC_CLIENT_ID}" "${CONFIDENTIAL_CLIENT_ID}"; do
      uuid="$(resolve_client_exact "${cid}")"
      if [ -n "${uuid}" ]; then
        "${KCADM}" update "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
          -s enabled=false > "${KCADM_OUT}" 2>&1 || \
          fail "rollback: failed to disable ${cid}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
        assert_client_boolean "${uuid}" enabled false
      fi
    done
    if FIXTURE_USER_ID="$(resolve_fixture_user_id)"; then
      if [ "$(fixture_user_field enabled)" = "true" ]; then
        "${KCADM}" update "users/${FIXTURE_USER_ID}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
          -s enabled=false > "${KCADM_OUT}" 2>&1 || \
          fail "rollback: failed to disable ${FIXTURE_USERNAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
        [ "$(fixture_user_field enabled)" = "false" ] || \
          fail "rollback: ${FIXTURE_USERNAME} is still enabled"
      fi
    fi
    report "rollback done"
    ;;
esac
