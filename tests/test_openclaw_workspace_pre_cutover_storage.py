from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "storage/longhorn/openclaw-workspace-precutover-recurring-job.yaml"


def test_pre_cutover_group_is_snapshot_only_and_rendered_by_gitops():
    job = yaml.safe_load(MANIFEST.read_text())
    assert job["kind"] == "RecurringJob"
    assert job["metadata"]["namespace"] == "longhorn-system"
    assert job["spec"]["task"] == "snapshot"
    assert job["spec"]["groups"] == ["openclaw-workspace-precutover"]
    assert job["spec"]["retain"] == 2
    assert "backup" not in job["metadata"]["name"]
    kustomization = yaml.safe_load((ROOT / "kustomization.yaml").read_text())
    assert "storage/longhorn/openclaw-workspace-precutover-recurring-job.yaml" in kustomization["resources"]
