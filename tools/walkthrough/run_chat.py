"""Drive the deployed ace-web chat over WebSocket using a Bearer PAT.

A smoke harness for "can the deployed claude subprocess stay alive long
enough to finish an ACE skill / phase / full /ace:run?" Authenticates with
``Authorization: Bearer $ACE_WEB_PAT_TOKEN``, creates a fresh session in a
workspace, posts one or more prompts (each driving a chat turn), and streams
every chat.* event with timestamps until the turn completes (or errors /
times out).

Usage:
    ACE_WEB_BASE_URL=https://labs.connect.dimagi.com/ace \\
    ACE_WEB_PAT_TOKEN=$(grep ^ACE_WEB_PAT_TOKEN= \\
        $CLAUDE_PLUGIN_DATA/.env | cut -d= -f2-) \\
    python tools/walkthrough/run_chat.py "your prompt here" \\
        [--workspace dimagi-team] \\
        [--timeout-seconds 2400] [--session-title "Tier A smoke"]

Mint a PAT one-time per machine via ``/ace:ace-web-pat-mint`` if you don't
have one yet.

Multi-turn (drive N turns into one session, sharing the cookie jar so the
ALB AWSALB stickiness cookie stays constant and all turns land on the same
ECS task):

    python tools/walkthrough/run_chat.py \\
        "Reply with HELLO." "Reply with WORLD." "Reply with AGAIN."

The single httpx.AsyncClient + cookie snapshot pattern is LOAD-BEARING for
reuse verification: a fresh client per invocation discards the AWSALB cookie
and ALB hashes the next WebSocket to a different task ~50% of the time on a
2-task service, which makes Phase 1B's long-lived subprocess pool look
broken when it isn't. The Bearer header authenticates; the AWSALB cookie
keeps task affinity.

Prints one line per event to stdout (machine-readable, ts-prefixed) and a
summary at the end. Exit codes:
    0 = all turns completed cleanly (chat.stream_complete)
    1 = a turn errored (chat.stream_error)
    2 = a turn timed out
    3 = WebSocket failed before any chat event
    4 = setup (PAT / session create) failed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from urllib.parse import urlparse

import httpx
import websockets

logger = logging.getLogger("run_chat")

DEFAULT_BASE = "https://labs.connect.dimagi.com/ace"
DEFAULT_WORKSPACE = "dimagi-team"
DEFAULT_TIMEOUT = 2400  # 40 minutes — Tier C may push 30+


async def _create_session(
    client: httpx.AsyncClient,
    base: str,
    workspace_slug: str,
    title: str,
    auth_headers: dict[str, str],
) -> str:
    resp = await client.post(
        f"{base}/api/w/{workspace_slug}/sessions",
        json={"title": title},
        headers={**auth_headers, "Origin": _origin(base)},
    )
    if resp.status_code != 201:
        raise RuntimeError(
            f"create session failed: HTTP {resp.status_code} {resp.text[:500]}"
        )
    body = resp.json()
    slug = body.get("slug")
    if not slug:
        raise RuntimeError(f"create session: no slug in response {body!r}")
    return slug


def _origin(base: str) -> str:
    p = urlparse(base)
    return f"{p.scheme}://{p.netloc}"


def _ws_url(base: str, slug: str) -> str:
    p = urlparse(base)
    scheme = "wss" if p.scheme == "https" else "ws"
    return f"{scheme}://{p.netloc}{p.path}/ws/sessions/{slug}/"


def _ts() -> str:
    return time.strftime("%H:%M:%S", time.localtime())


async def _drive_chat(
    base: str,
    slug: str,
    cookies: dict[str, str],
    auth_headers: dict[str, str],
    prompt: str,
    timeout_seconds: float,
) -> int:
    """Open the WS, send draft+chat, stream events until terminal. Returns exit code."""
    ws_url = _ws_url(base, slug)
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())

    started = time.monotonic()
    deadline = started + timeout_seconds

    print(f"[{_ts()}] connecting WS: {ws_url}")
    handshake_headers = {**auth_headers, "Origin": _origin(base)}
    if cookie_header:
        handshake_headers["Cookie"] = cookie_header
    async with websockets.connect(
        ws_url,
        additional_headers=handshake_headers,
        max_size=8 * 1024 * 1024,
        # Keep the connection alive even during long quiet stretches. The
        # websockets library default ping interval is 20s which matches the
        # frontend; making it explicit here so the test harness behaves the
        # same as a real browser.
        ping_interval=20.0,
        ping_timeout=20.0,
        close_timeout=5.0,
    ) as ws:
        # 1. wait for session.state
        active_draft_id, active_version = await _await_session_state(ws, deadline)
        print(
            f"[{_ts()}] session.state received "
            f"(draft_id={active_draft_id}, version={active_version})"
        )

        # 2. send draft.update with the prompt
        await ws.send(json.dumps({
            "action": "draft.update",
            "data": {"version": active_version, "body": prompt},
        }))
        print(f"[{_ts()}] draft.update sent (body_chars={len(prompt)})")

        # 3. send chat.send to commit + spawn the turn
        await ws.send(json.dumps({"action": "chat.send", "data": {}}))
        print(f"[{_ts()}] chat.send dispatched")

        # 4. stream until terminal
        return await _stream_until_terminal(ws, deadline, started)


async def _await_session_state(ws, deadline: float) -> tuple[int, int]:
    """Loop until we get session.state. Other early events (presence.joined etc.) are echoed."""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for session.state")
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(30.0, remaining))
        except TimeoutError as exc:
            raise TimeoutError("session.state never arrived") from exc
        frame = json.loads(raw)
        event = frame.get("event")
        if event == "session.state":
            data = frame["data"]
            draft = data.get("active_draft") or {}
            return draft["id"], draft["version"]
        # Otherwise just echo and keep listening.
        print(f"[{_ts()}] (pre-state) {event}: {json.dumps(frame.get('data'))[:200]}")


async def _stream_until_terminal(ws, deadline: float, started: float) -> int:
    delta_chars = 0
    tool_use_count = 0
    tool_result_count = 0
    last_progress_at = started
    last_log_summary_at = started
    while True:
        now = time.monotonic()
        if now >= deadline:
            print(f"[{_ts()}] TIMEOUT after {now - started:.0f}s")
            return 2
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(45.0, deadline - now))
        except TimeoutError:
            elapsed = time.monotonic() - started
            since_progress = time.monotonic() - last_progress_at
            print(
                f"[{_ts()}] (idle) elapsed={elapsed:.0f}s "
                f"since_last_event={since_progress:.0f}s — keeping connection"
            )
            continue
        except websockets.ConnectionClosed as exc:
            print(f"[{_ts()}] WS closed unexpectedly: {exc}")
            return 3

        last_progress_at = time.monotonic()
        try:
            frame = json.loads(raw)
        except Exception:
            print(f"[{_ts()}] (malformed frame, skipping)")
            continue
        event = frame.get("event")
        data = frame.get("data") or {}

        if event == "chat.delta":
            text = data.get("text", "")
            delta_chars += len(text)
            # Don't spam stdout with every delta — emit a periodic progress line.
            if time.monotonic() - last_log_summary_at > 5.0:
                last_log_summary_at = time.monotonic()
                elapsed = time.monotonic() - started
                print(
                    f"[{_ts()}] streaming: elapsed={elapsed:.0f}s "
                    f"delta_chars={delta_chars} tool_use={tool_use_count} "
                    f"tool_result={tool_result_count}"
                )
        elif event == "chat.tool_use":
            tool_use_count += 1
            block = data.get("tool_block") or {}
            print(
                f"[{_ts()}] tool_use #{tool_use_count}: name={block.get('name', '?')} "
                f"input_keys={list((block.get('input') or {}).keys())}"
            )
        elif event == "chat.tool_result":
            tool_result_count += 1
            block = data.get("tool_block") or {}
            content_preview = str(block.get("content", ""))[:120].replace("\n", " ")
            print(
                f"[{_ts()}] tool_result #{tool_result_count}: "
                f"is_error={block.get('is_error', False)} preview={content_preview!r}"
            )
        elif event == "chat.stream_start":
            print(f"[{_ts()}] chat.stream_start: message_id={data.get('message_id')}")
        elif event == "chat.stream_complete":
            elapsed = time.monotonic() - started
            print(
                f"[{_ts()}] chat.stream_complete elapsed={elapsed:.0f}s "
                f"delta_chars={delta_chars} tool_use={tool_use_count} "
                f"tool_result={tool_result_count}"
            )
            return 0
        elif event == "chat.stream_error":
            print(f"[{_ts()}] chat.stream_error: {json.dumps(data)[:500]}")
            return 1
        elif event == "chat.stream_cancelled":
            print(f"[{_ts()}] chat.stream_cancelled")
            return 1
        elif event in ("draft.committed", "draft.updated"):
            pass  # noise
        else:
            preview = json.dumps(data)[:160]
            print(f"[{_ts()}] {event}: {preview}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "prompts",
        nargs="+",
        help=(
            "One or more prompts. Each drives a single chat turn against the "
            "same session, sharing one cookie jar — required to land all turns "
            "on the same ECS task via the ALB AWSALB stickiness cookie."
        ),
    )
    parser.add_argument("--base-url", default=os.environ.get("ACE_WEB_BASE_URL", DEFAULT_BASE))
    parser.add_argument(
        "--workspace", default=os.environ.get("ACE_WEB_WORKSPACE", DEFAULT_WORKSPACE),
        help="Workspace slug to create the session under (default: dimagi-team)",
    )
    parser.add_argument(
        "--pat", default=os.environ.get("ACE_WEB_PAT_TOKEN", ""),
        help="Bearer PAT (default: from $ACE_WEB_PAT_TOKEN). Mint via /ace:ace-web-pat-mint.",
    )
    parser.add_argument("--session-title", default="walkthrough smoke")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--reuse-session-slug", default="",
                        help="Skip session creation and use an existing slug")
    args = parser.parse_args()

    if not args.pat:
        print("ERROR: ACE_WEB_PAT_TOKEN not set. Mint one via /ace:ace-web-pat-mint.",
              file=sys.stderr)
        return 4

    base = args.base_url.rstrip("/")
    auth_headers = {"Authorization": f"Bearer {args.pat}"}
    print(f"[{_ts()}] base_url={base} workspace={args.workspace}")
    print(f"[{_ts()}] timeout={args.timeout_seconds}s prompts={len(args.prompts)}")

    # ONE httpx client = ONE persistent cookie jar. The ``cookies`` snapshot
    # below carries the ALB AWSALB stickiness cookie set on the first
    # response, so every subsequent WebSocket upgrade hashes to the same
    # ECS task and reuses Phase 1B's long-lived subprocess. A fresh client
    # per turn discards that cookie and re-rolls task affinity each time —
    # which makes the long-lived path look broken for cross-task hops.
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
        if args.reuse_session_slug:
            slug = args.reuse_session_slug
            # Touch the API once to seed the AWSALB cookie before WS upgrade.
            await http.get(f"{base}/api/health", headers=auth_headers)
            print(f"[{_ts()}] reusing session slug={slug}")
        else:
            try:
                slug = await _create_session(
                    http, base, args.workspace, args.session_title, auth_headers
                )
            except Exception as exc:
                print(f"[{_ts()}] session create failed: {exc}")
                return 4
            print(f"[{_ts()}] session created slug={slug}")
            print(f"[{_ts()}] view at: {base}/w/{args.workspace}/chat/{slug}")

        cookies = {k: v for k, v in http.cookies.items()}
        awsalb = cookies.get("AWSALB", "")
        if awsalb:
            print(f"[{_ts()}] AWSALB cookie present (first 24 chars): {awsalb[:24]!r}")
        else:
            print(f"[{_ts()}] WARNING: no AWSALB cookie — multi-turn will hop "
                  "ECS tasks and Phase 1B reuse won't engage")

    last_rc = 0
    multi = len(args.prompts) > 1
    for i, prompt in enumerate(args.prompts, 1):
        if multi:
            print(f"[{_ts()}] ─── turn {i}/{len(args.prompts)} ───")
        try:
            last_rc = await _drive_chat(
                base, slug, cookies, auth_headers, prompt, float(args.timeout_seconds)
            )
        except TimeoutError as exc:
            print(f"[{_ts()}] timeout: {exc}")
            return 2
        except Exception as exc:
            print(f"[{_ts()}] unhandled exception: {type(exc).__name__}: {exc}")
            return 3
        if last_rc != 0:
            remaining = len(args.prompts) - i
            if remaining:
                print(f"[{_ts()}] turn {i} returned rc={last_rc} — aborting "
                      f"remaining {remaining} prompt(s)")
            return last_rc

    return last_rc


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
