#!/bin/sh
set -eu

umask 077

# SKIRM-15 — reconciler del SSO propio de skirmbooks en el realm `edani`.
#
# Tres cosas, todas idempotentes:
#   1. los grupos `/skirmbooks-users` y `/skirmbooks-admins` (la lista de
#      permisos del software fiscal, hasta ahora inexistente: skirmbooks heredaba
#      los grupos del dashboard);
#   2. el `redirect_uri` nuevo en el client `oauth2-proxy`, SIN pisar los que ya
#      estan (ver ensure_redirect_uri: ahi esta el riesgo real de este Job);
#   3. el mapper `oidc-group-membership-mapper` (full.path, id.token) para que
#      `allowed_groups` de oauth2-proxy vea los grupos, y la lista nominal de
#      miembros.
#
# Precedente del patron: synapse-sre-client.sh y openclaw-readonly-clients.sh.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
CLIENT_ID="${CLIENT_ID:-oauth2-proxy}"
REDIRECT_URI="${REDIRECT_URI:-https://skirmbooks.e-dani.com/oauth2/callback}"
# El callback de la cadena compartida. Sirve de canario: si tras escribir el
# array desaparece, el merge ha roto el login de las ~33 rutas de `sso-chain`.
CANARY_URI="${CANARY_URI:-https://auth-next.e-dani.com/oauth2/callback}"
USER_GROUP="${USER_GROUP:-/skirmbooks-users}"
ADMIN_GROUP="${ADMIN_GROUP:-/skirmbooks-admins}"
# Lista nominal. No es decision de infra quien firma la contabilidad: el default
# deja las llaves en el dueno del realm y anade la cuenta fiscal con la que Dani
# quiere entrar a skirmbooks. Se cambia por env, no por codigo.
ADMIN_EMAILS="${ADMIN_EMAILS:-me@e-dani.com}"
USER_EMAILS="${USER_EMAILS:-daniel.ibanez@alphalinkcrossfit.com}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-skirmbooks-sso-admin.config

cleanup() {
  rm -f "${ADMIN_CONFIG}"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

# Nada de esto es renomeable en caliente: oauth2-proxy-skirmbooks-config fija los
# nombres de grupo y el redirect, y cambiarlos aqui sin cambiarlos alli deja a
# skirmbooks sin acceso.
[ "${CLIENT_ID}" = "oauth2-proxy" ] || fail "CLIENT_ID is immutable"
[ "${REDIRECT_URI}" = "https://skirmbooks.e-dani.com/oauth2/callback" ] || fail "REDIRECT_URI is immutable"
[ "${USER_GROUP}" = "/skirmbooks-users" ] || fail "USER_GROUP is immutable"
[ "${ADMIN_GROUP}" = "/skirmbooks-admins" ] || fail "ADMIN_GROUP is immutable"
case "${MODE}" in
  ensure|audit) ;;
  *) fail "unsupported MODE=${MODE}" ;;
esac

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

# --- grupos ---------------------------------------------------------------
# GET /groups no admite ?path=, asi que se lista y se casa el path exacto. El
# path no lleva comas, luego CSV `id,path` parte bien con el id delante.
# OJO: la imagen de Keycloak NO trae awk (el Job real fallo con
# `awk: command not found`). Solo sed/grep/tr/head/wc, que si hay. Se quita el
# sufijo `,path` con sed y se imprimen unicamente las lineas donde la sustitucion
# cupo (`t` sale al final si hubo cambio, `d` borra las demas) — POSIX, vale
# tambien para el sed de busybox de la imagen.
group_id_for() {
  kget groups --fields id,path --format csv --noquotes 2>/dev/null \
    | sed -e "s#,[[:space:]]*${1}[[:space:]]*\$##" -e t -e d \
    | sed -e 's/[[:space:]]*$//' | head -1
}

