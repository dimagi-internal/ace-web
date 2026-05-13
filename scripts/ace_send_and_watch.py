"""Send a chat message into an existing session and watch until it ends.

The exit decision is grounded in server state, not wall-clock:

  - WS event ``chat.stream_complete`` / ``chat.stream_error`` /
    ``chat.stream_cancelled`` → exit immediately (the canonical
    "this turn is over" signals).

  - In parallel, poll ``GET /api/sessions/<slug>/turn-state`` every
    ``--poll-seconds`` (default 30). When the endpoint reports
    ``running=false`` for two consecutive polls AND we haven't seen a
    completion event, the server-side turn task is gone — the script
    exits. Two polls because the WS receive race could be faster than
    the turn-task done-callback that clears the slug index.

  - No --max-seconds cap by default. The script keeps watching until
    one of the above signals fires or the user Ctrl+Cs. Pass
    ``--max-seconds`` only if you want a defensive ceiling for CI use.

Usage:
  ACE_URL=https://labs.connect.dimagi.com/ace \\
  ACE_E2E_TOKEN=... \\
  ACE_USER_EMAIL=jjackson@dimagi.com \\
  uv run python scripts/ace_send_and_watch.py <session-slug> "<message>"
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


async def _login(http: httpx.AsyncClient, ace_url: str, email: str, token: str) -> str:
    r = await http.post(
        f"{ace_url}/auth/e2e-login/",
        json={"email": email, "token": token},
    )
    r.raise_for_status()
    jar = SimpleCookie()
    for sc in r.headers.get_list("set-cookie"):
        jar.load(sc)
    return "; ".join(f"{k}={m.value}" for k, m in jar.items())


async def _poll_turn_state(
    ace_url: str,
    cookie: str,
    slug: str,
    poll_seconds: float,
    on_state,
    stop_event: asyncio.Event,
) -> None:
    """Poll the turn-state endpoint in a loop until ``stop_event`` is set.

    Calls ``on_state(state_dict)`` after each successful poll. Failures
    are logged and retried on the next interval — a transient API hiccup
    shouldn't kill the watch.
    """
    async with httpx.AsyncClient(timeout=10.0) as http:
        while not stop_event.is_set():
            try:
                r = await http.get(
                    f"{ace_url}/api/sessions/{slug}/turn-state",
                    headers={"Cookie": cookie},
                )
                if r.status_code == 200:
                    on_state(r.json().get("data") or {})
                else:
                    on_state({"_error": f"HTTP {r.status_code}"})
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                on_state({"_error": str(exc)})
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
            except asyncio.TimeoutError:
                pass


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_slug")
    parser.add_argument("message")
    parser.add_argument(
        "--poll-seconds", type=float, default=30.0,
        help="Interval between /turn-state polls (default 30).",
    )
    parser.add_argument(
        "--max-seconds", type=int, default=0,
        help="Optional wall-clock ceiling (0 = no ceiling). Default 0.",
    )
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
        cookie = await _login(http, ace_url, email, e2e_token)

    # Shared state between the WS reader and the polling loop.
    stop_event = asyncio.Event()
    exit_code = 0
    completion_seen = False
    # `running=false` must be observed twice in a row to count as
    # "turn ended". Single false reading can happen between chat.send
    # and the consumer task being installed in the slug index.
    consecutive_idle_polls = 0

    def _on_state(state: dict) -> None:
        nonlocal consecutive_idle_polls, exit_code
        if "_error" in state:
            print(f"[turn-state] error: {state['_error']}")
            return
        running = state.get("running", False)
        cli = state.get("cli") or {}
        cli_alive = cli.get("alive")
        pid = cli.get("pid")
        elapsed = cli.get("elapsed_s")
        last_age = cli.get("last_active_age_s")
        last_msg = state.get("last_message_at")
        bits = [f"running={running}"]
        if pid is not None:
            bits.append(f"pid={pid}")
        if elapsed is not None:
            bits.append(f"elapsed={elapsed:.0f}s")
        if last_age is not None:
            bits.append(f"idle={last_age:.0f}s")
        if last_msg is not None:
            bits.append(f"last_msg={last_msg}")
        if cli_alive is not None:
            bits.append(f"cli_alive={cli_alive}")
        print(f"[turn-state] {' '.join(bits)}")
        if running:
            consecutive_idle_polls = 0
        else:
            consecutive_idle_polls += 1
            if consecutive_idle_polls >= 2:
                # Two consecutive idle polls AND we haven't seen a
                # terminal stream event → the turn task is gone. If the
                # WS already delivered chat.stream_complete this branch
                # is preempted by the WS side; the dual check keeps the
                # script honest when the WS missed (or pre-empted) the
                # terminal event.
                print("[turn-state] running=false twice → exiting")
                if not completion_seen:
                    exit_code = 4
                stop_event.set()

    ws_url = f"{ws_base}/ws/sessions/{args.session_slug}/"
    origin = f"{parsed.scheme}://{parsed.netloc}"
    print(f"[connect] {ws_url}")

    poll_task = asyncio.create_task(
        _poll_turn_state(ace_url, cookie, args.session_slug, args.poll_seconds, _on_state, stop_event)
    )
    sanity_task = None
    if args.max_seconds > 0:
        async def _sanity():
            await asyncio.sleep(args.max_seconds)
            print(f"[sanity-cap] hit --max-seconds={args.max_seconds}")
            stop_event.set()
        sanity_task = asyncio.create_task(_sanity())

    start = time.monotonic()
    delta_chars = 0
    tool_counts: dict[str, int] = {}
    try:
        async with websockets.connect(
            ws_url,
            additional_headers=[("Cookie", cookie), ("Origin", origin)],
            ping_interval=20,
            ping_timeout=20,
            max_size=64 * 1024 * 1024,
        ) as ws:
            draft_version = 0
            # Drain initial frames to learn draft version.
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.8)
                    frame = json.loads(raw)
                except asyncio.TimeoutError:
                    break
                d = frame.get("data") or {}
                if "version" in d:
                    draft_version = int(d["version"])
            await ws.send(json.dumps({
                "action": "draft.update",
                "data": {"version": draft_version, "body": args.message},
            }))
            try:
                await asyncio.wait_for(ws.recv(), timeout=5.0)
            except asyncio.TimeoutError:
                pass
            await ws.send(json.dumps({"action": "chat.send", "data": {}}))
            print(f"[sent] {args.message[:120]}")

            async def _drain_ws():
                nonlocal delta_chars, completion_seen, exit_code
                while not stop_event.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
                    except asyncio.TimeoutError:
                        continue
                    frame = json.loads(raw)
                    t = frame.get("event") or frame.get("type")
                    d = frame.get("data") or {}
                    if t in ("chat.stream_delta", "chat.delta"):
                        delta_chars += len(d.get("text") or "")
                        if not args.quiet:
                            sys.stdout.write(d.get("text") or "")
                            sys.stdout.flush()
                    elif t == "chat.tool_use":
                        block = d.get("block") or {}
                        name = block.get("name") or "?"
                        tool_counts[name] = tool_counts.get(name, 0) + 1
                        print(f"\n[tool_use #{sum(tool_counts.values())}] {name}")
                    elif t == "chat.tool_result":
                        preview = (d.get("plaintext") or "")[:120].replace("\n", " ")
                        print(f"[tool_result] {preview}")
                    elif t == "chat.stream_complete":
                        print(f"\n[done] total_deltas={delta_chars}c tool_counts={dict(tool_counts)}")
                        completion_seen = True
                        stop_event.set()
                        return
                    elif t == "chat.stream_error":
                        print(f"\n[stream_error] {d.get('detail')}")
                        completion_seen = True
                        exit_code = 1
                        stop_event.set()
                        return
                    elif t == "chat.stream_cancelled":
                        print(f"\n[cancelled] partial_len={d.get('partial_len')}")
                        completion_seen = True
                        exit_code = 2
                        stop_event.set()
                        return
                    elif t == "chat.stream_start":
                        print("[stream_start]")
                    elif t in ("draft.updated", "draft.committed", "presence.joined",
                               "presence.left", "session.state"):
                        pass
                    elif not args.quiet:
                        print(f"[{t}]")

            ws_task = asyncio.create_task(_drain_ws())
            await stop_event.wait()
            ws_task.cancel()
            try:
                await ws_task
            except asyncio.CancelledError:
                pass
    finally:
        stop_event.set()
        poll_task.cancel()
        if sanity_task is not None:
            sanity_task.cancel()
        for t in (poll_task, sanity_task):
            if t is None:
                continue
            try:
                await t
            except asyncio.CancelledError:
                pass
        elapsed = time.monotonic() - start
        print(f"[exit] elapsed={elapsed:.0f}s deltas={delta_chars}c "
              f"tools={dict(tool_counts)} exit_code={exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
