#!/bin/sh
# INFRA-250 (INFRA-219 C5): entrypoint of the keycloak-role-drift CronJob.
#
# Runs the two read-only verifiers against the live edani realm with the
# keycloak-rbac-auditor credential (mounted files, see kc_rbac.Client.from_env)
# and folds their exit codes into one:
#
#   0  both printed OK: (verify-role-catalog.py also prints its SKIP: line)
#   1  at least one DRIFT: and no ERROR:
#   2  at least one ERROR:, or a verifier that died without its verdict line
#
# The verifiers own the logic; this file only calls them. A non-zero exit
# fails the Job (backoffLimit 0) and K8sCronJobFailed raises the alert.
set -u

RBAC_DIR="${RBAC_DIR:-/opt/rbac}"
PYTHON="${PYTHON:-python3}"
WORK="${TMPDIR:-/tmp}"
RESULT=0

fold() {
  case "$1" in
    0) ;;
    1) [ "${RESULT}" -eq 2 ] || RESULT=1 ;;
    *) RESULT=2 ;;
  esac
}

run_verifier() {
  name="$1"
  shift
  out="${WORK}/keycloak-role-drift.$$.out"
  "${PYTHON}" "${RBAC_DIR}/${name}" "$@" >"${out}" 2>&1
  code=$?
  cat "${out}"
  # exit 1 is DRIFT only when the verifier said so; an uncaught Python
  # exception also exits 1 and must read as ERROR, not as drift.
  if [ "${code}" -eq 1 ] && ! grep -q '^DRIFT: ' "${out}"; then
    printf 'ERROR: %s terminó con código 1 sin línea DRIFT:\n' "${name}"
    code=2
  fi
  if [ "${code}" -eq 0 ] && ! grep -q '^OK: ' "${out}"; then
    printf 'ERROR: %s terminó con código 0 sin línea OK:\n' "${name}"
    code=2
  fi
  rm -f "${out}"
  fold "${code}"
}

# --skip-client-uuid-check: the auditor has no view-clients, so the catalog's
# client_uuids map is used as is and not re-checked with GET clients (INFRA-253).
run_verifier verify-role-catalog.py --catalog "${RBAC_DIR}/ROLES.yaml" --skip-client-uuid-check
run_verifier verify-principals.py --principals "${RBAC_DIR}/PRINCIPALS.md" --catalog "${RBAC_DIR}/ROLES.yaml"
exit "${RESULT}"