ensure_group() {
  path="$1"
  gid="$(group_id_for "${path}")"
  if [ -n "${gid}" ]; then
    # Los mensajes van a stderr: quien llama captura el gid con
    # `gid="$(ensure_group ...)"`, y cualquier printf a stdout se colaria dentro
    # del gid (de ahi el 404 del PUT de membresia: el id llegaba con la linea de
    # log pegada). Solo el gid puro sale por stdout.
    printf 'grupo %s ya existe (%s)\n' "${path}" "${gid}" >&2
    printf '%s' "${gid}"
    return 0
  fi
  if [ "${MODE}" = "audit" ]; then
    fail "audit: group ${path} is missing"
  fi
  name="$(printf '%s' "${path}" | sed 's#.*/##')"
  "${KCADM}" create groups --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "name=${name}" >/dev/null 2>&1 || fail "failed to create group ${path}"
  gid="$(group_id_for "${path}")"
  [ -n "${gid}" ] || fail "group ${path} created but not resolvable"
  printf 'grupo %s creado (%s)\n' "${path}" "${gid}" >&2
  printf '%s' "${gid}"
}

# --- client ---------------------------------------------------------------
client_uuid() {
  kget clients -q "clientId=${CLIENT_ID}" --fields id --format csv --noquotes 2>/dev/null \
    | sed '/^[[:space:]]*$/d' | head -1
}

# Devuelve el array interno de redirectUris tal cual (`"a", "b"`), vacio si no
# hay ninguno. `--fields redirectUris --format json` responde
#   [ { "redirectUris" : [ "a", "b" ] } ]
# — el array que interesa es el INTERNO; quitar los corchetes de fuera (error
# clasico aqui) deja un churro que al escribirlo borra todos los redirects.
read_redirect_uris() {
  kget "clients/$1" --fields redirectUris --format json 2>/dev/null \
    | tr -d '\n' \
    | sed -n 's/.*"redirectUris"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' \
    | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//'
}

write_redirect_uris() {
  "${KCADM}" update "clients/$1" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s "redirectUris=$2" >/dev/null 2>&1 \
    || fail "failed to write redirectUris on ${CLIENT_ID}"
}

ensure_redirect_uri() {
  uuid="$1"
  current="$(read_redirect_uris "${uuid}")"
  if printf '%s' "${current}" | grep -qF "${REDIRECT_URI}"; then
    printf 'redirect_uri %s ya declarado\n' "${REDIRECT_URI}"
    return 0
  fi
  if [ "${MODE}" = "audit" ]; then
    fail "audit: redirect_uri ${REDIRECT_URI} is missing on ${CLIENT_ID}"
  fi
  [ -n "${current}" ] || fail "client ${CLIENT_ID} reported no redirectUris at all — refusing to overwrite"
  if printf '%s' "${current}" | grep -q '\*'; then
    printf 'AVISO: %s usa comodines; comprobar que cubren ya el callback nuevo\n' "${CLIENT_ID}"
  fi
  if printf '%s' "${current}" | grep -q ']'; then
    fail "could not parse redirectUris cleanly — refusing to write"
  fi
  merged="[${current},\"${REDIRECT_URI}\"]"
  printf 'anadiendo %s sobre %s\n' "${REDIRECT_URI}" "${current}"
  write_redirect_uris "${uuid}" "${merged}"

  # Guard: el merge tiene que conservar TODO lo que habia mas el nuestro. Si
  # falta cualquiera de los originales, se restaura el array previo y se aborta:
  # sin el callback de auth-next se caen el login de las ~33 rutas compartidas.
  after="$(read_redirect_uris "${uuid}")"
  before_count="$(printf '%s' "${current}" | tr ',' '\n' | grep -c . || true)"
  after_count="$(printf '%s' "${after}" | tr ',' '\n' | grep -c . || true)"
  ok=1
  printf '%s' "${current}" | tr ',' '\n' | sed -e 's/^"//' -e 's/"$//' -e 's/^[[:space:]]*//' | while read -r uri; do
    [ -n "${uri}" ] || continue
    printf '%s' "${after}" | grep -qF "${uri}" || { echo "PERDIDO: ${uri}"; exit 3; }
  done || ok=0
  printf '%s' "${after}" | grep -qF "${REDIRECT_URI}" || ok=0
  if [ "${ok}" -ne 1 ] || [ "${after_count}" -ne "$((before_count + 1))" ]; then
    printf 'RESTAURANDO redirectUris previos (quedaban %s, ahora %s)\n' "${before_count}" "${after_count}" >&2
    write_redirect_uris "${uuid}" "[${current}]"
    fail "redirect_uri merge lost entries — reverted, ${CLIENT_ID} left as it was"
  fi
  printf 'redirect_uri %s anadido a %s (%s -> %s, canario OK)\n' "${REDIRECT_URI}" "${CLIENT_ID}" "${before_count}" "${after_count}"
}

