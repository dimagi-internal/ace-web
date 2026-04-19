#!/usr/bin/env python3
"""Upload this laptop's claude CLI credentials to a deployed ace-web.

The server no longer runs ``claude setup-token`` itself — instead, you
run ``claude setup-token`` (or just use the CLI normally, which caches
credentials) once on your laptop, then run this script to ship the
cached credential blob to the ace-web server. The server writes it to
``$ACE_CLAUDE_HOME/.claude/.credentials.json`` so its own ``claude -p``
subprocess reads it natively, including auto-refresh via the refresh
token.

Usage:
    ACE_URL=https://labs.connect.dimagi.com/ace \\
    ACE_TOKEN=<personal bearer token from /settings or ACE_E2E_AUTH_TOKEN> \\
    python scripts/ace_cli_login.py

Flags:
    --url      server base URL (overrides $ACE_URL)
    --token    bearer token (overrides $ACE_TOKEN)
    --email    for e2e-login fallback (default ace-repro@dimagi.com)
    --dry-run  show the blob that would be uploaded, don't POST
    --scope    "user" (default) writes your personal blob; "global" writes
               the instance-wide fallback (admin only)
    --global   shorthand for --scope=global
    --from     source: "keychain" (macOS), "file" (Linux), or "auto"

Exit codes:
    0 = uploaded, server confirms authenticated=True
    1 = local credentials not found or malformed
    2 = upload succeeded but server failed live check (token stored,
        but ``claude -p`` from the server still 401s — check server logs)
    3 = network / HTTP error
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import urllib.error
import urllib.request

KEYCHAIN_SERVICE = "Claude Code-credentials"
LINUX_CRED_PATH = os.path.expanduser("~/.claude/.credentials.json")


def load_blob_from_keychain() -> dict:
    """macOS: read the JSON blob out of Keychain via ``security``."""
    proc = subprocess.run(
        [
            "security", "find-generic-password",
            "-s", KEYCHAIN_SERVICE, "-w",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise FileNotFoundError(
            f"security find-generic-password failed: {proc.stderr.strip() or 'no output'}"
        )
    return json.loads(proc.stdout)


def load_blob_from_file(path: str = LINUX_CRED_PATH) -> dict:
    """Linux / generic: read ``~/.claude/.credentials.json``."""
    with open(path) as f:
        return json.load(f)


def load_blob(source: str) -> dict:
    if source == "auto":
        source = "keychain" if platform.system() == "Darwin" else "file"
    if source == "keychain":
        return load_blob_from_keychain()
    if source == "file":
        return load_blob_from_file()
    raise ValueError(f"unknown source: {source}")


def post_upload(url: str, token: str, blob: dict, scope: str = "user") -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + f"/api/auth/cli/upload?scope={scope}",
        data=json.dumps(blob).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"upload failed: HTTP {exc.code} — {body[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"upload failed: {exc}") from exc
    if body.get("error"):
        raise RuntimeError(f"upload rejected: {body['error']}")
    return body.get("data") or {}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", default=os.environ.get("ACE_URL", ""))
    p.add_argument("--token", default=os.environ.get("ACE_TOKEN", ""))
    p.add_argument(
        "--from", dest="source", choices=("auto", "keychain", "file"),
        default="auto",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--scope",
        choices=("user", "global"),
        default="user",
        help="upload to your personal blob (default) or the instance-wide fallback (requires admin)",
    )
    p.add_argument(
        "--global",
        dest="scope",
        action="store_const",
        const="global",
        help="shorthand for --scope global (admin only)",
    )
    args = p.parse_args()

    if not args.dry_run:
        if not args.url:
            print("error: --url or $ACE_URL required", file=sys.stderr)
            return 3
        if not args.token:
            print(
                "error: --token or $ACE_TOKEN required\n"
                "  mint one at $ACE_URL/settings (or use ACE_E2E_AUTH_TOKEN)",
                file=sys.stderr,
            )
            return 3

    try:
        blob = load_blob(args.source)
    except FileNotFoundError as exc:
        print(f"error: no local credentials found — {exc}", file=sys.stderr)
        print(
            "  run ``claude setup-token`` or use the CLI once to cache credentials",
            file=sys.stderr,
        )
        return 1
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"error: malformed local credentials — {exc}", file=sys.stderr)
        return 1

    # Shape: keychain returns {"claudeAiOauth": {...}} already; file too.
    access = (blob.get("claudeAiOauth") or {}).get("accessToken") or ""
    if not access.startswith("sk-ant-oat"):
        print(
            "error: blob loaded but accessToken looks wrong "
            f"(prefix={access[:15]!r})",
            file=sys.stderr,
        )
        return 1

    print(f"found credentials (accessToken prefix={access[:15]}, len={len(access)})")

    if args.dry_run:
        redacted = {
            "claudeAiOauth": {
                **{k: v for k, v in (blob.get("claudeAiOauth") or {}).items()
                   if k not in ("accessToken", "refreshToken")},
                "accessToken": access[:15] + "...",
                "refreshToken": "<redacted>",
            }
        }
        print(json.dumps(redacted, indent=2))
        return 0

    try:
        data = post_upload(args.url, args.token, blob, scope=args.scope)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3

    print(f"uploaded: {data}")
    if not data.get("authenticated"):
        print(
            "warning: server stored the token but the live check failed. "
            "check server logs for `CLI token check`.",
            file=sys.stderr,
        )
        return 2
    print("✓ server confirms authenticated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
