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
#      EXACTO y unico dgx://oauth/callback (sin comodín, el esquema que ya usa
#      dgx-app), NO es el `oauth2-proxy` compartido; fullScopeAllowed=false:
#      el token del usuario solo lleva los roles del scope del cliente;
#   2. mapper `aud-mcp` con el patron de audience de la casa
#      (upsert_audience_mapper de keycloak-reconcile-lib.sh):
#      aud = mcp.lan.e-dani.com en access e introspección (lo que verifica el
#      AgentGateway en la ruta /photos, k8s-agentgateway-pocharlies#247);
#   3. scope de roles del cliente: agentgateway-read:photos +
#      photos-confirm-delete mapeados con ensure_role_in_client_scope (con
#      fullScopeAllowed=false esto es lo que hace viajar los roles en el token;
#      la ruta /photos exige el primero y el gate de borrado G1 del architect
#      lee el segundo del JWT);
#   4. grant directo de agentgateway-read:photos a Daniel (subject
#      e51253a7-c137-4c6c-9fb9-af9cecd3b147, username me@e-dani.com, mismo pin
#      que photos-confirm-delete-grant-daniel.sh), el usuario de la app. Es la
#      única concesión que aplica este hook; photos-confirm-delete NO se
#      concede aquí (lo posee photos-confirm-delete-grant-daniel.sh) — este
#      hook solo lo MAPEA en el scope del cliente, que no es una concesión.
#   Y VERIFICA antes de dar el OK (falla si no): los booleanos del cliente, el
#   redirect exacto, webOrigins vacío, PKCE S256, el mapper con su audience,
#   los dos roles en el scope del cliente, el grant directo del usuario, y las
#   claims del token de ejemplo (evaluate-scopes, idiom
#   openwebui-ios-client.sh): aud y los dos roles (lo que el gateway va a leer).
#
# Los dos roles los ALTAN y posee el PostSync agentgateway-read-grants.sh
# (wave 20) y photos-confirm-delete-grant-daniel.sh (wave 25): este hook wave
# 25 los exige existentes (role_exists) y no los crea — fail-closed: si
# faltan, el sync está a medias y hay que arreglarlo, no parchearlo desde aquí.
# La titularidad humana de agentgateway-read:photos está declarada en
# ROLES.yaml y PRINCIPALS.md (SC-4414) y tolerada por la allowlist revisada de
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
MAPPER_NAME="${MAPPER_NAME:-aud-mcp}"
AGENTGATEWAY_AUDIENCE="${AGENTGATEWAY_AUDIENCE:-mcp.lan.e-dani.com}"
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
. "${0%/*}/keycloak-reconcile-lib.sh"

# Inmutables (contrato con la app pocharlies-org/photos-ios, PhotosAuth.swift,
# y con el gateway): renombrarlos despues del primer merge es un cambio de
# contrato.
[ "${REALM}" = "edani" ] || fail "REALM is immutable for this reconciler"
[ "${CLIENT_ID}" = "photos-app" ] || fail "CLIENT_ID is immutable"
[ "${REDIRECT_URI}" = "dgx://oauth/callback" ] || fail "REDIRECT_URI is immutable"
[ "${MAPPER_NAME}" = "aud-mcp" ] || fail "MAPPER_NAME is immutable"
[ "${AGENTGATEWAY_AUDIENCE}" = "mcp.lan.e-dani.com" ] || fail "AGENTGATEWAY_AUDIENCE is immutable"
[ "${SCOPED_ROLE_NAMES}" = "agentgateway-read:photos,photos-confirm-delete" ] || \
  fail "SCOPED_ROLE_NAMES is immutable; the token contract of photos-ios is fixed by INFRA-402/INFRA-403"
[ "${GRANT_ROLE_NAME}" = "agentgateway-read:photos" ] || fail "GRANT_ROLE_NAME is immutable"
[ "${USER_ID}" = "e51253a7-c137-4c6c-9fb9-af9cecd3b147" ] || fail "USER_ID is immutable"
[ "${USER_NAME}" = "me@e-dani.com" ] || fail "USER_NAME is immutable"
case "${MODE}" in
  ensure|audit|rollback) ;;
  *) fail "MODE must be ensure, audit, or rollback" ;;