ensure_group_mapper() {
  uuid="$1"
  existing="$(kget "clients/${uuid}/protocol-mappers/models" --fields name --format csv --noquotes 2>/dev/null | sed '/^[[:space:]]*$/d' || true)"
  if printf '%s\n' "${existing}" | grep -qx "groups"; then
    printf 'mapper groups ya presente en %s\n' "${CLIENT_ID}"
    return 0
  fi
  if [ "${MODE}" = "audit" ]; then
    fail "audit: group mapper missing on ${CLIENT_ID}"
  fi
  "${KCADM}" create "clients/${uuid}/protocol-mappers/models" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    -s name=groups \
    -s protocol=openid-connect \
    -s protocolMapper=oidc-group-membership-mapper \
    -s consentRequired=false \
    -s 'config={"full.path":"true","id.token.claim":"true","access.token.claim":"true","claim.name":"groups","userinfo.token.claim":"true"}' \
    >/dev/null 2>&1 || fail "failed to add group mapper to ${CLIENT_ID}"
  printf 'mapper groups anadido a %s\n' "${CLIENT_ID}"
}

# --- membresias ------------------------------------------------------------
user_id_for() {
  kget users -q "email=$1" --fields id --format csv --noquotes 2>/dev/null \
    | sed '/^[[:space:]]*$/d' | head -1
}

grant_membership() {
  email="$1"
  gid="$2"
  gpath="$3"
  uid="$(user_id_for "${email}")"
  if [ -z "${uid}" ]; then
    printf 'AVISO: %s no existe en el realm %s; se omite su membresia en %s\n' "${email}" "${REALM}" "${gpath}"
    return 0
  fi
  if kget "users/${uid}/groups" --fields path --format csv --noquotes 2>/dev/null | grep -qxF "${gpath}"; then
    printf '%s ya esta en %s\n' "${email}" "${gpath}"
    return 0
  fi
  if [ "${MODE}" = "audit" ]; then
    fail "audit: ${email} is not in ${gpath}"
  fi
  # PUT, no POST: la REST de Keycloak asocia grupos con
  # PUT /users/{uid}/groups/{gid}. `kcadm create` mandaria POST y daria 405;
  # `update` sobre esa ruta manda el PUT con cuerpo vacio, que es lo que vale.
  "${KCADM}" update "users/${uid}/groups/${gid}" --config "${ADMIN_CONFIG}" -r "${REALM}" \
    >/dev/null 2>&1 || fail "failed to put ${email} into ${gpath}"
  printf '%s anadido a %s\n' "${email}" "${gpath}"
}

login_admin

uuid="$(client_uuid)"
[ -n "${uuid}" ] || fail "client ${CLIENT_ID} not found in realm ${REALM}"
printf 'client %s = %s\n' "${CLIENT_ID}" "${uuid}"

ugid="$(ensure_group "${USER_GROUP}")"
agid="$(ensure_group "${ADMIN_GROUP}")"
ensure_redirect_uri "${uuid}"
ensure_group_mapper "${uuid}"

for email in ${ADMIN_EMAILS}; do
  grant_membership "${email}" "${agid}" "${ADMIN_GROUP}"
done
for email in ${USER_EMAILS}; do
  grant_membership "${email}" "${ugid}" "${USER_GROUP}"
done

printf 'OK: SSO de skirmbooks reconciliado (%s, %s)\n' "${USER_GROUP}" "${ADMIN_GROUP}"
