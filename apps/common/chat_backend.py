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
from typing import Protocol, runtime_checkable

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
    tool_block: dict | None = None
    session_id: str | None = None
    error: str | None = None

    @classmethod
    def delta(cls, *, text: str) -> StreamEvent:
        return cls(type=StreamEventType.DELTA, text=text)

    @classmethod
    def tool_use(cls, *, block: dict) -> StreamEvent:
        return cls(type=StreamEventType.TOOL_USE, tool_block=block)

    @classmethod
    def tool_result(cls, *, block: dict) -> StreamEvent:
        return cls(type=StreamEventType.TOOL_RESULT, tool_block=block)

    @classmethod
    def done(cls) -> StreamEvent:
        return cls(type=StreamEventType.DONE)


def _session_id_constructor(cls: type[StreamEvent], *, session_id: str) -> StreamEvent:
    return cls(type=StreamEventType.SESSION_ID, session_id=session_id)


def _error_constructor(cls: type[StreamEvent], *, message: str) -> StreamEvent:
    return cls(type=StreamEventType.ERROR, error=message)


# `session_id` and `error` are both field names AND desired classmethod names on
# StreamEvent. Defining them as classmethods inside the dataclass body causes Python
# to store the classmethod object as the field's default value, shadowing the field
# on every instance. We define the functions outside and attach them post-class-creation
# so the dataclass decorator processes the fields correctly first.
StreamEvent.session_id = classmethod(_session_id_constructor)  # type: ignore[method-assign]
StreamEvent.error = classmethod(_error_constructor)  # type: ignore[method-assign]


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
    ) -> AsyncIterator[StreamEvent]: ...
