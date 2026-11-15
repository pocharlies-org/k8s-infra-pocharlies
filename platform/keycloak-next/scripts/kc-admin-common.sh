#!/bin/sh
# Shared bootstrap of the keycloak-next PostSync reconcilers: the cleanup
# trap, fail(), nonempty_lines(), line_count(), login_admin() and kget().
# Sourced, never executed. (Extracted from the 16 hook scripts by OWU-28-g;
# the copies were byte-identical — keep it that way: change it here only.)
# keycloak-reconcile-lib.sh (INFRA-477) builds on these helpers: source this
# file first, the library after it, and never copy these functions into either.
#
# The sourcing script must define BEFORE sourcing:
#   KCADM, KEYCLOAK_URL, REALM, ADMIN_CONFIG
# and may define KCADM_TMP_FILES (space-separated) with the other temporary
# files the EXIT trap must remove (captured kcadm replies, client configs,
# request bodies).
#
# login_admin passes the admin password as a kcadm option (the form these
# hooks have always used). A hook that must keep it out of argv (SC-1215
# lineage) may redefine login_admin AFTER sourcing with the
# KC_CLI_PASSWORD= environment form.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk/jq/python
# (SC-1215): only sed/wc/tr/rm/sleep are used here.

cleanup() {
  rm -f "${ADMIN_CONFIG}" ${KCADM_TMP_FILES:-}
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

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

# Variant for hooks that must keep the admin password out of argv (SC-1215):
# same retry loop, password delivered as the KC_CLI_PASSWORD environment
# (kcadm 26's default for --password). Such a hook defines, after sourcing:
#   login_admin() { login_admin_env; }
login_admin_env() {
  attempt=1
  while [ "${attempt}" -le 30 ]; do
    if KC_CLI_PASSWORD="${KC_BOOTSTRAP_ADMIN_PASSWORD}" "${KCADM}" config credentials \
      --config "${ADMIN_CONFIG}" \
      --server "${KEYCLOAK_URL}" \
      --realm master \
      --user "${KC_BOOTSTRAP_ADMIN_USERNAME}" >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 5
  done
  fail "Keycloak admin login did not become ready"
}
