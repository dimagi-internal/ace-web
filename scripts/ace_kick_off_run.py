"""Programmatically kick off `/ace:run <slug>` on a deployed ace-web.

Flow:
  1. POST /auth/e2e-login/ as jjackson@dimagi.com (shared-secret auth)
  2. GET /api/opps/<slug>/working-session  → working session slug
  3. WS connect to /ace/ws/sessions/<slug>/ with the session cookie
  4. Wait for initial state to learn draft version
  5. draft.update + chat.send → server starts the turn
  6. Disconnect — the turn keeps running on the server

Usage:
  ACE_URL=https://labs.connect.dimagi.com/ace \
  ACE_E2E_TOKEN=... \
  ACE_USER_EMAIL=jjackson@dimagi.com \
  ACE_WORKSPACE=dimagi-team \
  uv run python scripts/ace_kick_off_run.py leep-paint-collection
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import httpx
import websockets


async def main(opp_slug: str) -> int:
    ace_url = os.environ.get("ACE_URL", "https://labs.connect.dimagi.com/ace").rstrip("/")
    e2e_token = os.environ.get("ACE_E2E_TOKEN")
    email = os.environ.get("ACE_USER_EMAIL", "jjackson@dimagi.com")
    workspace = os.environ.get("ACE_WORKSPACE", "dimagi-team")
    if not e2e_token:
        print("ACE_E2E_TOKEN env var is required", file=sys.stderr)
        return 2

    parsed = urlparse(ace_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_base = f"{ws_scheme}://{parsed.netloc}{parsed.path}"

    async with httpx.AsyncClient() as http:
        # Step 1: e2e-login → session cookie
        r = await http.post(
            f"{ace_url}/auth/e2e-login/",
            json={"email": email, "token": e2e_token},
        )
        r.raise_for_status()
        cookie_jar = SimpleCookie()
        for set_cookie in r.headers.get_list("set-cookie"):
            cookie_jar.load(set_cookie)
        # Tenant-specific cookies per CLAUDE.md.
        cookie_header = "; ".join(
            f"{k}={m.value}" for k, m in cookie_jar.items()
        )
        if "sessionid_ace" not in cookie_header:
            print(
                f"e2e-login did not return sessionid_ace; "
                f"got: {list(cookie_jar.keys())}",
                file=sys.stderr,
            )
            return 3
        print(f"[1/4] e2e-login OK as {email}")

        # Step 2: working session
        r = await http.get(
            f"{ace_url}/api/opps/{opp_slug}/working-session",
            headers={"Cookie": cookie_header, "X-Workspace": workspace},
        )
        r.raise_for_status()
        session_slug = r.json()["data"]["working_session_slug"]
        print(f"[2/4] working session: {session_slug}")

    # Step 3: WS connect
    ws_url = f"{ws_base}/ws/sessions/{session_slug}/"
    print(f"[3/4] connecting to {ws_url}")
    # AllowedHostsOriginValidator rejects WS without an Origin header
    # matching ALLOWED_HOSTS — match the public origin.
    origin = f"{parsed.scheme}://{parsed.netloc}"
    async with websockets.connect(
        ws_url,
        additional_headers=[("Cookie", cookie_header), ("Origin", origin)],
    ) as ws:
        # Wait for the initial state frame so we learn the active draft's
        # version. The consumer sends one on connect.
        draft_version = 0
        draft_body = ""
        # Collect up to 1.5s of initial frames so we see draft state.
        async def _initial_frames():
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    yield json.loads(msg)
            except TimeoutError:
                return
        async for frame in _initial_frames():
            t = frame.get("type") or frame.get("event")
            if t in ("draft.updated", "session.snapshot", "draft.snapshot"):
                d = frame.get("data") or frame.get("draft") or {}
                if "version" in d:
                    draft_version = int(d["version"])
                if "body" in d:
                    draft_body = d.get("body") or ""
            print(f"  ← {t}")
        print(f"   current draft version={draft_version}, body_len={len(draft_body)}")

        text = f"/ace:run {opp_slug}"
        await ws.send(json.dumps({
            "action": "draft.update",
            "data": {"version": draft_version, "body": text},
        }))
        # Wait for draft.updated ack
        try:
            ack = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"  ← {json.loads(ack).get('type') or json.loads(ack).get('event')}")
        except TimeoutError:
            print("  (no draft.update ack within 5s)", file=sys.stderr)
            return 4

        await ws.send(json.dumps({"action": "chat.send", "data": {}}))
        print(f"[4/4] sent: chat.send  →  text='{text}'")

        # Wait for chat.stream_start so we know the server received it.
        try:
            for _ in range(8):
                msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                evt = json.loads(msg)
                t = evt.get("type") or evt.get("event")
                print(f"  ← {t}")
                if t in ("chat.stream_start", "draft.committed"):
                    break
        except TimeoutError:
            print("  (timed out waiting for stream_start)", file=sys.stderr)
            return 5

        print("\n✓ Run kicked off. Open in browser:")
        print(f"  {ace_url}/w/{workspace}/chat/{session_slug}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: ace_kick_off_run.py <opp-slug>", file=sys.stderr)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1])))
