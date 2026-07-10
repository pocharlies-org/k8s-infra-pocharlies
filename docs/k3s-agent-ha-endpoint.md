# K3s agent HA endpoint migration

## Scope and invariant

The four K3s agents (`ubuntu`, `sauvage`, `nvidia-dgx`, and `gx10-ec3d`) must
join through `https://k8s.lan.e-dani.com:6443`, which resolves only to the
TailVIP `100.105.20.73`. Direct control-plane IPs and the retired
`x86.taile0ad27.ts.net` endpoint are not valid persisted agent dependencies.

The playbook is audit-only by default. An apply or rollback is serial (`1`),
fails the entire wave on the first error, never changes the K3s binary, and
keeps a root-only exact configuration archive on each node. It updates every
loaded environment source that already defines `K3S_URL` and any existing YAML
`server:` key. It refuses unknown supervisor layouts and explicit `--server`
flags instead of guessing precedence.

## Preconditions

1. `k8s.lan.e-dani.com` resolves only to `100.105.20.73` from the controller
   and all four agents.
2. The current kubeconfig context is `x86-k3s` and authenticated `/readyz`
   succeeds with `--server=https://k8s.lan.e-dani.com:6443`.
3. The API certificate verifies for `k8s.lan.e-dani.com` against each agent's
   existing K3s server CA.
4. No protected OpenClaw singleton is running on an agent being restarted.
5. Use a unique migration identifier. Never delete or overwrite the evidence
   under `/var/lib/k3s-agent-endpoint-migrations/`.

## Audit without restart

```bash
export KUBECTL_BIN=kubectl
export EXPECTED_KUBE_CONTEXT=x86-k3s
uvx --from ansible-core ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-agent-endpoint.yml \
  -e endpoint_operation=audit
```

The report prints only the effective URL and source file paths. It never prints
the K3s token or the full service environment.

## Apply serially

Choose one shared identifier, for example `20260710-tailvip-ha`. If all nodes
have non-interactive sudo, one invocation processes them in inventory order:

```bash
export K3S_ENDPOINT_MIGRATION_ID=20260710-tailvip-ha
export CONFIRM_K3S_AGENT_ENDPOINT_MIGRATION="migrate-k3s-agents-${K3S_ENDPOINT_MIGRATION_ID}-to-k8s.lan.e-dani.com"
uvx --from ansible-core ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-agent-endpoint.yml \
  -e endpoint_operation=apply \
  -e "migration_id=${K3S_ENDPOINT_MIGRATION_ID}"
```

`sauvage` currently has an interactive sudo boundary. If that remains true,
run the three non-interactive agents first, then run the exact same migration
ID against `sauvage` with `--ask-become-pass`:

```bash
uvx --from ansible-core ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-agent-endpoint.yml \
  --limit 'ubuntu,nvidia-dgx,gx10-ec3d' \
  -e endpoint_operation=apply \
  -e "migration_id=${K3S_ENDPOINT_MIGRATION_ID}"

uvx --from ansible-core ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-agent-endpoint.yml \
  --limit sauvage --ask-become-pass \
  -e endpoint_operation=apply \
  -e "migration_id=${K3S_ENDPOINT_MIGRATION_ID}"
```

For each restart, acceptance requires a new systemd PID, the exact HA URL in
the running process, `systemctl is-active`, the same Kubernetes Node UID and
K3s version, a fresh node Lease, `Ready=True`, and no TLS/auth errors in the
new journal window. A failure restores the archive, restarts the previous
configuration, waits for Ready, and aborts the serial wave.

## Explicit rollback

Rollback uses the exact archive for the selected migration ID and preserves it
after restoration:

```bash
export CONFIRM_K3S_AGENT_ENDPOINT_ROLLBACK="rollback-k3s-agent-endpoint-${K3S_ENDPOINT_MIGRATION_ID}"
uvx --from ansible-core ansible-playbook \
  -i ansible/inventory/generated/k3s-production.ini \
  ansible/playbooks/k3s-agent-endpoint.yml \
  -e endpoint_operation=rollback \
  -e "migration_id=${K3S_ENDPOINT_MIGRATION_ID}"
```

Do not run a K3s version upgrade until the post-apply audit shows all four
agents using the HA URL.
