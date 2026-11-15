#!/bin/sh
set -eu

umask 077

# OWU-80 (OWU-28 P6; security ruling of 2026-09-25, nota-security-owu28.md
# sections (b) and «Observación de disponibilidad»): owns EXACTLY ONE IdP
# fact — the direct realm-role mapping of "agentgateway-write" (realm "edani")
# onto the human user of Daniel, identified by his immutable Keycloak
# subject/id "e51253a7-c137-4c6c-9fb9-af9cecd3b147" (username
# "me@e-dani.com", resolved read-only against the live realm 2026-09-25). It
# grants that one role to that one user and NOTHING else.
#
# Why the subject is the primary pin and not the username: the internal user
# id IS the `sub` claim every consumer binds on (identity-bindings.yaml
# `default: dani`; dgx-messages-client.sh already pins the same CHECK_USER_ID),
# while the username is a mutable email attribute. The hook resolves the user
# BY ID and then cross-checks the username, enabled flag and human-ness; any
# mismatch fails closed. It never creates, edits or enables users (OWU-80
# limit: if the subject is absent from the realm the job fails loud).
#
# Division of ownership with agentgateway-write-role.sh (SC-44):
#   * The role itself, its service-account grant and its client scope stay
#     owned there (PostSync wave 20). This hook REQUIRES the role to already
#     exist and fails loud otherwise — it never creates, edits or deletes it.
#   * That hook's exclusivity audit was extended in the same PR to tolerate
#     exactly this pinned human holder (HUMAN_GRANTEE_ID/USERNAME there). Any
#     other user, group or service account still fails both hooks.
#   * Merge gate (binding security condition): this grant must not reach prod
#     before the ProForma guard extension of OWU-77 is merged in
#     k8s-agentgateway-pocharlies and deployed (ArgoCD agentgateway-mcp
#     Synced). The CTO governs the merge order; see the PR body and the
#     README grants section.
#
# MODE rollback removes ONLY this user's mapping of the role; the role, the
# service-account grant and every other holder are untouched. A git revert of
# this file restores the grant on the next PostSync; the manual rollback Job
# (manual/agentgateway-write-grant-daniel-rollback-job.yaml, RUNBOOK section
# 16) is applied by hand.
#
# The reconciler skeleton (identity guard, user resolution, post-ensure
# assertion, audit and rollback flow) is shared with
# photos-confirm-delete-grant-daniel.sh via human-role-grant-daniel-lib.sh
# (INFRA-402 duplicates check; behavior unchanged — the OWU-80 contract tests
# drive this script end-to-end). This file keeps only its identity pins and
# its role-existence policy.
#
# Runs INSIDE the pinned Keycloak image, which ships no awk (SC-1215). Only
# kcadm plus sed/grep/tr/wc/rm/sleep are invoked; the contract test audits
# this. Neither the admin password nor any token is ever printed: the output
# is a sanitized JSON verdict.

MODE="${MODE:-ensure}"
KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak.keycloak.svc.cluster.local}"
REALM="${REALM:-edani}"
ROLE_NAME="${ROLE_NAME:-agentgateway-write}"
USER_ID="${USER_ID:-e51253a7-c137-4c6c-9fb9-af9cecd3b147}"
USER_NAME="${USER_NAME:-me@e-dani.com}"
KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"
ADMIN_CONFIG=/tmp/kcadm-write-grant-daniel-admin.config
KCADM_OUT=/tmp/kcadm-write-grant-daniel-reply.txt

KCADM_TMP_FILES="${KCADM_OUT}"
. "${0%/*}/kc-admin-common.sh"
. "${0%/*}/human-role-grant-daniel-lib.sh"

# The identity of this reconciler is fixed; it cannot be pointed at another
# realm, role or user through the environment (guard_human_grant_identity
# compares against these literals).
REALM_PIN=edani
ROLE_PIN=agentgateway-write
USER_ID_PIN=e51253a7-c137-4c6c-9fb9-af9cecd3b147
USER_NAME_PIN=me@e-dani.com

assert_role_present() {
  # The role is owned by agentgateway-write-role.sh (PostSync wave 20, which
  # runs before this hook's wave 25). Missing here means the trunk moved out
  # from under the grant: fail loud, never create the role from this hook.
  kget "roles/${ROLE_NAME}" --fields id >/dev/null 2>&1 || \
    fail "${ROLE_NAME} is missing from realm ${REALM}: owned by agentgateway-write-role.sh, refusing to create it here"
}

reconcile_human_grant