esac

# Los roles del contrato los ALTAN otros reconciliadores (wave 20 y su hermano
# wave 25); este hook los exige y no los crea (role_exists, fail-closed).
assert_roles_exist() {
  for role in $(printf '%s\n' "${SCOPED_ROLE_NAMES}" | tr ',' ' '); do
    role_exists "${role}" || \
      fail "${role} is missing from the realm: its owner reconciler has not run (this hook never creates it)"
  done
}

user_field() {
  kget "users/${USER_ID}" --fields "$1" --format csv --noquotes | nonempty_lines
}

# Nunca crea, edita ni habilita usuarios (OWU-80): si el subject fijado no está
# o no es el humano esperado, falla en seco.
resolve_user() {
  kget "users/${USER_ID}" --fields id >/dev/null 2>&1 || \
    fail "user ${USER_ID} does not exist in realm ${REALM}: refusing to create a human user"
  [ "$(user_field username)" = "${USER_NAME}" ] || \
    fail "user ${USER_ID} is not the pinned ${USER_NAME}: refusing to continue"
  [ "$(user_field enabled)" = "true" ] || fail "user ${USER_NAME} is disabled: refusing to grant"
  case "$(user_field serviceAccountClientId)" in
    ""|null) ;;
    *) fail "user ${USER_ID} is a service account: this hook grants to the human user only" ;;
  esac
}

user_has_direct_role() {
  kget "users/${USER_ID}/role-mappings/realm" \
    --fields name --format csv --noquotes | nonempty_lines | grep -Fxq "${GRANT_ROLE_NAME}"
}

upsert_client() {
  progress "${CLIENT_ID}" upsert
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
  CLIENT_UUID="$(require_client)"
  # Patron de audience de la casa (MAPPER_NAME + AGENTGATEWAY_AUDIENCE).
  upsert_audience_mapper
}

grant_daniel_read_role() {
  progress "${CLIENT_ID}" grant
  resolve_user
  if user_has_direct_role; then
    return 0
  fi
  # kcadm add-roles: el exit code no se fía (SC-1215); la lectura post-ensure
  # de verify_client_state es la aserción real.
  "${KCADM}" add-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
    --uid "${USER_ID}" --rolename "${GRANT_ROLE_NAME}" > "${KCADM_OUT}" 2>&1 || \
    fail "failed to map ${GRANT_ROLE_NAME} to ${USER_NAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
}

# Redirect EXACTO, webOrigins vacío y PKCE se casan sobre la representación
# COMPLETA del cliente (sin --fields): el filtro de kcadm pinta `attributes`
# vacío sin subcampos (dgx-messages-client.sh). NUNCA se imprime, solo se
# grep-a.
verify_client_list_fields() {
  client="$(kget "clients/${CLIENT_UUID}" --format json | tr -d '\n')"
  printf '%s' "${client}" | grep -Eq "\"redirectUris\"[[:space:]]*:[[:space:]]*\[\"${REDIRECT_URI}\"\]" || \
    { unset client; fail "client redirectUris is not exactly [\"${REDIRECT_URI}\"]"; }
  printf '%s' "${client}" | grep -Eq '"webOrigins"[[:space:]]*:[[:space:]]*\[\]' || \
    { unset client; fail "client webOrigins must be empty"; }
  printf '%s' "${client}" | grep -Eq '"pkce\.code\.challenge\.method"[[:space:]]*:[[:space:]]*"S256"' || \
    { unset client; fail "client pkce.code.challenge.method is not S256"; }
  unset client
}

