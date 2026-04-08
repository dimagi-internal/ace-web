"""Pure stream-json parser for `claude -p --output-format stream-json` output.

Takes an iterable of raw JSONL lines (strings) and yields StreamEvent records.
No I/O, no subprocess. Subprocess management lives in cli_backend.py.

Event format reference: see docs/learnings/cli-stream-json-format.md (created
in Task 16) for the canonical event shapes captured from real CLI runs.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from typing import Any

from .chat_backend import StreamEvent

logger = logging.getLogger(__name__)


def parse_stream_json_lines(lines: Iterable[str]) -> Iterator[StreamEvent]:
    """Parse JSONL stream-json output into StreamEvent records.

    Skips blank lines and invalid JSON lines (with a warning log) so a
    single garbled line cannot break a streaming response.
    """
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Invalid JSON line in stream-json output: %r", line[:200])
            continue

        yield from _convert(payload)


def _convert(payload: dict[str, Any]) -> Iterator[StreamEvent]:
    """Convert a single parsed JSON payload to zero or more StreamEvents."""
    kind = payload.get("type")

    if kind == "system" and payload.get("subtype") == "init":
        session_id = payload.get("session_id")
        if session_id:
            yield StreamEvent.for_session_id(session_id=session_id)
        return

    if kind == "assistant":
        yield from _convert_assistant(payload)
        return

    if kind == "user":
        # `user` messages in stream-json carry tool_result blocks
        yield from _convert_tool_result(payload)
        return

    if kind == "result":
        subtype = payload.get("subtype", "")
        if subtype.startswith("error"):
            yield StreamEvent.for_error(message=subtype)
            return
        if subtype != "success":
            logger.warning("Unknown result subtype, treating as success: %r", subtype)
        yield StreamEvent.done()
        return

    # Unknown event types — log once but don't yield
    logger.debug("Skipping unknown stream-json event type: %r", kind)


def _convert_assistant(payload: dict[str, Any]) -> Iterator[StreamEvent]:
    blocks = payload.get("message", {}).get("content", [])
    for block in blocks:
        block_type = block.get("type")
        if block_type == "text":
            yield StreamEvent.delta(text=block.get("text", ""))
        elif block_type == "tool_use":
            yield StreamEvent.tool_use(block=block)
        # Unknown block types are skipped silently


def _convert_tool_result(payload: dict[str, Any]) -> Iterator[StreamEvent]:
    blocks = payload.get("message", {}).get("content", [])
    for block in blocks:
        if block.get("type") == "tool_result":
            yield StreamEvent.tool_result(block=block)
