#!/usr/bin/env python3
"""Read or replace the Tailscale ACL policy of the tailnet from the CLI.

Replaces the "open the admin console with Dani's passkey" toil (INFRA-1312:
six documented ACL changes blocked on a human gesture). Uses a dedicated
OAuth client with scopes policy_file:write + devices:core:write — NOT the
auth-key client (.ts-oauth-id / .ts-oauth-secret), which cannot touch the
policy file.

Credentials are read from files (mode 0600), never from argv, reusing the
helpers of ts_mint_authkey.py:
  TS_ACL_OAUTH_ID_FILE     (default /home/dibanez/k8s/.ts-oauth-acl-id)
  TS_ACL_OAUTH_SECRET_FILE (default /home/dibanez/k8s/.ts-oauth-acl-secret)
or directly from env TS_ACL_OAUTH_CLIENT_ID / TS_ACL_OAUTH_CLIENT_SECRET.

Tailnet slug: the API does NOT resolve the MagicDNS name (taile0ad27) nor
`-`; the slug is the tailnet name shown by `tailscale status` CurrentTailnet.Name:
  TS_TAILNET_SLUG          (default e-dani.com)

Usage:
  ts_acl_policy.py get                 # print the current policy (HuJSON) to stdout
  ts_acl_policy.py put <file>          # replace the policy with the file contents
  ts_acl_policy.py check <file>        # PUT the file and fail if the API rejects it,
                                       # then restore the previous policy

Logs go to stderr; the policy body goes to stdout only, so the caller can do:
  ts_acl_policy.py get > /tmp/acl.hujson
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from ts_mint_authkey import access_token, log, read_cred

BASE = "https://api.tailscale.com/api/v2"
DEFAULT_SLUG = "e-dani.com"


def api(method: str, path: str, token: str, body: bytes | None = None) -> bytes:
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} failed {exc.code}: {exc.read().decode()[:300]}")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "get"
    slug = os.environ.get("TS_TAILNET_SLUG", DEFAULT_SLUG)
    tok = access_token(
        read_cred("TS_ACL_OAUTH_CLIENT_ID", "TS_ACL_OAUTH_ID_FILE", "/home/dibanez/k8s/.ts-oauth-acl-id"),
        read_cred("TS_ACL_OAUTH_CLIENT_SECRET", "TS_ACL_OAUTH_SECRET_FILE", "/home/dibanez/k8s/.ts-oauth-acl-secret"),
    )
    acl_path = f"/tailnet/{urllib.parse.quote(slug)}/acl-policy"

    if cmd == "get":
        sys.stdout.buffer.write(api("GET", acl_path, tok))
        return

    if cmd in ("put", "check"):
        try:
            with open(sys.argv[2], "rb") as f:
                new_policy = f.read()
        except (IndexError, OSError) as exc:
            raise SystemExit(f"put/check need a policy file: {exc}")
        if cmd == "put":
            api("PUT", acl_path, tok, new_policy)
            log("policy updated")
            return
        # check: PUT, then restore what was there before, so the criterion
        # "the API accepts this policy" is proven without leaving it applied.
        previous = api("GET", acl_path, tok)
        api("PUT", acl_path, tok, new_policy)
        api("PUT", acl_path, tok, previous)
        log("policy accepted by the API and previous policy restored")
        return

    raise SystemExit("usage: ts_acl_policy.py get | put <file> | check <file>")


if __name__ == "__main__":
    main()