verify_client_state() {
  CLIENT_UUID="$(require_client)"
  assert_client_boolean "${CLIENT_UUID}" enabled true
  assert_client_boolean "${CLIENT_UUID}" publicClient true
  assert_client_boolean "${CLIENT_UUID}" standardFlowEnabled true
  assert_client_boolean "${CLIENT_UUID}" implicitFlowEnabled false
  assert_client_boolean "${CLIENT_UUID}" directAccessGrantsEnabled false
  assert_client_boolean "${CLIENT_UUID}" serviceAccountsEnabled false
  assert_client_boolean "${CLIENT_UUID}" fullScopeAllowed false
  verify_client_list_fields
  [ -n "$(mapper_uuid_optional)" ] || fail "mapper ${MAPPER_NAME} missing on ${CLIENT_ID}"
  mapper="$(kget "clients/${CLIENT_UUID}/protocol-mappers/models/$(mapper_uuid_optional)" --format json | tr -d '\n')"
  printf '%s' "${mapper}" | grep -Eq "\"included\.custom\.audience\"[[:space:]]*:[[:space:]]*\"${AGENTGATEWAY_AUDIENCE}\"" || \
    { unset mapper; fail "mapper ${MAPPER_NAME} does not carry the audience ${AGENTGATEWAY_AUDIENCE}"; }
  unset mapper
  for role in $(printf '%s\n' "${SCOPED_ROLE_NAMES}" | tr ',' ' '); do
    role_scope_has_direct_role "${role}" || \
      fail "client role scope is missing ${role}"
  done
  # Grant directo del usuario (el otro lado del contrato del token).
  user_has_direct_role || \
    fail "post-ensure assertion failed: ${GRANT_ROLE_NAME} is not in the direct realm-role mappings of ${USER_NAME}"
}

verify_example_token() {
  # evaluate-scopes (idiom openwebui-ios-client.sh): simula la emisión del
  # access token del usuario por este cliente, sin credenciales. Es lo que el
  # gateway va a leer: la audience y los dos roles en realm_access.
  access="$(kget "clients/${CLIENT_UUID}/evaluate-scopes/generate-example-access-token" \
    -q scope=openid -q "userId=${USER_ID}" | tr -d '\n')" || fail "example access token failed"
  [ -n "${access}" ] || fail "example access token is empty"
  printf '%s' "${access}" | grep -Eq "\"azp\"[[:space:]]*:[[:space:]]*\"${CLIENT_ID}\"" || \
    fail "example access token has wrong azp (expected ${CLIENT_ID})"
  printf '%s' "${access}" | grep -Eq "\"aud\"[[:space:]]*:[[:space:]]*(\"${AGENTGATEWAY_AUDIENCE}\"|\[[^]]*\"${AGENTGATEWAY_AUDIENCE}\")" || \
    fail "example access token has no aud ${AGENTGATEWAY_AUDIENCE}"
  for role in $(printf '%s\n' "${SCOPED_ROLE_NAMES}" | tr ',' ' '); do
    # realm_access.roles: array de nombres; se casa el rol exacto entre comillas.
    printf '%s' "${access}" | grep -Eq "\"realm_access\"[^}]*\"roles\"[^]]*\"${role}\"" || \
      { unset access; fail "example access token does not carry realm role ${role}"; }
  done
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
    for role in $(printf '%s\n' "${SCOPED_ROLE_NAMES}" | tr ',' ' '); do
      ensure_role_in_client_scope "${role}"
    done
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
    uuid="$(resolve_client_optional)"
    if [ -n "${uuid}" ]; then
      "${KCADM}" update "clients/${uuid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
        -s enabled=false > "${KCADM_OUT}" 2>&1 || \
        fail "rollback: failed to disable ${CLIENT_ID}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      assert_client_boolean "${uuid}" enabled false
    fi
    if kget "users/${USER_ID}" --fields id >/dev/null 2>&1 && user_has_direct_role; then
      "${KCADM}" remove-roles --config "${ADMIN_CONFIG}" -r "${REALM}" \
        --uid "${USER_ID}" --rolename "${GRANT_ROLE_NAME}" > "${KCADM_OUT}" 2>&1 || \
        fail "rollback: failed to remove ${GRANT_ROLE_NAME} from ${USER_NAME}: server replied [$(tr '\n' ' ' < "${KCADM_OUT}")]"
      if user_has_direct_role; then
        fail "rollback: ${GRANT_ROLE_NAME} remains mapped to ${USER_NAME}"
      fi
    fi
    report "rollback done"
    ;;
esac
