#!/usr/bin/env python3
"""Static safety contract for the production OpenClaw failover helper."""

from pathlib import Path
import subprocess


SCRIPT = Path(__file__).with_name("openclaw_maintenance_failover.sh")
SOURCE = SCRIPT.read_text()
GATE_SOURCE = Path(__file__).with_name("openclaw_failover_gate.sh").read_text()


def require(fragment: str) -> int:
    if fragment not in SOURCE:
        raise SystemExit(f"missing failover contract: {fragment}")
    return SOURCE.index(fragment)


for component in ("openclaw", "readonly", "social", "telegram-router"):
    require(f"{component}:deployment)")
    require(f"{component}:pdb)")
    require(f"{component}:pvc)")

require('kind:"Eviction"')
require('apiVersion:"policy/v1"')
require('kctl create --raw')
require('deleteOptions:{preconditions:{uid:$uid}}')
require('OPENCLAW_PRESTOP_FAIL_ON_TIMEOUT=true')
require('volumeattachments.storage.k8s.io')
require('volumes.longhorn.io')
require('.status.robustness == "healthy"')
require('CONFIRM_OPENCLAW_MAINTENANCE_FAILOVER')
require('CONFIRM_OPENCLAW_MAINTENANCE_ABORT')
require('openclaw-qwen36-maintenance-lock')
require('argocd.argoproj.io/skip-reconcile=true')
require('.spec.syncPolicy.automated.selfHeal == false')
require('.status.observedGeneration == .metadata.generation')
require('run_paused_social_smoke')
require('restore_argo_best_effort')
require('assert_argo_restored')

for forbidden in (
    "kubectl delete pod",
    "kctl delete pod",
    "--force --grace-period=0",
    "--disable-eviction",
):
    if forbidden in SOURCE:
        raise SystemExit(f"forbidden failover operation present: {forbidden}")

prepare = SOURCE[SOURCE.index("prepare_failover() {") : SOURCE.index("verify_failover() {")]
ordered = (
    "router_admin /admin/pause",
    'kctl cordon "$TARGET_NODE"',
    "move_component_if_needed openclaw",
    "move_component_if_needed readonly",
    "move_component_if_needed social",
    "move_component_if_needed telegram-router",
    "run_paused_social_smoke",
    "run_smoke smoke-workboard.sh",
    "run_smoke smoke-codex-k8s.sh",
    "router_admin /admin/resume",
    "run_smoke smoke-social-gateway.sh",
)
positions = [prepare.index(fragment) for fragment in ordered]
if positions != sorted(positions):
    raise SystemExit("prepare choreography is not pause -> cordon -> evict -> smoke -> resume")

for fragment in (
    "router_gateway=",
    "protected_singletons=",
    "protectedSingletons:$protectedSingletons",
    "source_router_node=",
):
    if fragment not in GATE_SOURCE:
        raise SystemExit(f"K3s failover gate does not protect the router: {fragment}")

usage = subprocess.run([str(SCRIPT)], text=True, capture_output=True, check=False)
if usage.returncode != 2 or "Usage:" not in usage.stderr:
    raise SystemExit("helper usage path or EXIT trap return code is broken")

print("OpenClaw maintenance failover static contract: PASS")
