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

        event = _convert(payload)
        if event is not None:
            yield event


def _convert(payload: dict[str, Any]) -> StreamEvent | None:
    """Convert a single parsed JSON payload to a StreamEvent, or None to skip."""
    kind = payload.get("type")

    if kind == "system" and payload.get("subtype") == "init":
        session_id = payload.get("session_id")
        if session_id:
            return StreamEvent.for_session_id(session_id=session_id)
        return None

    if kind == "assistant":
        return _convert_assistant(payload)

    if kind == "user":
        # `user` messages in stream-json carry tool_result blocks
        return _convert_tool_result(payload)

    if kind == "result":
        subtype = payload.get("subtype", "")
        if subtype == "success":
            return StreamEvent.done()
        if subtype.startswith("error"):
            return StreamEvent.for_error(message=subtype)
        return StreamEvent.for_error(message=f"unknown result subtype: {subtype}")

    # Unknown event types — log once but don't crash
    logger.debug("Skipping unknown stream-json event type: %r", kind)
    return None


def _convert_assistant(payload: dict[str, Any]) -> StreamEvent | None:
    blocks = payload.get("message", {}).get("content", [])
    if not blocks:
        return None
    block = blocks[0]
    block_type = block.get("type")
    if block_type == "text":
        return StreamEvent.delta(text=block.get("text", ""))
    if block_type == "tool_use":
        return StreamEvent.tool_use(block=block)
    return None


def _convert_tool_result(payload: dict[str, Any]) -> StreamEvent | None:
    blocks = payload.get("message", {}).get("content", [])
    if not blocks:
        return None
    block = blocks[0]
    if block.get("type") == "tool_result":
        return StreamEvent.tool_result(block=block)
    return None
