"""Parse a Claude CLI .jsonl session file into structured turn data."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


def parse_session_file(path: Path) -> ParsedSession:
    """Parse a .jsonl session file and return structured turn data."""
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

            if msg_id != current_msg_id and current_assistant_text:
                session.turns.append(ParsedTurn(
                    role="assistant",
                    content={"text": "".join(current_assistant_text)},
                    plaintext="".join(current_assistant_text),
                ))
                current_assistant_text = []
            current_msg_id = msg_id

            for block in blocks:
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
            for block in blocks:
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

    return session
