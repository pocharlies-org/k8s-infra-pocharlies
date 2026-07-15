# LiteLLM shared Valkey HA prerequisite

This change hardens the existing `databases/shared-valkey` placement and opens
its data plane to pods with `app=litellm` in namespace `litellm`. It does not
switch LiteLLM to Valkey, scale LiteLLM, create an ACL principal, or change the
out-of-Git `shared-valkey-acl` Secret.

## Contract delivered here

- Exactly three `shared-valkey` pods remain scheduled on nodes labelled
  `workload=core`.
- Required hostname anti-affinity and a fail-closed topology spread constraint
  keep the three pods on three distinct eligible nodes.
- `PodDisruptionBudget/shared-valkey` requires two pods to remain available for
  voluntary disruptions.
- The existing Sentinel services, quorum, master-labeler, AOF settings,
  `ReadWriteOnce` Longhorn claims, and Service ports are unchanged.
- NetworkPolicy admits `litellm/app=litellm` only on TCP `6379`. TCP `26379`
  remains closed because the current LiteLLM manifest does not configure a
  Sentinel-aware client.

## Make-before-break blocker for LiteLLM

Do not scale LiteLLM above one replica and do not remove its node-local tracking
state merely because this infrastructure change has landed. The consumer-side
cutover remains blocked until all of the following are implemented and proven:

1. Create a dedicated least-privilege LiteLLM ACL user through the existing
   authoritative secret-management process. Do not edit `shared-valkey-acl`
   manually, commit credentials, or reuse the replication/Sentinel users.
2. Project that credential into the LiteLLM namespace through its GitOps-owned
   secret path before changing any LiteLLM Redis settings.
3. Configure and test the LiteLLM shared cooldown/cache state and replace the
   node-local active-request tracker with a multi-replica-safe shared design.
   Keep `replicas: 1` and the existing tracking path as the rollback floor until
   both stores are verified.
4. From a pod matching `namespace=litellm, app=litellm`, verify authenticated
   `SET`/`GET`/`DEL` of a uniquely prefixed disposable key through
   `shared-valkey-master.databases.svc.cluster.local:6379`.
5. Run a controlled Valkey failover and prove that LiteLLM reconnects, shared
   cooldown state survives, active-request accounting converges, and no request
   is duplicated or lost. Also verify one master, two replicas, healthy AOF,
   and all three exporter targets after recovery.
6. Only after that evidence is green may a separate LiteLLM change remove its
   HA blockers and increase replicas. Roll back the LiteLLM client configuration
   first if any gate fails; this infrastructure prerequisite can remain in place.

If LiteLLM later uses Sentinel discovery directly, add TCP `26379` in a separate
reviewed change only after the exact client configuration, authentication path,
DNS behavior, and failover test are present. Opening the Sentinel control plane
preemptively is not part of this change.

## Scheduling and rollout gate

The hard placement contract intentionally leaves a pod Pending if fewer than
three schedulable `workload=core` hostnames exist. Before syncing, verify three
Ready eligible nodes, healthy Longhorn volumes/backups, one Valkey master and two
replicas, and zero active maintenance. Roll one ordinal at a time and stop if
any pod, PVC attachment, Sentinel quorum, replication, or AOF check is unhealthy.
