"""ChatBackend abstraction and the StreamEvent record types it emits.

This module is the only contract between the chat backends (CLIBackend now,
ApiBackend / McpBackend never in this phase) and the streaming transports
(SSE in Phase 2, Channels WebSocket in Phase 3). The interface is one
async-generator method that yields StreamEvent records, end of story.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from apps.sessions.models import Session


class StreamEventType(StrEnum):
    DELTA = "delta"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    SESSION_ID = "session_id"
    DONE = "done"
    ERROR = "error"


@dataclass(frozen=True)
class StreamEvent:
    """One event from a streaming chat completion.

    Use the classmethod constructors below; they are the only sanctioned way
    to build StreamEvent instances. Direct field assignment is allowed but
    error-prone because every field except `type` is optional.
    """

    type: StreamEventType
    text: str | None = None
    tool_block: dict[str, Any] | None = None
    session_id: str | None = None
    error: str | None = None

    @classmethod
    def delta(cls, *, text: str) -> StreamEvent:
        return cls(type=StreamEventType.DELTA, text=text)

    @classmethod
    def tool_use(cls, *, block: dict[str, Any]) -> StreamEvent:
        return cls(type=StreamEventType.TOOL_USE, tool_block=block)

    @classmethod
    def tool_result(cls, *, block: dict[str, Any]) -> StreamEvent:
        return cls(type=StreamEventType.TOOL_RESULT, tool_block=block)

    @classmethod
    def done(cls) -> StreamEvent:
        return cls(type=StreamEventType.DONE)

    @classmethod
    def for_session_id(cls, *, session_id: str) -> StreamEvent:
        return cls(type=StreamEventType.SESSION_ID, session_id=session_id)

    @classmethod
    def for_error(cls, *, message: str) -> StreamEvent:
        return cls(type=StreamEventType.ERROR, error=message)


@runtime_checkable
class ChatBackend(Protocol):
    """Single method, single contract.

    Implementations stream events for ONE assistant turn given the session
    context and the new user message. They are responsible for keeping the
    underlying conversation state consistent (e.g., capturing the CLI
    session id on a fresh CLI session and yielding it as a SESSION_ID event
    so the caller can persist it on Session.cli_session_id).

    Implementations MUST be cancellable: if the consumer stops iterating
    (typically because the HTTP client disconnected), the implementation
    must release subprocess / network resources promptly.
    """

    async def stream_completion(
        self,
        *,
        session: Session,
        new_user_message: str,
        force_fresh_session: bool = False,
    ) -> AsyncIterator[StreamEvent]: ...
