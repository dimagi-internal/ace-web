"""Parse a Claude CLI .jsonl session file into structured turn data."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class ParsedTurn:
    role: str  # "user", "assistant", "tool_use", "tool_result"
    content: dict[str, Any]
    plaintext: str


@dataclass
class ParsedSession:
    cli_session_id: str
    turns: list[ParsedTurn] = field(default_factory=list)
    raw_bytes: int = 0
    line_count: int = 0


@dataclass
class CostEvent:
    """One JSONL line, projected onto cost-relevant fields.

    Emitted in chronological (file) order. The aggregator walks this list
    and never re-reads the source JSONL.
    """
    kind: Literal["assistant_turn", "tool_use", "tool_result"]
    timestamp: datetime | None
    uuid: str | None
    parent_uuid: str | None = None
    is_sidechain: bool = False

    # assistant_turn fields
    model: str | None = None
    usage: dict[str, Any] | None = None

    # tool_use fields
    tool_use_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None

    # tool_result fields
    matched_tool_use_id: str | None = None


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        # Z-suffix common in CLI transcripts; fromisoformat handles it on 3.11+.
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_cost_events(lines: list[str]) -> list[CostEvent]:
    """Project JSONL lines onto cost-relevant fields.

    Pure projection — no segment building, no aggregation. The aggregator
    in cost_aggregator.py consumes this list.
    """
    events: list[CostEvent] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        kind = payload.get("type")
        ts = _parse_ts(payload.get("timestamp"))
        uuid = payload.get("uuid")
        parent_uuid = payload.get("parentUuid")
        is_sidechain = bool(payload.get("isSidechain", False))

        if kind == "assistant":
            message = payload.get("message", {}) or {}
            usage = message.get("usage")
            model = message.get("model")
            blocks = message.get("content", []) or []
            # Defensive: real-world transcripts may have non-list content
            # (string for user-style prompts in subagent transcripts).
            if not isinstance(blocks, list):
                blocks = []
            # One assistant_turn event per assistant message (carries usage),
            # plus one tool_use event per tool_use block (carries the skill name).
            has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in blocks)
            tool_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"]

            if has_text or usage:
                events.append(CostEvent(
                    kind="assistant_turn",
                    timestamp=ts,
                    uuid=uuid,
                    parent_uuid=parent_uuid,
                    is_sidechain=is_sidechain,
                    model=model,
                    usage=usage,
                ))
            for block in tool_blocks:
                events.append(CostEvent(
                    kind="tool_use",
                    timestamp=ts,
                    uuid=uuid,
                    parent_uuid=parent_uuid,
                    is_sidechain=is_sidechain,
                    tool_use_id=block.get("id"),
                    tool_name=block.get("name"),
                    tool_input=block.get("input") or {},
                ))
            continue

        if kind == "user":
            blocks = payload.get("message", {}).get("content", []) or []
            # Real-world transcripts: `content` is sometimes a plain string
            # (the user's prompt) instead of a list of content blocks.
            # Strings carry no tool_result blocks, so skip iteration.
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    events.append(CostEvent(
                        kind="tool_result",
                        timestamp=ts,
                        uuid=uuid,
                        parent_uuid=parent_uuid,
                        is_sidechain=is_sidechain,
                        matched_tool_use_id=block.get("tool_use_id"),
                    ))
            continue

    return events


def parse_session_file(path: Path) -> tuple[ParsedSession, list[CostEvent]]:
    """Parse a .jsonl session file. Returns (ParsedSession, cost events)."""
    raw = path.read_bytes()
    lines = raw.decode("utf-8", errors="replace").splitlines()

    session = ParsedSession(
        cli_session_id="",
        raw_bytes=len(raw),
        line_count=len(lines),
    )

    current_assistant_text: list[str] = []
    current_msg_id: str | None = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping invalid JSON line: %r", line[:200])
            continue

        kind = payload.get("type")

        if kind == "system" and payload.get("subtype") == "init":
            session.cli_session_id = payload.get("session_id", "")
            continue

        if kind == "assistant":
            msg_id = payload.get("message", {}).get("id")
            blocks = payload.get("message", {}).get("content", [])
            if not isinstance(blocks, list):
                blocks = []

            if msg_id != current_msg_id and current_assistant_text:
                session.turns.append(ParsedTurn(
                    role="assistant",
                    content={"text": "".join(current_assistant_text)},
                    plaintext="".join(current_assistant_text),
                ))
                current_assistant_text = []
            current_msg_id = msg_id

            for block in blocks:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type")
                if block_type == "text":
                    current_assistant_text.append(block.get("text", ""))
                elif block_type == "tool_use":
                    if current_assistant_text:
                        session.turns.append(ParsedTurn(
                            role="assistant",
                            content={"text": "".join(current_assistant_text)},
                            plaintext="".join(current_assistant_text),
                        ))
                        current_assistant_text = []
                        current_msg_id = None
                    session.turns.append(ParsedTurn(
                        role="tool_use",
                        content=block,
                        plaintext=f"Tool: {block.get('name', 'unknown')}",
                    ))
            continue

        if kind == "user":
            if current_assistant_text:
                session.turns.append(ParsedTurn(
                    role="assistant",
                    content={"text": "".join(current_assistant_text)},
                    plaintext="".join(current_assistant_text),
                ))
                current_assistant_text = []
                current_msg_id = None

            blocks = payload.get("message", {}).get("content", [])
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_result":
                    session.turns.append(ParsedTurn(
                        role="tool_result",
                        content=block,
                        plaintext=str(block.get("content", ""))[:500],
                    ))
            continue

        if kind == "result":
            if current_assistant_text:
                session.turns.append(ParsedTurn(
                    role="assistant",
                    content={"text": "".join(current_assistant_text)},
                    plaintext="".join(current_assistant_text),
                ))
                current_assistant_text = []
                current_msg_id = None
            continue

    if current_assistant_text:
        session.turns.append(ParsedTurn(
            role="assistant",
            content={"text": "".join(current_assistant_text)},
            plaintext="".join(current_assistant_text),
        ))

    cost_events = _extract_cost_events(lines)
    return session, cost_events
