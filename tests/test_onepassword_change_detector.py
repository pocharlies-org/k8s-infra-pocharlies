"""DGX-506: contract of platform/external-secrets/change-detector/detect.py.

The detector must force-sync exactly the ExternalSecrets (and the
ClusterExternalSecret templates) that reference an item whose version changed,
never a CES child (ESO drops a force-sync set on a child), never another
store's ExternalSecret, and must do nothing on the first run but record the
baseline. Stdlib only: the Kubernetes API is replaced by an in-memory fake.
"""
import importlib.util
import json
import pathlib
import re
import runpy
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = ROOT / "platform" / "external-secrets" / "change-detector"
SCRIPT = BASE / "detect.py"
ESO = "/apis/external-secrets.io/v1"
STATE = "/api/v1/namespaces/external-secrets-operator/configmaps/onepassword-change-detector-state"


def load_detector():
    spec = importlib.util.spec_from_file_location("detect", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def es(ns, name, store="onepassword", keys=(), extract=(), owner=None):
    meta = {"namespace": ns, "name": name}
    if owner:
        meta["ownerReferences"] = [{"kind": "ClusterExternalSecret", "name": owner}]
    return {
        "metadata": meta,
        "spec": {
            "secretStoreRef": {"name": store, "kind": "ClusterSecretStore"},
            "data": [{"secretKey": "k", "remoteRef": {"key": k}} for k in keys],
            "dataFrom": [{"extract": {"key": k}} for k in extract],
        },
    }


def ces(name, keys=(), store="onepassword"):
    return {
        "metadata": {"name": name},
        "spec": {"externalSecretSpec": {
            "secretStoreRef": {"name": store},
            "data": [{"secretKey": "k", "remoteRef": {"key": k}} for k in keys],
        }},
    }


class FakeAPI:
    def __init__(self, externalsecrets, clusterexternalsecrets, state=None):
        self.objects = {
            f"{ESO}/externalsecrets": {"items": externalsecrets},
            f"{ESO}/clusterexternalsecrets": {"items": clusterexternalsecrets},
        }
        self.state = state
        self.writes = []

    def __call__(self, method, path, body=None, ctype="application/json"):
        if method == "GET":
            if path == STATE:
                if self.state is None:
                    return None
                return {"data": {"items.json": json.dumps(self.state)}}
            return self.objects[path]
        self.writes.append((method, path, body))
        return {}

    def forced(self):
        return sorted(p for m, p, b in self.writes
                      if m == "PATCH" and "force-sync" in json.dumps(b))


ITEMS_V1 = [
    {"id": "aaa", "title": "harbor-pull", "version": 1},
    {"id": "bbb", "title": "gsc-mcp", "version": 3},
    {"id": "ccc", "title": "minio-backup-user", "version": 2},
]


def state_of(items):
    return {i["id"]: {"title": i["title"], "version": i["version"]} for i in items}


CLUSTER_ES = [
    es("gsc-mcp", "gsc-mcp-secrets", keys=["gsc-mcp/sa_json"]),
    es("merchant", "merchant-secrets", extract=["gsc-mcp"]),
    es("chat", "harbor-pull", keys=["harbor-pull/dockerconfigjson"]),
    es("web", "harbor-runtime-pull", keys=["harbor-pull/dockerconfigjson"], owner="harbor-runtime-pull"),
    es("skirmshop", "pg", store="kubernetes-cnpg", keys=["gsc-mcp/x"]),
    es("minio", "backup", keys=["minio-backup-user/ACCESS_KEY_ID"]),
]
CLUSTER_CES = [ces("harbor-runtime-pull", keys=["harbor-pull/dockerconfigjson"]),
               ces("other-store", keys=["gsc-mcp/x"], store="vault")]


class ChangeDetectorTest(unittest.TestCase):
    def run_detector(self, items, api, dry_run=False):
        detector = load_detector()
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(items, f)
        detector.ITEMS_FILE = f.name
        detector.DRY_RUN = dry_run
        detector.call = api
        detector.main()
        return api

    def test_first_run_records_baseline_and_forces_nothing(self):
        api = self.run_detector(ITEMS_V1, FakeAPI(CLUSTER_ES, CLUSTER_CES, state=None))
        self.assertEqual(api.forced(), [])
        posts = [w for w in api.writes if w[0] == "POST"]
        self.assertEqual(len(posts), 1)
        self.assertEqual(json.loads(posts[0][2]["data"]["items.json"]), state_of(ITEMS_V1))

    def test_no_change_forces_nothing_and_keeps_state(self):
        api = self.run_detector(ITEMS_V1, FakeAPI(CLUSTER_ES, CLUSTER_CES, state=state_of(ITEMS_V1)))
        self.assertEqual(api.forced(), [])
        self.assertEqual([w[1] for w in api.writes], [STATE])

    def test_changed_item_forces_only_its_consumers(self):
        items = [dict(i, version=i["version"] + (1 if i["id"] == "bbb" else 0)) for i in ITEMS_V1]
        api = self.run_detector(items, FakeAPI(CLUSTER_ES, CLUSTER_CES, state=state_of(ITEMS_V1)))
        # data[] key and dataFrom.extract both match; the cnpg-store ES and the
        # CES on another store are left alone.
        self.assertEqual(api.forced(), [
            f"{ESO}/namespaces/gsc-mcp/externalsecrets/gsc-mcp-secrets",
            f"{ESO}/namespaces/merchant/externalsecrets/merchant-secrets",
        ])

    def test_connect_store_consumers_are_forced_too(self):
        # INFRA-511: Kyverno moves ExternalSecrets to onepassword-connect, where
        # the reference is `key: <item>` + property; they keep OnChange and
        # still need the force-sync when their item changes.
        connect = es("hermes", "hermes-connect", store="onepassword-connect", keys=["gsc-mcp"])
        items = [dict(i, version=i["version"] + (1 if i["id"] == "bbb" else 0)) for i in ITEMS_V1]
        api = self.run_detector(items, FakeAPI(CLUSTER_ES + [connect], CLUSTER_CES, state=state_of(ITEMS_V1)))
        self.assertIn(f"{ESO}/namespaces/hermes/externalsecrets/hermes-connect", api.forced())
        self.assertNotIn(f"{ESO}/namespaces/skirmshop/externalsecrets/pg", api.forced())

    def test_ces_template_is_forced_not_its_children(self):
        items = [dict(i, version=i["version"] + (1 if i["id"] == "aaa" else 0)) for i in ITEMS_V1]
        api = self.run_detector(items, FakeAPI(CLUSTER_ES, CLUSTER_CES, state=state_of(ITEMS_V1)))
        self.assertEqual(api.forced(), [
            f"{ESO}/clusterexternalsecrets/harbor-runtime-pull",
            f"{ESO}/namespaces/chat/externalsecrets/harbor-pull",
        ])

    def test_new_item_and_renamed_item_force_their_consumers(self):
        prev = state_of(ITEMS_V1)
        del prev["bbb"]  # gsc-mcp is new since the last run
        items = [dict(i) for i in ITEMS_V1]
        items[2] = {"id": "ccc", "title": "minio-backup-user-v2", "version": 3}  # renamed
        api = self.run_detector(items, FakeAPI(CLUSTER_ES, CLUSTER_CES, state=prev))
        self.assertEqual(api.forced(), [
            f"{ESO}/namespaces/gsc-mcp/externalsecrets/gsc-mcp-secrets",
            f"{ESO}/namespaces/merchant/externalsecrets/merchant-secrets",
            f"{ESO}/namespaces/minio/externalsecrets/backup",
        ])

    def test_reference_by_item_id_matches(self):
        cluster = [es("x", "by-id", keys=["bbb/sa_json"])]
        items = [dict(i, version=i["version"] + (1 if i["id"] == "bbb" else 0)) for i in ITEMS_V1]
        api = self.run_detector(items, FakeAPI(cluster, [], state=state_of(ITEMS_V1)))
        self.assertEqual(api.forced(), [f"{ESO}/namespaces/x/externalsecrets/by-id"])

    def test_force_sync_value_is_a_timestamp_annotation(self):
        items = [dict(i, version=i["version"] + (1 if i["id"] == "bbb" else 0)) for i in ITEMS_V1]
        api = self.run_detector(items, FakeAPI(CLUSTER_ES, [], state=state_of(ITEMS_V1)))
        patch = next(b for m, p, b in api.writes if p.endswith("/gsc-mcp-secrets"))
        self.assertEqual(list(patch), ["metadata"])
        self.assertRegex(patch["metadata"]["annotations"]["force-sync"], r"^\d{10}$")

    def test_failed_patch_leaves_state_unwritten(self):
        """A force-sync PATCH that fails must not save the new versions: the
        next run sees the same items as changed and forces them again."""
        class FailingPatch(FakeAPI):
            def __call__(self, method, path, body=None, ctype="application/json"):
                if method == "PATCH" and path != STATE:
                    raise OSError("apiserver unavailable")
                return super().__call__(method, path, body, ctype)

        items = [dict(i, version=i["version"] + (1 if i["id"] == "bbb" else 0)) for i in ITEMS_V1]
        api = FailingPatch(CLUSTER_ES, CLUSTER_CES, state=state_of(ITEMS_V1))
        with self.assertRaises(OSError):
            self.run_detector(items, api)
        self.assertEqual([w for w in api.writes if w[1] == STATE], [])

    def test_dry_run_writes_nothing(self):
        items = [dict(i, version=i["version"] + 1) for i in ITEMS_V1]
        api = self.run_detector(items, FakeAPI(CLUSTER_ES, CLUSTER_CES, state=state_of(ITEMS_V1)), dry_run=True)
        self.assertEqual(api.writes, [])

    def test_any_error_exits_1_so_the_cronjob_alert_fires(self):
        with mock.patch.dict("os.environ", {"ITEMS_FILE": "/nonexistent/items.json"}):
            with self.assertRaises(SystemExit) as ctx:
                runpy.run_path(str(SCRIPT), run_name="__main__")
        self.assertEqual(ctx.exception.code, 1)


class CronJobManifestTest(unittest.TestCase):
    """Quota guards on the CronJob: one vault listing per run, no retries."""

    def setUp(self):
        self.manifest = (BASE / "cronjob.yaml").read_text()

    def test_no_retry_and_no_overlap(self):
        self.assertRegex(self.manifest, r"\n\s+backoffLimit: 0\n")
        self.assertRegex(self.manifest, r"\n\s+concurrencyPolicy: Forbid\n")

    def test_op_image_pinned_by_digest(self):
        self.assertRegex(self.manifest, r"image: docker\.io/1password/op:[\d.]+@sha256:[0-9a-f]{64}")

    def test_schedule_is_not_more_often_than_hourly(self):
        schedule = re.search(r'schedule: "([^"]+)"', self.manifest).group(1)
        minute = schedule.split()[0]
        self.assertRegex(minute, r"^\d+$", "a fixed minute: at most one run per hour")


class OpContainerStateDirTest(unittest.TestCase):
    """Live failure: `op` as uid 65532 refused /tmp/.config/op and
    /tmp/com.agilebits.op.SingleUserEnvironment ("not owned by the current
    user"): the dirs came from a root-owned emptyDir. Every container that
    runs `op` must keep HOME, config and TMPDIR under a writable emptyDir
    mount and create those dirs itself, never under the image's /tmp."""

    def setUp(self):
        text = (BASE / "cronjob.yaml").read_text()
        self.volumes = text.split("\n          volumes:\n", 1)[1]
        containers = re.split(r"\n            - name: ", "\n" + text.split("\n          initContainers:\n", 1)[1])[1:]
        self.op = [c for c in containers if re.search(r"\bop item\b", c)]

    def test_there_is_an_op_container(self):
        self.assertTrue(self.op)

    def test_state_env_is_under_a_mounted_emptydir(self):
        for c in self.op:
            mount = re.search(r"\{ name: (\w+), mountPath: (/\w+) \}", c)
            self.assertIsNotNone(mount, "op needs a writable volume mount")
            name, path = mount.groups()
            self.assertRegex(self.volumes, rf"- name: {name}\n\s+emptyDir:")
            self.assertNotIn("readOnly", mount.group(0))
            for var in ("HOME", "XDG_CONFIG_HOME", "OP_CONFIG_DIR", "TMPDIR"):
                value = re.search(rf"name: {var}, value: (\S+) \}}", c)
                self.assertIsNotNone(value, f"{var} must be set")
                self.assertTrue(value.group(1).startswith(path + "/"), f"{var}={value.group(1)} not under {path}")

    def test_op_creates_its_own_dirs_as_the_job_uid(self):
        for c in self.op:
            self.assertRegex(c, r"mkdir -p [^\n]*/home/\.config[^\n]* && op item list")
            self.assertRegex(c, r"readOnlyRootFilesystem: true")

    def test_no_container_writes_the_image_tmp(self):
        self.assertNotRegex((BASE / "cronjob.yaml").read_text(), r"(HOME|TMPDIR|XDG_CONFIG_HOME|OP_CONFIG_DIR), value: /tmp\b")
        self.assertNotRegex(self.volumes + "".join(self.op), r"mountPath: /tmp\b")


if __name__ == "__main__":
    unittest.main()
