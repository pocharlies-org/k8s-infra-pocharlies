# Contract tests for the shared-valkey startup scripts (INFRA-859, fix of the
# root cause behind problem INFRA-822: circular replication on master restart
# and Sentinel ghost entries from a myid lost on every restart).
#
# These are behavioural: the scripts from the ConfigMap are executed against
# fake valkey-cli / valkey-server / valkey-sentinel binaries, so the assertions
# prove what the pod does on restart, not just what the text says.
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "databases/postgres-shared/shared-valkey.yaml"

HEADLESS = "shared-valkey-headless.databases.svc.cluster.local"


def config_map() -> dict:
    for doc in yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")):
        if doc and doc.get("kind") == "ConfigMap":
            return doc["data"]
    raise AssertionError("ConfigMap shared-valkey-scripts not found")


def labeler_args() -> str:
    for doc in yaml.safe_load_all(MANIFEST.read_text(encoding="utf-8")):
        if (
            doc
            and doc.get("kind") == "Deployment"
            and doc["metadata"]["name"] == "shared-valkey-master-labeler"
        ):
            return doc["spec"]["template"]["spec"]["containers"][0]["args"][0]
    raise AssertionError("labeler Deployment not found")


class Runner:
    """Runs a ConfigMap script with fake valkey binaries on PATH.

    Scenario env vars consumed by the fakes:
      FAKE_SENTINEL_MASTER  reply to `sentinel get-master-addr-by-name` ("" = unknown)
      FAKE_SENTINEL_AFTER   emit the master only after this many sentinel answers
      FAKE_P0_ROLE          reply to `role` when asked of shared-valkey-0
    Each fake `valkey-server` invocation is appended to <tmp>/servers.log.
    """

    def __init__(self, script: str, scenario: dict):
        self.dir = tempfile.TemporaryDirectory()
        binpath = Path(self.dir.name, "bin")
        binpath.mkdir()
        log = Path(self.dir.name, "servers.log")
        (binpath, log)
        self.log = log
        self.env = {
            "PATH": f"{binpath}{os.pathsep}{os.environ['PATH']}",
            "POD_NAMESPACE": "databases",
            "SENTINEL_PASSWORD": "sp",
            "SENTINEL_VALKEY_PASSWORD": "svp",
            "REPLICATION_PASSWORD": "rp",
            **{k: str(v) for k, v in scenario.items()},
        }
        (binpath / "valkey-cli").write_text(
            "#!/bin/sh\n"
            'args="$*"\n'
            "case \"$args\" in\n"
            "  *get-master-addr-by-name*)\n"
            "    n=$(cat \"$FAKE_COUNT_FILE\" 2>/dev/null || echo 0); n=$((n+1));"
            " echo $n > \"$FAKE_COUNT_FILE\"\n"
            '    if [ -n "${FAKE_SENTINEL_AFTER:-}" ] && [ "$n" -lt "$FAKE_SENTINEL_AFTER" ]; then'
            ' echo ""; else echo "${FAKE_SENTINEL_MASTER:-}"; fi ;;\n'
            "  *role*)\n"
            '    case "$args" in *"shared-valkey-0."*) echo "${FAKE_P0_ROLE:-}";; esac ;;\n'
            "esac\n"
        )
        (binpath / "valkey-server").write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> '" + str(log) + "'\n"
        )
        (binpath / "valkey-sentinel").write_text(
            "#!/bin/sh\nprintf '%s\\n' \"$*\" >> '" + str(log) + "'\n"
        )
        for f in binpath.iterdir():
            f.chmod(0o755)
        self.env["FAKE_COUNT_FILE"] = str(Path(self.dir.name, "count"))
        self.script = Path(self.dir.name, "script.sh")
        self.script.write_text(script)

    def run(self, pod_name: str, timeout: float = 15.0):
        env = dict(self.env, POD_NAME=pod_name)
        try:
            proc = subprocess.run(
                ["sh", str(self.script)], env=env, capture_output=True,
                text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return None, (exc.stdout or "") + (exc.stderr or ""), True
        return proc.returncode, proc.stdout + proc.stderr, False

    def servers(self) -> list[str]:
        if not self.log.exists():
            return []
        return self.log.read_text().splitlines()

    def close(self):
        self.dir.cleanup()


class StartValkeyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.script = config_map()["start-valkey.sh"]

    def _run(self, scenario: dict, pod: str, timeout: float = 30.0):
        r = Runner(self.script, scenario)
        self.addCleanup(r.close)
        rc, out, timed_out = r.run(pod, timeout=timeout)
        return r, rc, out, timed_out

    def test_sentinel_says_master_is_me_starts_as_master_not_replica_of_pod0(self) -> None:
        # The INFRA-822 case: the master pod restarts and Sentinel still knows
        # it as master. It must come back as master, never --replicaof pod 0.
        r, rc, out, timed_out = self._run(
            {"FAKE_SENTINEL_MASTER": f"shared-valkey-2.{HEADLESS}"}, "shared-valkey-2"
        )
        self.assertEqual((rc, timed_out), (0, False), out)
        self.assertEqual(len(r.servers()), 1)
        self.assertNotIn("--replicaof", r.servers()[0])

    def test_known_other_master_replicates_to_it(self) -> None:
        r, rc, out, timed_out = self._run(
            {"FAKE_SENTINEL_MASTER": f"shared-valkey-1.{HEADLESS}"}, "shared-valkey-2"
        )
        self.assertEqual((rc, timed_out), (0, False), out)
        self.assertIn(f"--replicaof shared-valkey-1.{HEADLESS} 6379", r.servers()[0])

    def test_no_sentinel_answer_pod0_starts_as_master(self) -> None:
        r, rc, out, timed_out = self._run({"FAKE_SENTINEL_MASTER": ""}, "shared-valkey-0")
        self.assertEqual((rc, timed_out), (0, False), out)
        self.assertNotIn("--replicaof", r.servers()[0])

    def test_no_sentinel_answer_replicates_to_pod0_only_after_its_role_says_master(self) -> None:
        r, rc, out, timed_out = self._run(
            {"FAKE_SENTINEL_MASTER": "", "FAKE_P0_ROLE": "master"}, "shared-valkey-1"
        )
        self.assertEqual((rc, timed_out), (0, False), out)
        self.assertIn(f"--replicaof shared-valkey-0.{HEADLESS} 6379", r.servers()[0])

    def test_no_master_anywhere_never_replicates_to_pod0_blindly(self) -> None:
        # Pod 0 is a slave (or unreachable) and Sentinel knows nothing: pod 1
        # must wait, not recreate the circular loop of 04-07/10-10.
        r, rc, out, timed_out = self._run(
            {"FAKE_SENTINEL_MASTER": "", "FAKE_P0_ROLE": "slave"},
            "shared-valkey-1", timeout=32.0,
        )
        self.assertTrue(timed_out, "the script should wait, not start a wrong replica")
        for s in r.servers():
            self.assertNotIn("--replicaof", s)

    def test_late_sentinel_answer_is_followed(self) -> None:
        # Sentinel answers nothing for the first probes and then names this
        # pod as master (restart racing with sentinel recovery): it must end up
        # master, not replica of pod 0.
        r, rc, out, timed_out = self._run(
            {"FAKE_SENTINEL_MASTER": f"shared-valkey-1.{HEADLESS}",
             "FAKE_SENTINEL_AFTER": 14, "FAKE_P0_ROLE": "slave"},
            "shared-valkey-1", timeout=45.0,
        )
        self.assertEqual((rc, timed_out), (0, False), out)
        self.assertEqual(len(r.servers()), 1)
        self.assertNotIn("--replicaof", r.servers()[0])


class StartSentinelTest(unittest.TestCase):
    def setUp(self) -> None:
        self.script = config_map()["start-sentinel.sh"]

    def _conf_written(self, r: Runner, pod: str) -> str:
        data = Path(r.dir.name)
        (data / "data").mkdir(exist_ok=True)
        rc, out, timed_out = r.run(pod)
        self.assertEqual((rc, timed_out), (0, False), out)
        # fake valkey-sentinel receives the conf path as its only argument
        conf_path = Path(r.servers()[0])
        self.assertEqual(str(conf_path), "/data/sentinel.conf")
        return "/data/sentinel.conf"

    def test_myid_is_stable_per_pod_across_restarts(self) -> None:
        r = Runner(self.script, {})
        self.addCleanup(r.close)
        # /data is absolute in the script; run it with a bind of the temp dir by
        # rewriting only the CONF line for the sandbox.
        sandboxed = self.script.replace("CONF=/data/sentinel.conf", f"CONF={r.dir.name}/sentinel.conf")
        r.script.write_text(sandboxed)
        ids = []
        for _ in range(2):
            rc, out, timed_out = r.run("shared-valkey-1")
            self.assertEqual((rc, timed_out), (0, False), out)
            conf = Path(r.dir.name, "sentinel.conf").read_text()
            line = [l for l in conf.splitlines() if l.startswith("sentinel myid ")]
            self.assertEqual(len(line), 1, conf)
            ids.append(line[0].split()[-1])
        expected = hashlib.sha1(b"shared-valkey-1").hexdigest()
        self.assertEqual(ids[0], expected)
        self.assertEqual(ids[0], ids[1], "myid must survive restarts (no ghost sentinels)")

    def test_monitor_still_points_to_pod0_with_quorum_2(self) -> None:
        r = Runner(self.script, {})
        self.addCleanup(r.close)
        sandboxed = self.script.replace("CONF=/data/sentinel.conf", f"CONF={r.dir.name}/sentinel.conf")
        r.script.write_text(sandboxed)
        rc, out, timed_out = r.run("shared-valkey-2")
        self.assertEqual((rc, timed_out), (0, False), out)
        conf = Path(r.dir.name, "sentinel.conf").read_text()
        self.assertIn(f"sentinel monitor shared-cache-master shared-valkey-0.{HEADLESS} 6379 2", conf)


class LabelerTest(unittest.TestCase):
    def test_labeler_logs_role_changes(self) -> None:
        args = labeler_args()
        self.assertIn("role: ${prev:-unknown} -> ${role:-none}", args)


if __name__ == "__main__":
    unittest.main()
