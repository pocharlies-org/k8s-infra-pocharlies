# Runtime credential rotation

This runbook rotates the two credentials exposed during the July 2026
OpenClaw audit without printing either value and without interrupting running
pods. Run it from a trusted shell with history disabled and `set +x`.

## Safety invariants

- Never paste a robot secret or catalog token into Git, a terminal transcript,
  a ticket, a PR, or a Kubernetes manifest.
- Do not revoke the old credential until every target Secret has reconciled and
  an actual fresh image pull or catalog request succeeds with the new one.
- Keep the Harbor CI push credential (`buildkit/harbor-push`) separate. This
  rotation is for runtime pull only.
- The catalog API must run the dual-token build before changing the active
  client credential. A missing primary token must continue to return HTTP 401.

## Harbor runtime pull credential

1. Use Harbor API v2 to create a finite-lived system robot named
   `k8s-runtime-pull-YYYYMM` with exactly one permission:

   ```json
   {
     "name": "k8s-runtime-pull-YYYYMM",
     "description": "Kubernetes runtime pull only; rotate before expiry",
     "level": "system",
     "duration": 90,
     "disable": false,
     "permissions": [
       {
         "kind": "project",
         "namespace": "homelab",
         "access": [{"resource": "repository", "action": "pull"}]
       }
     ]
   }
   ```

   Capture the create response in memory. Do not print it. Build a Docker config
   JSON in memory and write it as property `dockerconfigjson` at Vault path
   `secret/infra/harbor/k8s-runtime-pull`.

2. Before GitOps reconciliation, ask Harbor's token endpoint for scope
   `repository:homelab/offers-mcp:pull,push`. Decode only the JWT claims and
   assert that the granted action set is exactly `["pull"]`. A push action is a
   hard stop.

3. Merge the ClusterExternalSecret change. Wait for
   `clusterexternalsecret/harbor-runtime-pull` to report Ready and for every
   generated ExternalSecret to report `SecretSynced=True`.

4. Verify the target Secret type remains
   `kubernetes.io/dockerconfigjson`, then perform an `imagePullPolicy: Always`
   canary pull in every listed namespace. Delete the canary pods after success.

5. Confirm no target Secret still contains the old robot username. Disable
   Harbor robot id `154` using `PUT /api/v2.0/robots/154` with the current robot
   object and `disable: true`. Re-run pull canaries. Delete robot id `154` only
   after a 24-hour clean observation window.

6. Separately replace the remaining runtime copies of Harbor `admin` and the
   CI push robot with this pull-only secret. `buildkit/harbor-push` remains the
   only Kubernetes Secret permitted to carry push scope.

After adoption, change the ClusterExternalSecret target from `Merge` to `Owner`
in a controlled follow-up so new namespaces fail closed instead of depending on
an out-of-band pre-existing Secret.

## Catalog API token

1. Seed Vault `secret/skirmshop/catalog-api` with properties `active` and
   `previous`, both initially holding the current credential. Do not change the
   credential yet.

2. Reconcile `catalog-api-client` and `catalog-api-server`, then deploy rag-app
   with explicit Secret refs for `CATALOG_SYNC_TOKEN` and
   `CATALOG_SYNC_TOKEN_PREVIOUS`. Verify the current token still succeeds and a
   random token returns HTTP 401.

3. Move all clients to `catalog-api-client/CATALOG_SYNC_TOKEN`. The inventory is:
   offers-mcp, skirmshop-plugins-mcp, picker-purchase-signals, and the disabled
   Synapse product-creator adapters. Do not scale the Synapse adapters up while
   they still reference the missing `synapse-secrets/catalog_sync.token` key.

4. Generate a new random token in memory. Write Vault atomically with
   `active=<new>` and `previous=<old>`, then force ESO refresh. **Roll rag-app
   first** so it loads and accepts both values; prove both work before touching
   a client. Only then restart client controllers whose environment value is
   captured at process start. Reversing this order creates an authentication
   outage because the old server process has not loaded the new value yet.

5. Validate every client with a read-only catalog endpoint, then validate one
   idempotent write path. Confirm the old value is no longer mounted in any
   client pod.

6. End the overlap by replacing `previous` with `active`, force-refresh the
   server Secret, and roll rag-app. Prove the old token returns HTTP 401.

7. After the new deployments are healthy, remove the legacy
   `CATALOG_SYNC_TOKEN` key from the manually managed `skirmshop/rag-secrets`
   Secret and delete `offers-mcp/offers-mcp-secrets`. First prove no live
   controller still references either source. Restart long-running clients so
   the revoked value is no longer present in process environments. Remove
   `CATALOG_SYNC_TOKEN_PREVIOUS` in a follow-up release after the observation
   window.

## Fail-closed checks

- Any ExternalSecret not Ready: stop; do not restart consumers.
- Harbor token grants push: delete the new robot and start again with pull only.
- rag-app primary token missing: expect HTTP 401 even if the previous value is
  present.
- Any client still using `rag-secrets`, `offers-mcp-secrets`, or
  `synapse-secrets/catalog_sync.token`: do not retire the old token.
- Any failed fresh image pull after disabling robot id 154: re-enable it,
  restore service, and fix the namespace before retrying.
