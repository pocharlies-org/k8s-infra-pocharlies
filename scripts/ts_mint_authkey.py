#!/usr/bin/env python3
"""Mint a fresh, tagged Tailscale auth key from a non-expiring OAuth client.

This removes the 90-day auth-key refresh toil: the OAuth client itself never
expires, and we mint a short-lived tagged key on demand right before a join.
Keys created via an OAuth client are always tagged; tagged nodes never expire.

Credentials are read from files (mode 0600), never from argv:
  TS_OAUTH_ID_FILE     (default /home/dibanez/k8s/.ts-oauth-id)
  TS_OAUTH_SECRET_FILE (default /home/dibanez/k8s/.ts-oauth-secret)
or directly from env TS_OAUTH_CLIENT_ID / TS_OAUTH_CLIENT_SECRET.

Tags come from env TAILSCALE_TAGS (comma-separated), default the KS-5 set.
The auth key itself is printed to stdout ONLY; all logs go to stderr so the
caller can do:  TAILSCALE_AUTH_KEY="$(ts_mint_authkey.py)"
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.tailscale.com/api/v2"
DEFAULT_TAGS = "tag:k8s,tag:ks5-control"


def log(msg: str) -> None:
    print(msg, file=sys.stderr)


def read_cred(env_name: str, file_env: str, default_file: str) -> str:
    val = os.environ.get(env_name)
    if val:
        return val.strip()
    path = os.environ.get(file_env, default_file)
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError as exc:
        raise SystemExit(f"Missing credential: set {env_name} or {file_env} ({path}): {exc}")


def main() -> None:
    client_id = read_cred("TS_OAUTH_CLIENT_ID", "TS_OAUTH_ID_FILE", "/home/dibanez/k8s/.ts-oauth-id")
    client_secret = read_cred("TS_OAUTH_CLIENT_SECRET", "TS_OAUTH_SECRET_FILE", "/home/dibanez/k8s/.ts-oauth-secret")

    tags = [t.strip() for t in os.environ.get("TAILSCALE_TAGS", DEFAULT_TAGS).split(",") if t.strip()]
    if not tags:
        raise SystemExit("No tags resolved; OAuth-minted keys require at least one tag.")
    expiry = int(os.environ.get("TS_AUTHKEY_EXPIRY_SECONDS", "3600"))
    reusable = os.environ.get("TS_AUTHKEY_REUSABLE", "true").lower() != "false"
    ephemeral = os.environ.get("TS_AUTHKEY_EPHEMERAL", "false").lower() == "true"

    # 1) client_credentials -> short-lived access token
    data = urllib.parse.urlencode({"client_id": client_id, "client_secret": client_secret}).encode()
    req = urllib.request.Request(
        BASE + "/oauth/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            access = json.load(r)["access_token"]
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"OAuth token exchange failed {exc.code}: {exc.read().decode()[:300]}")

    # 2) mint the tagged auth key
    body = json.dumps({
        "capabilities": {"devices": {"create": {
            "reusable": reusable, "ephemeral": ephemeral, "preauthorized": True, "tags": tags,
        }}},
        "expirySeconds": expiry,
        "description": "ks5-ha auto-mint",
    }).encode()
    req = urllib.request.Request(
        BASE + "/tailnet/-/keys", data=body,
        headers={"Authorization": "Bearer " + access, "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            created = json.load(r)
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Auth key mint failed {exc.code}: {exc.read().decode()[:300]}")

    key = created.get("key")
    if not key:
        raise SystemExit("No key field in mint response.")
    log(f"minted tagged auth key id={created.get('id')} tags={tags} reusable={reusable} "
        f"ephemeral={ephemeral} expirySeconds={expiry}")
    # the key itself: stdout only
    sys.stdout.write(key)


if __name__ == "__main__":
    main()
