# Intermittent P1001/P2024 to postgres-shared after a CNPG switchover

Tracked in INFRA-1004 (27-10-2026). On 27-10 the CNPG primary of `postgres-shared-nvme`
moved from ks5-cp-3 (cordoned) to ks5-cp-2 at 06:59Z. From ~08:30Z to ~10:17Z pods on
`sauvage` intermittently lost TCP to `postgres-shared-rw.databases.svc:5432` (Prisma
P1001/P2024, the translations queue stalled in bursts and resumed on its own).

## What it was not

The ticket suspected stale flannel/conntrack routes left by the switchover. The evidence
ruled that out:

- The endpointSlice and the service selector were correct throughout (`10.42.5.122` =
  pod `-2` on ks5-cp-2); the service path from other nodes was fine.
- flannel writes **PERMANENT** ARP and FDB entries per remote subnet — there is no aging
  entry to go stale (`ip neigh show dev flannel.1` on sauvage, all PERMANENT, correct VTEPs).
- tailscaled on sauvage logged **no** session events (endpoint change, rebind, disconnect)
  for the ks5 peers during the window — the WireGuard session itself was stable.
- conntrack on sauvage was near-empty during the incident (4158/1.5M, no entries to the
  primary).

## What it was

Node-level packet loss on the **sauvage → ks5 (OVH, 141.94.73.0/24)** path, not
postgres-specific:

- The k3s agent on sauvage failed its node-lease PUTs to the apiserver (cp-1) **30 times**
  between 05:00Z and 10:00Z on 27-10 (`journalctl -u k3s-agent | grep "Failed to update lease"`),
  with the peak (12) at 09:00Z — the same window as the P1001s. The same check on x86 over
  the same window: **0** failures. So the apiserver/etcd was fine; the path from sauvage was not.
- `brain→litellm` stayed healthy because litellm runs on `ubuntu` (home), a different path.
- The switchover did not create the loss; it moved the primary from cp-3 (145.239.x) onto
  the flaky path (cp-2, 141.94.73.50), which made an existing path problem visible as P1001.
  The loss resolved on its own by ~10:17Z (OVH-side; nothing was changed on the nodes).

## Triage order when it recurs

The probe CronJob `databases/postgres-rw-connectivity-probe` (one probe per minute from a
pod on sauvage to the rw service) fails → `K8sCronJobFailed` alarm (topic Crons). Then:

1. Confirm the target is right:
   `kubectl get endpointslice -n databases -l kubernetes.io/service-name=postgres-shared-rw -o wide`
   and `kubectl get pods -n databases -o wide` (the primary's node is the destination).
2. Test from the affected node and compare with another node:
   `kubectl exec -n skirmshop deploy/translations-app -- node -e 'new (require("net").Socket)().connect(5432,"postgres-shared-rw.databases.svc").on("connect",()=>{console.log("ok");process.exit(0)}).on("error",e=>{console.log("fail",e.code);process.exit(1)})'`
   If it fails only from one node → node-level path, continue at 3. If it fails everywhere →
   check the CNPG cluster (`kubectl get cluster.postgresql.cnpg.io -n databases`) first.
3. Check whether the node's control-plane path degraded in the same window (the tell from
   INFRA-1004): `ssh <node> 'journalctl -u k3s-agent --since -4h | grep -c "Failed to update lease"'`
   (a healthy node: ~0; sauvage on 27-10: 30).
4. Check the tailnet peer is `direct` and stable: `ssh <node> tailscale status | grep ks5`.
   If it flapped, the loss is in tailscale/underlay; if stable (as on 27-10), the loss is
   in the underlying OVH path — check the OVH status/history for the two hosts and escalate
   if it repeats.
5. Only if 1–4 are clean and the failure is reproducible, consider stale conntrack and
   flush the flows to the primary on the affected node:
   `ssh <node> 'sudo conntrack -D -p tcp --dport 5432'`
   (this was not the cause on 27-10 — do not stop here expecting it to fix a path problem).

## Residual risk

The loss was external (OVH between sauvage and the ks5 trio) and self-resolved; there is no
in-house fix for the path itself. What the house keeps: the per-minute probe (recurrence is
detected in ≤1 min with an alarm instead of by the translations queue), and this triage.
If recurrences become frequent, the candidate mitigations are a second tailnet path for the
ks5 peers (DERP is already a fallback, slow) or moving the probe's node set to catch which
pairs actually degrade.
