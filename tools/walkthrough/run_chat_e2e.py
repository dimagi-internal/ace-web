"""Drive the deployed ace-web chat over WebSocket as the e2e bot.

A smoke harness for "can the deployed claude subprocess stay alive long
enough to finish an ACE skill / phase / full /ace:run?" Authenticates as
ace@dimagi-ai.com via /auth/e2e-login/, creates a fresh session, posts a
single prompt, and streams every chat.* event with timestamps until the
turn completes (or errors / times out).

Usage:
    ACE_WEB_BASE_URL=https://labs.connect.dimagi.com/ace \\
    ACE_E2E_AUTH_TOKEN=... \\
    python tools/walkthrough/run_chat_e2e.py "your prompt here" \\
        [--timeout-seconds 2400] [--session-title "Tier A smoke"]

Prints one line per event to stdout (machine-readable, ts-prefixed) and
a summary at the end. Exit codes:
    0 = chat.stream_complete observed
    1 = chat.stream_error observed
    2 = timeout
    3 = WebSocket failed before any chat event
    4 = setup (login / session create) failed
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

logger = logging.getLogger("run_chat_e2e")

DEFAULT_BASE = "https://labs.connect.dimagi.com/ace"
DEFAULT_EMAIL = "ace@dimagi-ai.com"
DEFAULT_TIMEOUT = 2400  # 40 minutes — Tier C may push 30+


async def _e2e_login(client: httpx.AsyncClient, base: str, email: str, token: str) -> None:
    resp = await client.post(
        f"{base}/auth/e2e-login/",
        json={"email": email, "token": token},
        headers={"Origin": _origin(base)},
    )
    resp.raise_for_status()


async def _create_session(client: httpx.AsyncClient, base: str, title: str) -> str:
    csrf = client.cookies.get("csrftoken_ace", "")
    resp = await client.post(
        f"{base}/api/sessions",
        json={"title": title},
        headers={"X-CSRFToken": csrf, "Referer": f"{base}/", "Origin": _origin(base)},
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(f"create session failed: {body['error']}")
    return body["data"]["slug"]


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
    prompt: str,
    timeout_seconds: float,
) -> int:
    """Open the WS, send draft+chat, stream events until terminal. Returns exit code."""
    ws_url = _ws_url(base, slug)
    cookie_header = "; ".join(f"{k}={v}" for k, v in cookies.items())

    started = time.monotonic()
    deadline = started + timeout_seconds

    print(f"[{_ts()}] connecting WS: {ws_url}")
    async with websockets.connect(
        ws_url,
        additional_headers={"Cookie": cookie_header, "Origin": _origin(base)},
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
    parser.add_argument("prompt", help="The prompt to send into the chat")
    parser.add_argument("--base-url", default=os.environ.get("ACE_WEB_BASE_URL", DEFAULT_BASE))
    parser.add_argument("--email", default=os.environ.get("ACE_E2E_EMAIL", DEFAULT_EMAIL))
    parser.add_argument(
        "--token", default=os.environ.get("ACE_E2E_AUTH_TOKEN", ""),
        help="ACE_E2E_AUTH_TOKEN (default: from env)",
    )
    parser.add_argument("--session-title", default="e2e smoke")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--reuse-session-slug", default="",
                        help="Skip session creation and use an existing slug")
    args = parser.parse_args()

    if not args.token:
        print("ERROR: ACE_E2E_AUTH_TOKEN not set", file=sys.stderr)
        return 4

    base = args.base_url.rstrip("/")
    print(f"[{_ts()}] base_url={base}")
    print(f"[{_ts()}] email={args.email} timeout={args.timeout_seconds}s")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as http:
        try:
            await _e2e_login(http, base, args.email, args.token)
        except Exception as exc:
            print(f"[{_ts()}] e2e-login failed: {exc}")
            return 4
        print(f"[{_ts()}] e2e-login OK as {args.email}")

        if args.reuse_session_slug:
            slug = args.reuse_session_slug
            print(f"[{_ts()}] reusing session slug={slug}")
        else:
            try:
                slug = await _create_session(http, base, args.session_title)
            except Exception as exc:
                print(f"[{_ts()}] session create failed: {exc}")
                return 4
            print(f"[{_ts()}] session created slug={slug}")

        cookies = {k: v for k, v in http.cookies.items()}

    try:
        return await _drive_chat(
            base, slug, cookies, args.prompt, float(args.timeout_seconds)
        )
    except TimeoutError as exc:
        print(f"[{_ts()}] timeout: {exc}")
        return 2
    except Exception as exc:
        print(f"[{_ts()}] unhandled exception: {type(exc).__name__}: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
