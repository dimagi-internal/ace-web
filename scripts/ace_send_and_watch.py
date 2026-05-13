"""Send a chat message into an existing session and STAY CONNECTED.

Unlike ace_kick_off_run.py which disconnects after stream_start, this
holds the WS open so the consumer's turn task isn't GC'd when the
client goes away. Streams events to stdout (or `/dev/null` if --quiet)
and keeps printing summary lines per assistant turn / tool call.

Usage:
  ACE_URL=https://labs.connect.dimagi.com/ace \
  ACE_E2E_TOKEN=... \
  ACE_USER_EMAIL=jjackson@dimagi.com \
  ACE_WORKSPACE=dimagi-team \
  uv run python scripts/ace_send_and_watch.py <session-slug> "<message>" [--max-seconds 1800]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from http.cookies import SimpleCookie
from urllib.parse import urlparse

import httpx
import websockets


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_slug")
    parser.add_argument("message")
    parser.add_argument("--max-seconds", type=int, default=1800)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    ace_url = os.environ.get("ACE_URL", "https://labs.connect.dimagi.com/ace").rstrip("/")
    e2e_token = os.environ.get("ACE_E2E_TOKEN")
    email = os.environ.get("ACE_USER_EMAIL", "jjackson@dimagi.com")
    if not e2e_token:
        print("ACE_E2E_TOKEN env var is required", file=sys.stderr)
        return 2

    parsed = urlparse(ace_url)
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    ws_base = f"{ws_scheme}://{parsed.netloc}{parsed.path}"

    async with httpx.AsyncClient() as http:
        r = await http.post(
            f"{ace_url}/auth/e2e-login/",
            json={"email": email, "token": e2e_token},
        )
        r.raise_for_status()
        jar = SimpleCookie()
        for sc in r.headers.get_list("set-cookie"):
            jar.load(sc)
        cookie_header = "; ".join(f"{k}={m.value}" for k, m in jar.items())

    ws_url = f"{ws_base}/ws/sessions/{args.session_slug}/"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    print(f"[connect] {ws_url}")
    async with websockets.connect(
        ws_url,
        additional_headers=[("Cookie", cookie_header), ("Origin", origin)],
        ping_interval=20,
        ping_timeout=20,
        max_size=64 * 1024 * 1024,
    ) as ws:
        draft_version = 0

        async def _read_one(timeout=1.0):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                return json.loads(raw)
            except asyncio.TimeoutError:
                return None

        # Drain initial frames to learn draft version.
        while True:
            frame = await _read_one(0.8)
            if frame is None:
                break
            t = frame.get("event") or frame.get("type")
            d = frame.get("data") or {}
            if "version" in d:
                draft_version = int(d["version"])
        print(f"[draft] starting version={draft_version}")

        await ws.send(json.dumps({
            "action": "draft.update",
            "data": {"version": draft_version, "body": args.message},
        }))
        await _read_one(5.0)
        await ws.send(json.dumps({"action": "chat.send", "data": {}}))
        print(f"[sent] {args.message[:120]}")

        start = time.monotonic()
        last_event_at = time.monotonic()
        tool_counts: dict[str, int] = {}
        delta_chars = 0
        while time.monotonic() - start < args.max_seconds:
            frame = await _read_one(15.0)
            if frame is None:
                idle = time.monotonic() - last_event_at
                print(f"[idle] no events in {idle:.0f}s "
                      f"(deltas={delta_chars}c, tools={dict(tool_counts)})")
                continue
            last_event_at = time.monotonic()
            t = frame.get("event") or frame.get("type")
            d = frame.get("data") or {}
            if t in ("chat.stream_delta", "chat.delta"):
                delta_chars += len(d.get("text") or "")
                if not args.quiet:
                    # Print delta text incrementally on the same line.
                    sys.stdout.write(d.get("text") or "")
                    sys.stdout.flush()
            elif t == "chat.tool_use":
                name = d.get("name") or "?"
                tool_counts[name] = tool_counts.get(name, 0) + 1
                print(f"\n[tool_use #{sum(tool_counts.values())}] {name}")
            elif t == "chat.tool_result":
                preview = (d.get("plaintext") or "")[:120].replace("\n", " ")
                print(f"[tool_result] {preview}")
            elif t == "chat.stream_complete":
                print(f"\n[done] total_deltas={delta_chars}c "
                      f"tool_counts={dict(tool_counts)}")
                return 0
            elif t == "chat.stream_error":
                print(f"\n[error] {d.get('detail')}")
                return 1
            elif t == "chat.stream_cancelled":
                print(f"\n[cancelled] partial_len={d.get('partial_len')}")
                return 2
            elif t == "chat.stream_start":
                print("[stream_start]")
            elif t in ("draft.updated", "draft.committed", "presence.joined",
                       "presence.left", "session.state"):
                pass
            else:
                if not args.quiet:
                    print(f"[{t}]")
        print(f"\n[timeout] reached --max-seconds={args.max_seconds}")
        return 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
