#!/usr/bin/env python3
"""INFRA-514 (P2 of INFRA-511): prove the 1Password Connect store is value-
equivalent to the 1Password SDK store before any ExternalSecret is switched.

How it works
------------
~260 ExternalSecrets labeled ``infra511-test=true`` (scaffolding applied by
hand, NOT in git, one per ``onepassword``-store ES) read the same 1Password
items through the ClusterSecretStore ``onepassword-connect`` and write them to
a twin Secret ``<name>-infra511`` in the same namespace. This tool reads BOTH
Secrets with kubectl, hashes every key's value with SHA-256 and prints one
row per key::

    NAMESPACE  EXTERNALSECRET  KEY  ORIG_SHA  TWIN_SHA  EQUAL

It never prints a secret value — only hashes. It only ever runs read-only
``kubectl get`` calls; it does not touch any SecretStore, does not annotate
force-sync and does not reconcile anything, so it cannot spend the 1Password
daily quota (the SDK store ``onepassword`` is out of quota; Connect serves
from its local cache).

Usage (against a live cluster)::

    python3 scripts/infra511_hash_compare.py           # hash table
    python3 scripts/infra511_hash_compare.py --count   # edge-case census

``--count`` classifies every live ExternalSecret / ClusterExternalSecret of
the ``onepassword`` store into the cases the Kyverno translation policy (P3)
must handle: remoteRef.key with no ``/`` (whole-item extract), with one ``/``
(item/field), with two or more (item/section/field — must be REJECTED, not
guessed), ``property`` already present, ``version`` set, ``dataFrom.find`` and
``generatorRef``. The census numbers belong in 50-entrega.md.

The Kubernetes surface is injectable (``run_kubectl``) so
tests/test_infra511_hash_compare.py runs the whole logic offline in CI.
"""
import argparse
import base64
import hashlib
import json
import subprocess
import sys

TWIN_LABEL = "infra511-test=true"
TWIN_SUFFIX = "-infra511"


def default_run_kubectl(args):
    """Read-only kubectl helper; raises RuntimeError with stderr on failure."""
    p = subprocess.run(["kubectl", *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(args)}: {p.stderr.strip()}")
    return json.loads(p.stdout)


def sha256_of_b64(value_b64):
    return hashlib.sha256(base64.b64decode(value_b64)).hexdigest()


def twin_rows(es_items, run_kubectl):
    """One dict per (ES, key) comparing Secret <name> vs Secret <name>-infra511.

    Covers both ``spec.data`` (secretKey) and ``dataFrom.extract`` (the twin
    Secret's keys are the item's field labels; the comparison is by key over
    the twin Secret's key set, which is exactly what Connect produced).
    """
    rows = []
    for es in es_items:
        ns = es["metadata"]["namespace"]
        name = es["metadata"]["name"]
        if not name.endswith(TWIN_SUFFIX):
            rows.append({"ns": ns, "es": name, "key": "-", "equal": False,
                         "why": "twin ES name does not end in " + TWIN_SUFFIX})
            continue
        orig_name = name[: -len(TWIN_SUFFIX)]
        twin_name = es.get("spec", {}).get("target", {}).get("name") or name
        try:
            twin = run_kubectl(["-n", ns, "get", "secret", twin_name, "-o", "json"])
        except RuntimeError as e:
            rows.append({"ns": ns, "es": name, "key": "-", "equal": False,
                         "why": "twin secret missing: " + str(e)})
            continue
        try:
            orig = run_kubectl(["-n", ns, "get", "secret", orig_name, "-o", "json"])
        except RuntimeError:
            orig = None
        orig_data = (orig or {}).get("data", {})
        for key, value in sorted((twin.get("data") or {}).items()):
            twin_hash = sha256_of_b64(value)
            if key in orig_data:
                orig_hash = sha256_of_b64(orig_data[key])
                rows.append({"ns": ns, "es": name, "key": key,
                             "orig_sha": orig_hash[:16], "twin_sha": twin_hash[:16],
                             "equal": orig_hash == twin_hash,
                             "why": "" if orig_hash == twin_hash else "hash differs"})
            else:
                rows.append({"ns": ns, "es": name, "key": key, "orig_sha": None,
                             "twin_sha": twin_hash[:16], "equal": False,
                             "why": "key absent in original secret"})
    return rows


def classify_ref(remote_ref):
    """Case of one remoteRef/extract per the P3 rules (C3)."""
    key = remote_ref.get("key", "")
    slashes = key.count("/")
    case = "key_no_slash" if slashes == 0 else "key_1slash" if slashes == 1 else "key_2plus_slash"
    cases = [case]
    if remote_ref.get("property"):
        cases.append("property_present")
    if remote_ref.get("version"):
        cases.append("version_set")
    return cases


def census(es_items, ces_items):
    """Edge-case census over ES/CES of the legacy `onepassword` store.

    ~20 lines, per nota-architect-plan.md C3: how many live references fall in
    each case the Kyverno translation must treat.
    """
    counts = {}
    def bump(case):
        counts[case] = counts.get(case, 0) + 1
    def walk(spec, kind):
        bump(kind)
        if spec.get("secretStoreRef", {}).get("name") != "onepassword":
            return
        bump(kind + "_onepassword_store")
        for d in spec.get("data") or []:
            for case in classify_ref(d.get("remoteRef") or {}):
                bump("data_" + case)
        for df in spec.get("dataFrom") or []:
            if df.get("extract"):
                for case in classify_ref(df["extract"]):
                    bump("extract_" + case)
            if df.get("find"):
                bump("dataFrom_find")
            if (df.get("sourceRef") or {}).get("generatorRef"):
                bump("generatorRef")
    for es in es_items:
        walk(es["spec"], "es")
    for ces in ces_items:
        walk(ces["spec"].get("externalSecretSpec") or {}, "ces")
    return counts


def main(argv=None, run_kubectl=None):
    run_kubectl = run_kubectl or default_run_kubectl
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--count", action="store_true", help="edge-case census instead of hash table")
    ap.add_argument("--label", default=TWIN_LABEL, help="twin ES selector (default %(default)s)")
    args = ap.parse_args(argv)

    if args.count:
        es = run_kubectl(["get", "externalsecret", "-A", "-o", "json"])["items"]
        ces = run_kubectl.get("clusterexternalsecret") and [] or run_kubectl(
            ["get", "clusterexternalsecret", "-A", "-o", "json"])["items"]
        es = [e for e in es if TWIN_SUFFIX not in e["metadata"]["name"]]
        for case, n in sorted(census(es, ces).items()):
            print(f"{case}: {n}")
        return 0

    es_items = run_kubectl(["get", "externalsecret", "-A", "-l", args.label, "-o", "json"])["items"]
    rows = twin_rows(es_items, run_kubectl)
    print(f"{'NAMESPACE':<24} {'EXTERNALSECRET':<44} {'KEY':<28} {'ORIG_SHA':<17} {'TWIN_SHA':<17} EQUAL")
    bad = 0
    for r in rows:
        bad += 0 if r["equal"] else 1
        print(f"{r['ns']:<24} {r['es']:<44} {r['key']:<28} "
              f"{str(r.get('orig_sha')):<17} {str(r.get('twin_sha')):<17} "
              f"{'YES' if r['equal'] else 'NO  ' + r['why']}")
    total = len(rows)
    print(f"\n{total - bad}/{total} keys equal")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
