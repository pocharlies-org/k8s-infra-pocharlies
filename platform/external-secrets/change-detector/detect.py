"""onepassword-change-detector (DGX-506).

Every ExternalSecret on the onepassword ClusterSecretStore is refreshPolicy
OnChange (DGX-505), and keeps it when Kyverno moves it to onepassword-connect
(INFRA-511): ESO reads 1Password only when an ExternalSecret is created
or changes. This job is how a value rotated in the 1Password app still reaches
the cluster on its own, for 1-2 requests a run instead of one per reference.

The init container lists the vault once (`op item list`) into ITEMS_FILE. Here
each item's version is compared with the last run (ConfigMap STATE_CONFIGMAP);
for each item that changed, `force-sync=<now>` is set on the ExternalSecrets
that reference it, and on the ClusterExternalSecrets whose template does (ESO
copies a CES's force-sync to its children and drops one set on a child). The
first run, with no state, only records the baseline. State is saved after
the patches on purpose: a run that dies halfway forces the same items again
next time (one extra read each) instead of losing a rotation.

Keys follow 1Password secret-reference syntax without the vault,
`<item>/[section/]<field>`, and `dataFrom.extract.key` is the item: the item
is the first path segment, by title or by id.

Exit 1 on any error, so K8sCronJobFailed fires.
"""
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

ITEMS_FILE = os.environ.get("ITEMS_FILE", "/work/items.json")
# The stores whose ExternalSecrets are forced: the onepasswordSDK store and the
# 1Password Connect store that Kyverno moves them to (INFRA-511). Both read the
# same vault; `<item>/<field>` and `<item>` + property start with the same item.
STORES = {s.strip() for s in os.environ.get("STORE_NAMES", "onepassword,onepassword-connect").split(",") if s.strip()}
NS = os.environ.get("STATE_NAMESPACE", "external-secrets-operator")
CM = os.environ.get("STATE_CONFIGMAP", "onepassword-change-detector-state")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
API = "https://kubernetes.default.svc"
SA = "/var/run/secrets/kubernetes.io/serviceaccount"
ESO = "/apis/external-secrets.io/v1"
MERGE = "application/merge-patch+json"


def call(method, path, body=None, ctype="application/json"):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, method=method)
    with open(SA + "/token") as f:
        req.add_header("Authorization", "Bearer " + f.read().strip())
    if body is not None:
        req.add_header("Content-Type", ctype)
    ctx = ssl.create_default_context(cafile=SA + "/ca.crt")
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        raise


def referenced_items(spec):
    keys = [(d.get("remoteRef") or {}).get("key") for d in spec.get("data") or []]
    keys += [(d.get("extract") or {}).get("key") for d in spec.get("dataFrom") or []]
    return {k.split("/", 1)[0] for k in keys if k}


def on_store(spec):
    return (spec.get("secretStoreRef") or {}).get("name") in STORES


def force_sync(path, ts, label, forced):
    forced.append(label)
    if not DRY_RUN:
        call("PATCH", path, {"metadata": {"annotations": {"force-sync": ts}}}, MERGE)


def main():
    with open(ITEMS_FILE) as f:
        items = json.load(f)
    now = {i["id"]: {"title": i["title"], "version": i.get("version")} for i in items}

    cm = call("GET", f"/api/v1/namespaces/{NS}/configmaps/{CM}")
    prev = None
    if cm and "items.json" in (cm.get("data") or {}):
        prev = json.loads(cm["data"]["items.json"])

    changed = set()
    if prev is None:
        print(f"baseline: {len(now)} items recorded, nothing forced")
    else:
        for iid, it in now.items():
            old = prev.get(iid)
            if old is None or old.get("version") != it["version"]:
                changed |= {iid, it["title"]}
                if old:
                    changed.add(old["title"])
        print(f"{len(now)} items, changed: {sorted(now[i]['title'] for i in changed if i in now)}")

    forced = []
    if changed:
        ts = str(int(time.time()))
        for c in call("GET", f"{ESO}/clusterexternalsecrets")["items"]:
            spec = c["spec"].get("externalSecretSpec") or {}
            if on_store(spec) and referenced_items(spec) & changed:
                name = c["metadata"]["name"]
                force_sync(f"{ESO}/clusterexternalsecrets/{name}", ts,
                           f"ClusterExternalSecret/{name}", forced)
        for e in call("GET", f"{ESO}/externalsecrets")["items"]:
            meta, spec = e["metadata"], e["spec"]
            if any(o.get("kind") == "ClusterExternalSecret" for o in meta.get("ownerReferences") or []):
                continue
            if on_store(spec) and referenced_items(spec) & changed:
                ns, name = meta["namespace"], meta["name"]
                force_sync(f"{ESO}/namespaces/{ns}/externalsecrets/{name}", ts,
                           f"ExternalSecret/{ns}/{name}", forced)
    for f in forced:
        print(("would force-sync " if DRY_RUN else "force-sync ") + f)

    if DRY_RUN:
        return
    data = {"items.json": json.dumps(now, sort_keys=True)}
    if cm is None:
        call("POST", f"/api/v1/namespaces/{NS}/configmaps",
             {"metadata": {"name": CM, "labels": {"app.kubernetes.io/name": "onepassword-change-detector"}},
              "data": data})
    else:
        call("PATCH", f"/api/v1/namespaces/{NS}/configmaps/{CM}", {"data": data}, MERGE)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - any failure must fail the Job
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
