"""Scripted replacement for CLIBackend used by Playwright E2E tests.

Gated by `settings.ACE_USE_FAKE_CLI_BACKEND` (default False). When the
real CLIBackend is replaced, `stream_completion()` yields a deterministic
sequence of StreamEvents based on the input prompt so the Playwright
test can assert on the response body.

The timing is tuned so that:
- a full response finishes in ~1.5-2 seconds (long enough for the stop
  button to be clicked mid-stream, short enough that happy-path tests
  don't time out)
- each delta is small enough that a test can assert on partial text

This file is NEVER imported in production. The guard in
`apps.sessions.turn_driver._get_backend()` ensures the real CLIBackend
is used when ACE_USE_FAKE_CLI_BACKEND is False.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from apps.common.chat_backend import StreamEvent

# Timing tuned for Playwright - slow enough to allow mid-stream stop,
# fast enough not to hold up happy-path tests.
DELTA_DELAY_SECONDS = 0.1
CHUNK_SIZE = 4


class FakeCLIBackend:
    """Scripted backend that echoes the user message as deltas."""

    async def stream_completion(
        self,
        *,
        session,
        new_user_message: str,
        force_fresh_session: bool = False,
        raw_sink: list[str] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        response = f"Echo: {new_user_message}"
        # When the caller wants the raw transcript (web-source cost breakdown),
        # emit the same stream-json envelopes the real CLI would, so the parser
        # + aggregator see a system/init line and an assistant turn with usage.
        if raw_sink is not None:
            import json

            raw_sink.append(json.dumps({
                "type": "system", "subtype": "init",
                "session_id": session.cli_session_id or "fake-session",
            }) + "\n")
            raw_sink.append(json.dumps({
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:00.000Z",
                "message": {
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [{"type": "text", "text": response}],
                    "usage": {"input_tokens": 10, "output_tokens": 5,
                              "cache_creation_input_tokens": 0,
                              "cache_read_input_tokens": 0},
                },
            }) + "\n")
        # Break the response into small chunks so each yield is a
        # deterministic delta that the Playwright assertion can wait on.
        for i in range(0, len(response), CHUNK_SIZE):
            await asyncio.sleep(DELTA_DELAY_SECONDS)
            yield StreamEvent.delta(text=response[i : i + CHUNK_SIZE])
        yield StreamEvent.done()
