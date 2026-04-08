# ACE Web Harness — Phase 2: Conversation Engine

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a working single-user chat experience end-to-end. A team member logs in via IAP, lands at `/chat`, gets redirected to a fresh `/chat/<slug>` session, types a message, watches Claude stream a token-by-token response (with tool use rendered as nested blocks), can hit a stop button mid-stream to cleanly cancel, can navigate back to that conversation later via a recent-sessions sidebar, and can edit the auto-generated title inline. CLI authentication is self-service via an in-app `/auth/cli` page that drives `claude setup-token` over a PTY.

**Architecture:** A `ChatBackend` `Protocol` defines a single async-generator method `stream_completion(session, user_message)` that yields `StreamEvent` records. The only implementation in this phase is `CLIBackend`, which wraps `claude -p --output-format stream-json` as a subprocess and parses JSONL events into `StreamEvent`s. Resume strategy is hybrid: try `claude -p --resume <Session.cli_session_id>` first, and on failure (CLI session store missing — instance churn, deploy, container restart) fall back to a fresh CLI session seeded with the full conversation history from Django, then capture and persist the new session id. Streaming is delivered to the browser via SSE (`StreamingHttpResponse` with `text/event-stream`) — Phase 3 will swap the SSE wrapper for a Channels WebSocket consumer without changing the `ChatBackend` interface or the CLIBackend implementation.

**Tech Stack:** Python 3.11+, Django 5.x, Django REST Framework, asyncio, subprocess, `pty`, React 19 + Vite + TypeScript + Tailwind, native browser `EventSource`. No new Python dependencies — all stdlib. No new frontend dependencies. Filestore (NFS) on Cloud Run for persistent `~/.claude` storage; named Docker volume in local dev.

**Reference for canopy-web patterns to port:**
- `../canopy-web/apps/common/anthropic_client.py` (154 lines) — the CLI subprocess wrapper, circuit breaker pattern
- `../canopy-web/apps/common/auth_flow.py` (248 lines) — the full PTY-based `claude setup-token` driver

**Spec reference:** `docs/specs/2026-04-08-ace-web-design.md` — read sections 4.1, 4.2, 5.2, 5.3, and 5.4 before starting.

**Plan 1 corrections to keep in mind** (from `docs/plans/2026-04-07-1a-foundation.md` `## Post-execution corrections`):
- All API responses use `apps.common.envelope.success_response` / `error_response` (`{data, error}`).
- `Message.started_at` is `null=True`, set explicitly by the consumer when streaming begins. Do not use `auto_now_add`.
- `Session.save()` retries on slug collision via savepoint — use `Session.objects.create()` normally and trust the model.
- `IAPHeaderAuthMiddleware` only runs on HTTP — that's fine for Phase 2 (SSE is HTTP). Phase 3 adds the ASGI version.
- The `unique_session_turn` constraint means tool_use/tool_result rows get their own monotonically-increasing `turn_index` values (not shared with the parent assistant turn).

---

## File structure (created across all tasks)

```
ace-web/
├── apps/
│   ├── common/
│   │   ├── chat_backend.py            # ChatBackend Protocol + StreamEvent dataclass
│   │   ├── cli_event_parser.py        # Pure stream-json parser (no I/O)
│   │   ├── cli_backend.py             # CLIBackend implementation (subprocess + hybrid resume)
│   │   ├── circuit_breaker.py         # Reusable circuit breaker
│   │   ├── auth_flow.py               # PTY-based claude setup-token driver
│   │   ├── auth_views.py              # /api/auth/cli/* REST endpoints
│   │   ├── token_loader.py            # Load OAuth token at app boot
│   │   ├── apps.py                    # MODIFIED: AppConfig.ready() calls token_loader
│   │   ├── urls.py                    # MODIFIED: include auth_views routes
│   │   └── tests/
│   │       ├── test_chat_backend.py
│   │       ├── test_cli_event_parser.py
│   │       ├── test_cli_backend.py
│   │       ├── test_circuit_breaker.py
│   │       ├── test_auth_flow.py
│   │       ├── test_auth_views.py
│   │       └── fixtures/
│   │           ├── stream_json_simple.txt        # captured stream-json output: simple text response
│   │           ├── stream_json_tool_use.txt      # captured: text + tool_use + tool_result + text
│   │           ├── stream_json_error.txt         # captured: model error mid-stream
│   │           └── stream_json_session_init.txt  # captured: first event with session_id
│   │
│   ├── sessions/
│   │   ├── views.py                   # Session/Message REST endpoints
│   │   ├── serializers.py             # DRF serializers
│   │   ├── streaming.py               # SSE stream view + reconnect logic
│   │   ├── urls.py                    # /api/sessions/* and /api/messages/* routes
│   │   ├── auto_title.py              # Background-task title generation
│   │   └── tests/
│   │       ├── test_views.py
│   │       ├── test_streaming.py
│   │       ├── test_auto_title.py
│   │       └── test_serializers.py
│   │
│   └── auth/
│       └── (no changes — Phase 1 already shipped)
│
├── config/
│   ├── settings/
│   │   └── base.py                    # MODIFIED: add ACE_CLAUDE_TOKEN_FILE, ACE_CLAUDE_HOME, etc
│   └── urls.py                        # MODIFIED: include apps.sessions.urls
│
├── frontend/
│   └── src/
│       ├── api/
│       │   ├── types.ts               # Session, Message, StreamEvent shared types
│       │   ├── client.ts              # MODIFIED: extend with sessions/messages/auth helpers
│       │   ├── sessions.ts            # Session CRUD
│       │   ├── messages.ts            # Message send + SSE consumer
│       │   └── auth.ts                # CLI auth flow client
│       │
│       ├── hooks/
│       │   ├── useStreamingMessage.ts # SSE consumer hook for assistant messages
│       │   ├── useRecentSessions.ts   # Fetches sidebar data
│       │   └── useCliAuthStatus.ts    # Polls /api/auth/cli/status
│       │
│       ├── components/
│       │   ├── MessageList.tsx        # Renders Message[] with streaming awareness
│       │   ├── MessageItem.tsx        # Single message: text, tool_use (collapsed), tool_result
│       │   ├── SendBox.tsx            # Text input + send/stop button
│       │   ├── RecentSessionsSidebar.tsx
│       │   ├── InlineTitleEdit.tsx
│       │   └── CliAuthBanner.tsx
│       │
│       ├── pages/
│       │   ├── ChatRedirectPage.tsx   # /chat — creates session, redirects
│       │   ├── ChatPage.tsx           # /chat/<slug> — main chat view
│       │   └── AuthCliPage.tsx        # /auth/cli — PTY auth flow UI
│       │
│       └── router.tsx                 # MODIFIED: add /chat, /chat/:slug, /auth/cli
│
├── docker-compose.yml                 # MODIFIED: add ace-claude-data volume
├── cloudbuild.yaml                    # MODIFIED: Filestore mount
├── entrypoint.sh                      # MODIFIED: symlink ~/.claude to mounted volume
├── docs/
│   ├── deploy.md                      # MODIFIED: Filestore provisioning section
│   └── learnings/
│       ├── sse-django-async.md        # NEW
│       └── cli-stream-json-format.md  # NEW
└── CLAUDE.md                          # MODIFIED: phase status update at the end
```

---

## Task 1: ChatBackend interface and StreamEvent types

**Files:**
- Create: `apps/common/chat_backend.py`
- Create: `apps/common/tests/test_chat_backend.py`

This task defines the abstraction surface that the rest of Phase 2 builds against. No real CLI work yet — just the types.

- [ ] **Step 1: Write the type tests**

Create `apps/common/tests/test_chat_backend.py`:

```python
"""Tests for the ChatBackend Protocol and StreamEvent record types."""
from typing import get_type_hints

import pytest

from apps.common.chat_backend import ChatBackend, StreamEvent, StreamEventType


def test_stream_event_type_enum_values():
    assert StreamEventType.DELTA.value == "delta"
    assert StreamEventType.TOOL_USE.value == "tool_use"
    assert StreamEventType.TOOL_RESULT.value == "tool_result"
    assert StreamEventType.SESSION_ID.value == "session_id"
    assert StreamEventType.DONE.value == "done"
    assert StreamEventType.ERROR.value == "error"


def test_delta_event_construction():
    e = StreamEvent.delta(text="hello")
    assert e.type is StreamEventType.DELTA
    assert e.text == "hello"
    assert e.tool_block is None
    assert e.session_id is None
    assert e.error is None


def test_tool_use_event_construction():
    block = {"id": "toolu_01", "name": "Read", "input": {"file_path": "/x"}}
    e = StreamEvent.tool_use(block=block)
    assert e.type is StreamEventType.TOOL_USE
    assert e.tool_block == block
    assert e.text is None


def test_tool_result_event_construction():
    block = {"tool_use_id": "toolu_01", "content": "file contents"}
    e = StreamEvent.tool_result(block=block)
    assert e.type is StreamEventType.TOOL_RESULT
    assert e.tool_block == block


def test_session_id_event_construction():
    e = StreamEvent.session_id(session_id="sess_abc123")
    assert e.type is StreamEventType.SESSION_ID
    assert e.session_id == "sess_abc123"


def test_done_event_construction():
    e = StreamEvent.done()
    assert e.type is StreamEventType.DONE


def test_error_event_construction():
    e = StreamEvent.error(message="model failed")
    assert e.type is StreamEventType.ERROR
    assert e.error == "model failed"


def test_chat_backend_is_protocol():
    """ChatBackend is a runtime-checkable Protocol with one method."""
    assert hasattr(ChatBackend, "stream_completion")
    # Protocols cannot be instantiated directly
    with pytest.raises(TypeError):
        ChatBackend()
```

- [ ] **Step 2: Run the test, expect import failure**

Run: `pytest apps/common/tests/test_chat_backend.py -v`
Expected: ImportError on `apps.common.chat_backend`.

- [ ] **Step 3: Implement chat_backend.py**

Create `apps/common/chat_backend.py`:

```python
"""ChatBackend abstraction and the StreamEvent record types it emits.

This module is the only contract between the chat backends (CLIBackend now,
ApiBackend / McpBackend never in this phase) and the streaming transports
(SSE in Phase 2, Channels WebSocket in Phase 3). The interface is one
async-generator method that yields StreamEvent records, end of story.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Protocol, runtime_checkable

from apps.sessions.models import Session


class StreamEventType(str, Enum):
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
    def delta(cls, *, text: str) -> "StreamEvent":
        return cls(type=StreamEventType.DELTA, text=text)

    @classmethod
    def tool_use(cls, *, block: dict) -> "StreamEvent":
        return cls(type=StreamEventType.TOOL_USE, tool_block=block)

    @classmethod
    def tool_result(cls, *, block: dict) -> "StreamEvent":
        return cls(type=StreamEventType.TOOL_RESULT, tool_block=block)

    @classmethod
    def session_id(cls, *, session_id: str) -> "StreamEvent":
        return cls(type=StreamEventType.SESSION_ID, session_id=session_id)

    @classmethod
    def done(cls) -> "StreamEvent":
        return cls(type=StreamEventType.DONE)

    @classmethod
    def error(cls, *, message: str) -> "StreamEvent":
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
    ) -> AsyncIterator[StreamEvent]: ...
```

- [ ] **Step 4: Run the test, expect pass**

Run: `pytest apps/common/tests/test_chat_backend.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/common/chat_backend.py apps/common/tests/test_chat_backend.py
git commit -m "feat(common): add ChatBackend Protocol and StreamEvent types"
```

---

## Task 2: stream-json parser

**Files:**
- Create: `apps/common/cli_event_parser.py`
- Create: `apps/common/tests/test_cli_event_parser.py`
- Create: `apps/common/tests/fixtures/stream_json_simple.txt`
- Create: `apps/common/tests/fixtures/stream_json_tool_use.txt`
- Create: `apps/common/tests/fixtures/stream_json_session_init.txt`
- Create: `apps/common/tests/fixtures/stream_json_error.txt`

**Critical context:** `claude -p --output-format stream-json` emits JSON Lines. Each line is a JSON object describing one event. The parser is a pure function — no I/O, no subprocess. We test it against captured fixtures of real CLI output. The fixtures in this task are **shaped** (not necessarily byte-perfect captures from a real run) so the parser logic is testable. Task 4 will replace them with real captures and may surface format adjustments.

The relevant event types we care about (based on the canopy-web reference implementation and the Claude Code CLI documentation):
- `{"type": "system", "subtype": "init", "session_id": "..."}` — first event of a fresh session, contains the new CLI session id
- `{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}` — assistant text delta (each chunk is one event)
- `{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "...", "name": "...", "input": {...}}]}}` — tool use block
- `{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}}` — tool result block
- `{"type": "result", "subtype": "success"}` — terminal "done" event
- `{"type": "result", "subtype": "error_max_turns" | ...}` — terminal error

**Important:** the format above is the canonical Claude Code stream-json shape as captured from real CLI runs. If the real format differs when Task 4 captures actual output, the parser will be adjusted then.

- [ ] **Step 1: Write the fixture files**

Create `apps/common/tests/fixtures/stream_json_session_init.txt`:

```
{"type":"system","subtype":"init","session_id":"sess_abc123","cwd":"/tmp","tools":["Read","Edit","Bash"]}
{"type":"assistant","message":{"id":"msg_01","content":[{"type":"text","text":"Hello"}]}}
{"type":"assistant","message":{"id":"msg_01","content":[{"type":"text","text":" there"}]}}
{"type":"result","subtype":"success","duration_ms":1234,"num_turns":1}
```

Create `apps/common/tests/fixtures/stream_json_simple.txt`:

```
{"type":"assistant","message":{"id":"msg_02","content":[{"type":"text","text":"The answer "}]}}
{"type":"assistant","message":{"id":"msg_02","content":[{"type":"text","text":"is 42."}]}}
{"type":"result","subtype":"success","duration_ms":500,"num_turns":1}
```

Create `apps/common/tests/fixtures/stream_json_tool_use.txt`:

```
{"type":"assistant","message":{"id":"msg_03","content":[{"type":"text","text":"Let me read that file."}]}}
{"type":"assistant","message":{"id":"msg_03","content":[{"type":"tool_use","id":"toolu_01","name":"Read","input":{"file_path":"/etc/hosts"}}]}}
{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"toolu_01","content":"127.0.0.1 localhost"}]}}
{"type":"assistant","message":{"id":"msg_03","content":[{"type":"text","text":"It contains a localhost entry."}]}}
{"type":"result","subtype":"success","duration_ms":2000,"num_turns":1}
```

Create `apps/common/tests/fixtures/stream_json_error.txt`:

```
{"type":"assistant","message":{"id":"msg_04","content":[{"type":"text","text":"Working on it"}]}}
{"type":"result","subtype":"error_max_turns","duration_ms":300}
```

- [ ] **Step 2: Write the parser tests**

Create `apps/common/tests/test_cli_event_parser.py`:

```python
"""Tests for the stream-json parser. Reads captured fixtures and asserts on
the StreamEvent sequence the parser produces."""
from pathlib import Path

import pytest

from apps.common.chat_backend import StreamEventType
from apps.common.cli_event_parser import parse_stream_json_lines

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> list[str]:
    return [line for line in (FIXTURES / name).read_text().splitlines() if line]


def test_session_init_emits_session_id_first():
    events = list(parse_stream_json_lines(_load("stream_json_session_init.txt")))
    assert events[0].type is StreamEventType.SESSION_ID
    assert events[0].session_id == "sess_abc123"


def test_simple_text_emits_deltas_then_done():
    events = list(parse_stream_json_lines(_load("stream_json_simple.txt")))
    assert [e.type for e in events] == [
        StreamEventType.DELTA,
        StreamEventType.DELTA,
        StreamEventType.DONE,
    ]
    assert events[0].text == "The answer "
    assert events[1].text == "is 42."


def test_tool_use_sequence():
    events = list(parse_stream_json_lines(_load("stream_json_tool_use.txt")))
    types = [e.type for e in events]
    assert types == [
        StreamEventType.DELTA,        # "Let me read that file."
        StreamEventType.TOOL_USE,     # the Read call
        StreamEventType.TOOL_RESULT,  # the Read result
        StreamEventType.DELTA,        # "It contains a localhost entry."
        StreamEventType.DONE,
    ]
    assert events[1].tool_block["name"] == "Read"
    assert events[1].tool_block["input"] == {"file_path": "/etc/hosts"}
    assert events[2].tool_block["tool_use_id"] == "toolu_01"


def test_error_terminal_emits_error_event():
    events = list(parse_stream_json_lines(_load("stream_json_error.txt")))
    assert events[-1].type is StreamEventType.ERROR
    assert "max_turns" in events[-1].error


def test_blank_lines_are_ignored():
    lines = ["", "{\"type\":\"result\",\"subtype\":\"success\"}", ""]
    events = list(parse_stream_json_lines(lines))
    assert len(events) == 1
    assert events[0].type is StreamEventType.DONE


def test_invalid_json_line_is_skipped_with_log(caplog):
    lines = ["not json at all", "{\"type\":\"result\",\"subtype\":\"success\"}"]
    events = list(parse_stream_json_lines(lines))
    assert len(events) == 1
    assert events[0].type is StreamEventType.DONE
    assert any("invalid json" in r.message.lower() for r in caplog.records)


def test_unknown_event_type_is_skipped():
    lines = [
        '{"type":"weather_report","data":"sunny"}',
        '{"type":"result","subtype":"success"}',
    ]
    events = list(parse_stream_json_lines(lines))
    assert len(events) == 1
    assert events[0].type is StreamEventType.DONE
```

- [ ] **Step 3: Run the tests, expect import failure**

Run: `pytest apps/common/tests/test_cli_event_parser.py -v`
Expected: ImportError on `apps.common.cli_event_parser`.

- [ ] **Step 4: Implement the parser**

Create `apps/common/cli_event_parser.py`:

```python
"""Pure stream-json parser for `claude -p --output-format stream-json` output.

Takes an iterable of raw JSONL lines (strings) and yields StreamEvent records.
No I/O, no subprocess. Subprocess management lives in cli_backend.py.

Event format reference: see docs/learnings/cli-stream-json-format.md (created
in Task 16) for the canonical event shapes captured from real CLI runs.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable, Iterator

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


def _convert(payload: dict) -> StreamEvent | None:
    """Convert a single parsed JSON payload to a StreamEvent, or None to skip."""
    kind = payload.get("type")

    if kind == "system" and payload.get("subtype") == "init":
        session_id = payload.get("session_id")
        if session_id:
            return StreamEvent.session_id(session_id=session_id)
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
            return StreamEvent.error(message=subtype)
        return StreamEvent.error(message=f"unknown result subtype: {subtype}")

    # Unknown event types — log once but don't crash
    logger.debug("Skipping unknown stream-json event type: %r", kind)
    return None


def _convert_assistant(payload: dict) -> StreamEvent | None:
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


def _convert_tool_result(payload: dict) -> StreamEvent | None:
    blocks = payload.get("message", {}).get("content", [])
    if not blocks:
        return None
    block = blocks[0]
    if block.get("type") == "tool_result":
        return StreamEvent.tool_result(block=block)
    return None
```

- [ ] **Step 5: Run the tests, expect pass**

Run: `pytest apps/common/tests/test_cli_event_parser.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add apps/common/cli_event_parser.py apps/common/tests/test_cli_event_parser.py apps/common/tests/fixtures/
git commit -m "feat(common): add stream-json parser with fixture-based tests"
```

---

## Task 3: Circuit breaker utility

**Files:**
- Create: `apps/common/circuit_breaker.py`
- Create: `apps/common/tests/test_circuit_breaker.py`

A simple per-process circuit breaker. Tracks consecutive failures; opens after a threshold; closes after a cooldown window. Used by CLIBackend in Task 4. Pattern ported from `canopy-web/apps/common/anthropic_client.py` but extracted into a reusable class so it's testable in isolation.

- [ ] **Step 1: Write the tests**

Create `apps/common/tests/test_circuit_breaker.py`:

```python
"""Tests for the CircuitBreaker utility."""
import time

from apps.common.circuit_breaker import CircuitBreaker, CircuitOpenError


def test_starts_closed():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=1)
    assert not cb.is_open()


def test_opens_after_threshold_failures():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=10)
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()
    cb.record_failure()
    assert cb.is_open()


def test_success_resets_failures():
    cb = CircuitBreaker(threshold=3, cooldown_seconds=10)
    cb.record_failure()
    cb.record_failure()
    cb.record_success()
    cb.record_failure()
    cb.record_failure()
    assert not cb.is_open()


def test_check_raises_when_open():
    import pytest
    cb = CircuitBreaker(threshold=1, cooldown_seconds=10)
    cb.record_failure()
    with pytest.raises(CircuitOpenError):
        cb.check()


def test_half_opens_after_cooldown():
    cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
    cb.record_failure()
    assert cb.is_open()
    time.sleep(0.15)
    # Cooldown elapsed — circuit allows next call
    assert not cb.is_open()
    cb.check()  # does not raise


def test_reopens_immediately_on_first_failure_after_cooldown():
    cb = CircuitBreaker(threshold=1, cooldown_seconds=0.1)
    cb.record_failure()
    time.sleep(0.15)
    cb.record_failure()
    assert cb.is_open()
```

- [ ] **Step 2: Run, expect import failure**

Run: `pytest apps/common/tests/test_circuit_breaker.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the circuit breaker**

Create `apps/common/circuit_breaker.py`:

```python
"""Per-process circuit breaker for failing-fast on repeated downstream errors.

Used by CLIBackend to avoid hammering a broken `claude` subprocess (auth
expired, binary missing, network down, etc.) on every chat turn.
"""
from __future__ import annotations

import time
import threading


class CircuitOpenError(RuntimeError):
    """Raised by check() when the breaker is open."""


class CircuitBreaker:
    """Simple thread-safe circuit breaker.

    States:
      closed   — normal operation, calls pass through
      open     — failures exceeded threshold; calls are rejected fast
      half-open (implicit) — after cooldown elapses, the breaker
                             auto-transitions back to closed on the next
                             check, giving the next call a chance.
    """

    def __init__(self, *, threshold: int, cooldown_seconds: float):
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if time.monotonic() - self._opened_at >= self._cooldown:
                # Cooldown elapsed — half-open: allow the next call through
                self._opened_at = None
                self._consecutive_failures = 0
                return False
            return True

    def check(self) -> None:
        if self.is_open():
            raise CircuitOpenError("Circuit breaker is open")

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold:
                self._opened_at = time.monotonic()
```

- [ ] **Step 4: Run, expect pass**

Run: `pytest apps/common/tests/test_circuit_breaker.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add apps/common/circuit_breaker.py apps/common/tests/test_circuit_breaker.py
git commit -m "feat(common): add reusable CircuitBreaker utility"
```

---

## Task 4: CLIBackend with hybrid resume and cancellation

**Files:**
- Create: `apps/common/cli_backend.py`
- Create: `apps/common/tests/test_cli_backend.py`

The first real backend. Spawns `claude -p --output-format stream-json` as an `asyncio.subprocess`, parses its stdout line-by-line via the parser from Task 2, yields StreamEvents to the consumer. Hybrid resume strategy: try `--resume <session.cli_session_id>` first; on subprocess failure (non-zero exit, no events emitted) restart with the full conversation history seeded as the prompt and capture the new session id. Detects cancellation via the async-iterator being abandoned and sends SIGTERM → SIGKILL to the subprocess.

- [ ] **Step 1: Write the test scaffolding**

Create `apps/common/tests/test_cli_backend.py`:

```python
"""Tests for CLIBackend. Subprocess is mocked at the asyncio.create_subprocess_exec
level so the tests do not actually invoke the claude CLI binary."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from apps.common.chat_backend import StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError
from apps.sessions.models import Session

FIXTURES = Path(__file__).parent / "fixtures"

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="test@example.com", display_name="test"
    )
    return Session.objects.create(owner=user, title="test")


def _fake_proc(stdout_bytes: bytes, returncode: int = 0):
    """Build a mock that quacks like asyncio.subprocess.Process."""
    proc = AsyncMock()
    proc.stdout = AsyncMock()
    # Simulate readline() draining the buffer line by line
    lines = [b for b in stdout_bytes.splitlines(keepends=True)] + [b""]
    iterator = iter(lines)
    proc.stdout.readline = AsyncMock(side_effect=lambda: next(iterator))
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode)
    proc.terminate = lambda: None
    proc.kill = lambda: None
    proc.pid = 12345
    return proc


async def test_fresh_session_captures_session_id(session):
    fixture = (FIXTURES / "stream_json_session_init.txt").read_bytes()
    backend = CLIBackend()

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=_fake_proc(fixture))):
        events = []
        async for e in backend.stream_completion(session=session, new_user_message="hi"):
            events.append(e)

    types = [e.type for e in events]
    assert StreamEventType.SESSION_ID in types
    assert StreamEventType.DONE in types

    # The Session row should have the captured cli_session_id persisted
    session.refresh_from_db()
    assert session.cli_session_id == "sess_abc123"


async def test_resume_uses_existing_cli_session_id(session):
    session.cli_session_id = "sess_existing"
    session.save()
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    backend = CLIBackend()

    create = AsyncMock(return_value=_fake_proc(fixture))
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="hi"):
            pass

    args = create.call_args[0]
    assert "--resume" in args
    assert "sess_existing" in args


async def test_resume_failure_falls_back_to_full_history(session, django_user_model):
    """If --resume returns non-zero with no events, restart fresh and seed history."""
    from apps.sessions.models import Message

    session.cli_session_id = "sess_dead"
    session.save()
    Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "first turn from yesterday"},
        plaintext="first turn from yesterday", status="complete",
    )

    failing = _fake_proc(b"", returncode=1)
    succeeding = _fake_proc((FIXTURES / "stream_json_session_init.txt").read_bytes())

    backend = CLIBackend()
    create = AsyncMock(side_effect=[failing, succeeding])
    with patch("asyncio.create_subprocess_exec", new=create):
        async for _ in backend.stream_completion(session=session, new_user_message="next turn"):
            pass

    assert create.call_count == 2
    second_call_args = create.call_args_list[1][0]
    # Second call must NOT have --resume
    assert "--resume" not in second_call_args
    # And the session id should be replaced with the freshly captured one
    session.refresh_from_db()
    assert session.cli_session_id == "sess_abc123"


async def test_cancellation_terminates_subprocess(session):
    fixture = (FIXTURES / "stream_json_simple.txt").read_bytes()
    fake = _fake_proc(fixture)
    terminated = []
    fake.terminate = lambda: terminated.append("term")

    backend = CLIBackend()
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=fake)):
        async for e in backend.stream_completion(session=session, new_user_message="hi"):
            break  # cancel after first event

    assert terminated == ["term"]


async def test_circuit_breaker_opens_after_repeated_failures(session):
    backend = CLIBackend(circuit_threshold=2, circuit_cooldown=10)
    failing = _fake_proc(b"", returncode=1)

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=failing)):
        with pytest.raises(CLIBackendError):
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
        with pytest.raises(CLIBackendError):
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
        # Third call should fail-fast on circuit breaker, not invoke subprocess
        with pytest.raises(CLIBackendError) as exc_info:
            async for _ in backend.stream_completion(session=session, new_user_message="x"):
                pass
    assert "circuit" in str(exc_info.value).lower()
```

- [ ] **Step 2: Run, expect import failure**

Run: `pytest apps/common/tests/test_cli_backend.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement CLIBackend**

Create `apps/common/cli_backend.py`:

```python
"""CLIBackend — wraps `claude -p --output-format stream-json` as a subprocess.

Hybrid resume strategy:
  1. If session.cli_session_id is set, try `--resume <id>` with only the new
     user message as the prompt.
  2. If that subprocess exits non-zero with no SESSION_ID or DELTA events
     (signal that the CLI's on-disk session store is gone — instance churn,
     deploy, container restart), restart without --resume and seed the prompt
     with the full conversation history from Django.
  3. Capture the fresh session_id from the first SESSION_ID event of the new
     CLI session and persist it on session.cli_session_id.

The single subprocess is killed on consumer cancellation (the async iterator
is abandoned), via SIGTERM then SIGKILL after a 2-second grace.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import AsyncIterator

from asgiref.sync import sync_to_async
from django.conf import settings

from apps.sessions.models import Message, Session

from .chat_backend import StreamEvent, StreamEventType
from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .cli_event_parser import parse_stream_json_lines

logger = logging.getLogger(__name__)


class CLIBackendError(RuntimeError):
    """Raised when the CLI subprocess fails in a way the consumer should know about."""


class CLIBackend:
    """Async chat backend that wraps the Claude CLI."""

    def __init__(
        self,
        *,
        binary: str = "claude",
        circuit_threshold: int = 5,
        circuit_cooldown: float = 30.0,
        terminate_grace_seconds: float = 2.0,
    ):
        self._binary = binary
        self._breaker = CircuitBreaker(
            threshold=circuit_threshold, cooldown_seconds=circuit_cooldown
        )
        self._terminate_grace = terminate_grace_seconds

    async def stream_completion(
        self,
        *,
        session: Session,
        new_user_message: str,
    ) -> AsyncIterator[StreamEvent]:
        try:
            self._breaker.check()
        except CircuitOpenError as exc:
            raise CLIBackendError(str(exc)) from exc

        # First attempt: resume if we have a CLI session id
        if session.cli_session_id:
            had_events = False
            proc = await self._spawn(
                args=["--resume", session.cli_session_id],
                prompt=new_user_message,
            )
            try:
                async for event in self._drain(proc):
                    had_events = True
                    yield event
                    if event.type is StreamEventType.SESSION_ID:
                        await self._persist_session_id(session, event.session_id)
            finally:
                await self._cleanup(proc)

            if had_events and proc.returncode == 0:
                self._breaker.record_success()
                return

            logger.warning(
                "CLI --resume %s failed (rc=%s, events=%s) — falling back to seeded history",
                session.cli_session_id, proc.returncode, had_events,
            )
            # fallthrough to seeded-history path

        # Fallback / fresh-session path: seed the full history into the prompt
        history_prompt = await self._build_seeded_prompt(session, new_user_message)
        proc = await self._spawn(args=[], prompt=history_prompt)
        try:
            had_events = False
            async for event in self._drain(proc):
                had_events = True
                yield event
                if event.type is StreamEventType.SESSION_ID:
                    await self._persist_session_id(session, event.session_id)
            await proc.wait()
        finally:
            await self._cleanup(proc)

        if proc.returncode != 0 or not had_events:
            self._breaker.record_failure()
            raise CLIBackendError(
                f"claude CLI failed (rc={proc.returncode}, events={had_events})"
            )
        self._breaker.record_success()

    # ────────────────────────────── helpers ──────────────────────────────

    async def _spawn(self, *, args: list[str], prompt: str):
        """Spawn the CLI subprocess, write the prompt to stdin, and close it.

        The CLI does not start emitting output until stdin is closed, so the
        prompt must be written and the pipe closed before the caller starts
        draining stdout.
        """
        full_args = [
            self._binary, "-p", "--output-format", "stream-json", *args,
        ]
        env = self._build_env()
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        return proc

    def _build_env(self) -> dict[str, str]:
        # Strip ANTHROPIC_API_KEY so the CLI uses subscription auth via the
        # OAuth token loaded into CLAUDE_CODE_OAUTH_TOKEN by token_loader.
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        # Point HOME at the configured CLAUDE home so ~/.claude lives on the
        # mounted volume in production.
        claude_home = getattr(settings, "ACE_CLAUDE_HOME", None)
        if claude_home:
            env["HOME"] = claude_home
        return env

    async def _drain(self, proc) -> AsyncIterator[StreamEvent]:
        """Read stdout line by line and yield parsed StreamEvents.

        Tolerates the consumer abandoning the iterator (cancellation) by
        relying on the caller's `finally: cleanup` to terminate the process.
        """
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
            for event in parse_stream_json_lines([text]):
                yield event

    async def _build_seeded_prompt(self, session: Session, new_user_message: str) -> str:
        @sync_to_async
        def _load_history():
            return list(
                Message.objects.filter(session=session).order_by("turn_index").values(
                    "role", "plaintext"
                )
            )

        history = await _load_history()
        lines = []
        for row in history:
            role = row["role"].capitalize()
            lines.append(f"{role}: {row['plaintext']}")
        lines.append(f"User: {new_user_message}")
        return "\n\n".join(lines)

    async def _persist_session_id(self, session: Session, cli_session_id: str) -> None:
        @sync_to_async
        def _save():
            Session.objects.filter(pk=session.pk).update(cli_session_id=cli_session_id)
            session.cli_session_id = cli_session_id
        await _save()

    async def _cleanup(self, proc) -> None:
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=self._terminate_grace)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `pytest apps/common/tests/test_cli_backend.py -v`
Expected: 5 passed.

If any test fails because the mock's `readline` exhaustion behavior differs from the real `asyncio.StreamReader`, adjust the mock to return `b""` after exhausting the fixture lines (the helper already does this).

- [ ] **Step 5: Commit**

```bash
git add apps/common/cli_backend.py apps/common/tests/test_cli_backend.py
git commit -m "feat(common): add CLIBackend with hybrid resume and cancellation"
```

---

## Task 5: PTY auth flow port from canopy-web

**Files:**
- Create: `apps/common/auth_flow.py`
- Create: `apps/common/tests/test_auth_flow.py`

Direct port of `canopy-web/apps/common/auth_flow.py` (248 lines) into ace-web. The PTY-based driver for `claude setup-token` is the established shape — do not deviate from canopy-web's approach unless the test fails. ANSI parsing, threading, subprocess lifecycle, token persistence are all included.

**Important:** the canopy-web file uses `TOKEN_FILE = os.environ.get("CLAUDE_TOKEN_FILE", "/root/claude-data/oauth-token")`. ace-web uses a different env var name and default — `ACE_CLAUDE_TOKEN_FILE`, defaulting to `/var/lib/ace-claude/oauth-token`.

- [ ] **Step 1: Read the canopy-web reference**

Open `../canopy-web/apps/common/auth_flow.py` (248 lines). Skim it to internalize the structure: `_AuthSession` class, public `start/complete/poll/cancel` API, ANSI/URL/token regex helpers, token persistence functions.

- [ ] **Step 2: Write the test file**

Create `apps/common/tests/test_auth_flow.py`:

```python
"""Tests for the PTY auth flow driver. The PTY itself is mocked — these tests
exercise the public API and the regex helpers, not the actual claude binary.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.common import auth_flow


def test_extract_url_strips_ansi_and_finds_oauth_url():
    raw = "\x1b[2mPaste code\x1b[0m: https://claude.com/cai/oauth/authorize?client_id=abc&state=xyzPasteCode"
    url = auth_flow._extract_url(raw)
    assert url == "https://claude.com/cai/oauth/authorize?client_id=abc&state=xyz"


def test_extract_token_finds_sk_ant_oat_token():
    raw = "Token created: sk-ant-oat01-AbCdEfGhIjKlMnOp123456 (saved)"
    token = auth_flow._extract_token(raw)
    assert token == "sk-ant-oat01-AbCdEfGhIjKlMnOp123456"


def test_extract_returns_none_when_absent():
    assert auth_flow._extract_url("nothing here") is None
    assert auth_flow._extract_token("nothing here") is None


def test_store_and_load_token(tmp_path, monkeypatch):
    token_file = tmp_path / "oauth-token"
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(token_file))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    auth_flow.store_token("sk-ant-oat01-test")
    assert token_file.read_text() == "sk-ant-oat01-test"
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test"
    assert oct(token_file.stat().st_mode)[-3:] == "600"

    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    loaded = auth_flow.load_stored_token()
    assert loaded == "sk-ant-oat01-test"
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-test"


def test_get_stored_token_prefers_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-fromenv")
    assert auth_flow.get_stored_token() == "sk-ant-oat01-fromenv"


def test_poll_when_no_session_active():
    auth_flow.cancel()  # ensure no session
    result = auth_flow.poll()
    assert result["active"] is False


def test_start_then_cancel_cleans_up():
    """Smoke test the lifecycle without actually invoking claude."""
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.poll.return_value = None
        with patch("pty.openpty", return_value=(0, 1)), \
             patch("os.close"), \
             patch("os.read", return_value=b""), \
             patch("threading.Thread"):
            try:
                # start() will time out (no URL appears) — that's fine,
                # we just want cancel() to clean up cleanly
                with pytest.raises(RuntimeError):
                    auth_flow.start()
            finally:
                auth_flow.cancel()
```

- [ ] **Step 3: Run, expect import failure**

Run: `pytest apps/common/tests/test_auth_flow.py -v`
Expected: ImportError.

- [ ] **Step 4: Port auth_flow.py from canopy-web**

Copy the file:

```bash
cp ../canopy-web/apps/common/auth_flow.py apps/common/auth_flow.py
```

Then edit `apps/common/auth_flow.py` to swap the env var name and default path. Find this line near the top:

```python
TOKEN_FILE = os.environ.get(
    "CLAUDE_TOKEN_FILE", "/root/claude-data/oauth-token"
)
```

Replace with:

```python
TOKEN_FILE = os.environ.get(
    "ACE_CLAUDE_TOKEN_FILE", "/var/lib/ace-claude/oauth-token"
)
```

Leave everything else byte-identical to canopy-web. The proven shape is the proven shape — deviating risks regressing the ANSI parsing edge cases.

- [ ] **Step 5: Run the tests, expect pass**

Run: `pytest apps/common/tests/test_auth_flow.py -v`
Expected: 7 passed.

If `test_start_then_cancel_cleans_up` hangs, the mock for `os.read` may need to return `b""` after one call (rather than always `b""`) — adjust the mock to use `side_effect=[b""]`.

- [ ] **Step 6: Commit**

```bash
git add apps/common/auth_flow.py apps/common/tests/test_auth_flow.py
git commit -m "feat(common): port PTY-based claude setup-token auth flow from canopy-web"
```

---

## Task 6: CLI auth REST endpoints + AppConfig token loading

**Files:**
- Create: `apps/common/auth_views.py`
- Create: `apps/common/token_loader.py`
- Create: `apps/common/tests/test_auth_views.py`
- Modify: `apps/common/apps.py`
- Modify: `apps/common/urls.py`

REST endpoints that wrap the auth_flow public API, plus an `AppConfig.ready()` hook that loads any persisted token at app boot.

- [ ] **Step 1: Write the token_loader test**

Add to `apps/common/tests/test_auth_flow.py` (append):

```python
def test_token_loader_loads_at_boot(tmp_path, monkeypatch):
    from apps.common import token_loader
    token_file = tmp_path / "oauth-token"
    token_file.write_text("sk-ant-oat01-boot")
    monkeypatch.setattr(auth_flow, "TOKEN_FILE", str(token_file))
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    token_loader.load_at_boot()
    assert os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") == "sk-ant-oat01-boot"
```

- [ ] **Step 2: Write the auth_views tests**

Create `apps/common/tests/test_auth_views.py`:

```python
"""Tests for /api/auth/cli/* endpoints. auth_flow is mocked at the function
level so the tests do not actually spawn a PTY."""
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(django_user_model):
    user = django_user_model.objects.create_user(
        email="dev@example.com", display_name="dev"
    )
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_status_returns_authenticated_when_token_present(client, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-yes")
    resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    assert resp.json() == {"data": {"authenticated": True}, "error": None}


def test_status_returns_unauthenticated_when_no_token(client, monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    with patch("apps.common.auth_flow.load_stored_token", return_value=None):
        resp = client.get("/api/auth/cli/status")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"authenticated": False}


def test_start_returns_auth_url(client):
    with patch(
        "apps.common.auth_flow.start",
        return_value={"auth_url": "https://claude.com/cai/oauth/authorize?x=1", "token": None, "status": "awaiting_code"},
    ):
        resp = client.post("/api/auth/cli/start")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["auth_url"].startswith("https://")
    assert body["status"] == "awaiting_code"


def test_complete_with_code_returns_token(client):
    with patch("apps.common.auth_flow.complete", return_value="sk-ant-oat01-fresh"):
        resp = client.post("/api/auth/cli/complete", {"code": "abc"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "complete"


def test_complete_without_active_session_returns_error(client):
    with patch(
        "apps.common.auth_flow.complete",
        side_effect=RuntimeError("No active auth flow."),
    ):
        resp = client.post("/api/auth/cli/complete", {"code": "abc"}, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "auth_flow_error"


def test_poll_returns_status(client):
    with patch(
        "apps.common.auth_flow.poll",
        return_value={"active": True, "authenticated": False, "elapsed_seconds": 5},
    ):
        resp = client.get("/api/auth/cli/poll")
    assert resp.status_code == 200
    assert resp.json()["data"]["active"] is True


def test_cancel_invokes_auth_flow_cancel(client):
    with patch("apps.common.auth_flow.cancel") as cancel:
        resp = client.post("/api/auth/cli/cancel")
    assert resp.status_code == 200
    cancel.assert_called_once()
```

- [ ] **Step 3: Run, expect URL/import failures**

Run: `pytest apps/common/tests/test_auth_views.py -v`
Expected: failures (URL not found / import error).

- [ ] **Step 4: Implement token_loader**

Create `apps/common/token_loader.py`:

```python
"""Loads any persisted OAuth token into os.environ at app boot.

Wired up via apps/common/apps.py CommonConfig.ready(). Idempotent — calling
load_at_boot() multiple times is safe.
"""
from __future__ import annotations

import logging

from . import auth_flow

logger = logging.getLogger(__name__)


def load_at_boot() -> None:
    token = auth_flow.load_stored_token()
    if token:
        logger.info("Loaded stored Claude OAuth token from %s", auth_flow.TOKEN_FILE)
    else:
        logger.info(
            "No stored Claude OAuth token at %s — visit /auth/cli to connect",
            auth_flow.TOKEN_FILE,
        )
```

- [ ] **Step 5: Update CommonConfig.ready()**

Modify `apps/common/apps.py`. The existing file is minimal:

```python
from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"

    def ready(self):
        from . import token_loader
        token_loader.load_at_boot()
```

- [ ] **Step 6: Implement auth_views**

Create `apps/common/auth_views.py`:

```python
"""REST endpoints for the in-app PTY-based Claude CLI auth flow.

All endpoints return the standard {data, error} envelope. The actual PTY
work happens in apps.common.auth_flow.
"""
from __future__ import annotations

import logging

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from . import auth_flow
from .envelope import error_response, success_response

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cli_auth_status(request: Request) -> Response:
    token = auth_flow.get_stored_token()
    return Response(success_response({"authenticated": bool(token)}))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_start(request: Request) -> Response:
    try:
        result = auth_flow.start()
    except RuntimeError as exc:
        return Response(
            error_response(message=str(exc), code="auth_flow_error"),
            status=400,
        )
    return Response(success_response(result))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_complete(request: Request) -> Response:
    code = request.data.get("code") or ""
    try:
        token = auth_flow.complete(code=code or None)
    except RuntimeError as exc:
        return Response(
            error_response(message=str(exc), code="auth_flow_error"),
            status=400,
        )
    return Response(success_response({"status": "complete", "token_set": bool(token)}))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cli_auth_poll(request: Request) -> Response:
    return Response(success_response(auth_flow.poll()))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cli_auth_cancel(request: Request) -> Response:
    auth_flow.cancel()
    return Response(success_response({"cancelled": True}))
```

- [ ] **Step 7: Wire URLs**

Modify `apps/common/urls.py`. The existing file currently has the health check route. Add:

```python
from django.urls import path

from . import auth_views, views

urlpatterns = [
    path("health", views.health_check, name="health"),
    path("auth/cli/status", auth_views.cli_auth_status, name="cli_auth_status"),
    path("auth/cli/start", auth_views.cli_auth_start, name="cli_auth_start"),
    path("auth/cli/complete", auth_views.cli_auth_complete, name="cli_auth_complete"),
    path("auth/cli/poll", auth_views.cli_auth_poll, name="cli_auth_poll"),
    path("auth/cli/cancel", auth_views.cli_auth_cancel, name="cli_auth_cancel"),
]
```

- [ ] **Step 8: Run the auth_views tests, expect pass**

Run: `pytest apps/common/tests/test_auth_views.py apps/common/tests/test_auth_flow.py::test_token_loader_loads_at_boot -v`
Expected: 8 passed.

- [ ] **Step 9: Commit**

```bash
git add apps/common/auth_views.py apps/common/token_loader.py apps/common/tests/test_auth_views.py apps/common/tests/test_auth_flow.py apps/common/apps.py apps/common/urls.py
git commit -m "feat(common): add CLI auth REST endpoints and AppConfig token loader"
```

---

## Task 7: Sessions REST API

**Files:**
- Create: `apps/sessions/views.py`
- Create: `apps/sessions/serializers.py`
- Create: `apps/sessions/urls.py`
- Create: `apps/sessions/tests/test_views.py`
- Create: `apps/sessions/tests/test_serializers.py`
- Modify: `config/urls.py`

CRUD endpoints for `Session` and the listing/lookup endpoints for the recent-sessions sidebar. Per the spec, all responses use the `{data, error}` envelope. DRF serializers translate Session/Message rows.

- [ ] **Step 1: Write serializer tests**

Create `apps/sessions/tests/test_serializers.py`:

```python
import pytest

from apps.sessions.models import Message, Session
from apps.sessions.serializers import MessageSerializer, SessionSerializer

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )
    return Session.objects.create(owner=user, title="my chat")


def test_session_serializer_basic(session):
    data = SessionSerializer(session).data
    assert data["slug"] == session.slug
    assert data["title"] == "my chat"
    assert data["status"] == "active"
    assert data["backend_kind"] == "cli"
    assert "created_at" in data
    assert "message_count" in data
    assert data["message_count"] == 0


def test_session_serializer_includes_message_count(session):
    Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    data = SessionSerializer(session).data
    assert data["message_count"] == 1


def test_message_serializer_basic(session):
    msg = Message.objects.create(
        session=session, turn_index=1, role="assistant",
        content={"text": "hello"}, plaintext="hello", status="complete",
    )
    data = MessageSerializer(msg).data
    assert data["turn_index"] == 1
    assert data["role"] == "assistant"
    assert data["plaintext"] == "hello"
    assert data["status"] == "complete"
```

- [ ] **Step 2: Implement serializers**

Create `apps/sessions/serializers.py`:

```python
"""DRF serializers for Session and Message."""
from rest_framework import serializers

from .models import Message, Session


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = [
            "id",
            "turn_index",
            "role",
            "content",
            "plaintext",
            "status",
            "error_detail",
            "started_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = fields


class SessionSerializer(serializers.ModelSerializer):
    message_count = serializers.SerializerMethodField()

    class Meta:
        model = Session
        fields = [
            "slug",
            "title",
            "status",
            "backend_kind",
            "source",
            "cli_session_id",
            "created_at",
            "updated_at",
            "message_count",
        ]
        read_only_fields = ["slug", "cli_session_id", "created_at", "updated_at", "message_count"]

    def get_message_count(self, obj: Session) -> int:
        return obj.messages.count()


class SessionDetailSerializer(SessionSerializer):
    """Same as SessionSerializer but includes the full message list."""
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(SessionSerializer.Meta):
        fields = SessionSerializer.Meta.fields + ["messages"]
```

- [ ] **Step 3: Run serializer tests, expect pass**

Run: `pytest apps/sessions/tests/test_serializers.py -v`
Expected: 3 passed.

- [ ] **Step 4: Write view tests**

Create `apps/sessions/tests/test_views.py`:

```python
import pytest
from rest_framework.test import APIClient

from apps.sessions.models import Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(
        email="other@example.com", display_name="other"
    )


@pytest.fixture
def client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_create_session_returns_slug(client):
    resp = client.post("/api/sessions", {}, format="json")
    assert resp.status_code == 201
    body = resp.json()
    assert body["error"] is None
    assert "slug" in body["data"]
    assert body["data"]["status"] == "active"


def test_create_session_creates_owner_participant(client, user):
    resp = client.post("/api/sessions", {}, format="json")
    slug = resp.json()["data"]["slug"]
    s = Session.objects.get(slug=slug)
    assert s.participants.filter(user=user, role="owner").exists()


def test_list_sessions_only_returns_current_user(client, user, other_user):
    Session.objects.create(owner=user, title="mine")
    Session.objects.create(owner=other_user, title="theirs")

    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    titles = [s["title"] for s in resp.json()["data"]]
    assert "mine" in titles
    assert "theirs" not in titles


def test_list_sessions_filters_by_status(client, user):
    Session.objects.create(owner=user, title="active")
    Session.objects.create(owner=user, title="archived", status="archived")

    resp = client.get("/api/sessions?status=archived")
    titles = [s["title"] for s in resp.json()["data"]]
    assert titles == ["archived"]


def test_list_sessions_respects_limit(client, user):
    for i in range(15):
        Session.objects.create(owner=user, title=f"s{i}")
    resp = client.get("/api/sessions?limit=5")
    assert len(resp.json()["data"]) == 5


def test_get_session_by_slug(client, user):
    s = Session.objects.create(owner=user, title="x")
    resp = client.get(f"/api/sessions/{s.slug}")
    assert resp.status_code == 200
    assert resp.json()["data"]["title"] == "x"
    assert resp.json()["data"]["messages"] == []


def test_get_session_404_for_other_users_session(client, other_user):
    s = Session.objects.create(owner=other_user, title="hidden")
    resp = client.get(f"/api/sessions/{s.slug}")
    assert resp.status_code == 404


def test_patch_session_updates_title(client, user):
    s = Session.objects.create(owner=user, title="old")
    resp = client.patch(f"/api/sessions/{s.slug}", {"title": "new"}, format="json")
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.title == "new"


def test_patch_session_updates_status(client, user):
    s = Session.objects.create(owner=user, title="x")
    resp = client.patch(f"/api/sessions/{s.slug}", {"status": "archived"}, format="json")
    assert resp.status_code == 200
    s.refresh_from_db()
    assert s.status == "archived"


def test_patch_session_rejects_unknown_field(client, user):
    s = Session.objects.create(owner=user, title="x")
    resp = client.patch(f"/api/sessions/{s.slug}", {"slug": "hacked"}, format="json")
    assert resp.status_code == 200  # ignored, slug is read-only
    s.refresh_from_db()
    assert s.slug != "hacked"
```

- [ ] **Step 5: Implement views**

Create `apps/sessions/views.py`:

```python
"""REST endpoints for Session CRUD and listing."""
from __future__ import annotations

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response

from .models import Session, SessionParticipant
from .serializers import SessionDetailSerializer, SessionSerializer


@api_view(["POST", "GET"])
@permission_classes([IsAuthenticated])
def session_collection(request: Request) -> Response:
    if request.method == "POST":
        return _create_session(request)
    return _list_sessions(request)


def _create_session(request: Request) -> Response:
    title = (request.data or {}).get("title", "")
    session = Session.objects.create(owner=request.user, title=title)
    SessionParticipant.objects.create(
        session=session, user=request.user, role="owner"
    )
    return Response(
        success_response(SessionSerializer(session).data),
        status=status.HTTP_201_CREATED,
    )


def _list_sessions(request: Request) -> Response:
    qs = Session.objects.filter(owner=request.user)
    status_filter = request.query_params.get("status")
    if status_filter:
        qs = qs.filter(status=status_filter)
    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 100))
    qs = qs.order_by("-updated_at")[:limit]
    return Response(success_response(SessionSerializer(qs, many=True).data))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def session_detail(request: Request, slug: str) -> Response:
    try:
        session = Session.objects.get(slug=slug, owner=request.user)
    except Session.DoesNotExist:
        return Response(
            error_response(message="session not found", code="not_found"),
            status=status.HTTP_404_NOT_FOUND,
        )

    if request.method == "GET":
        return Response(success_response(SessionDetailSerializer(session).data))

    # PATCH
    allowed = {"title", "status"}
    updates = {k: v for k, v in (request.data or {}).items() if k in allowed}
    if "status" in updates and updates["status"] not in {"active", "archived"}:
        return Response(
            error_response(message="invalid status", code="validation_error"),
            status=400,
        )
    for k, v in updates.items():
        setattr(session, k, v)
    if updates:
        session.save(update_fields=list(updates.keys()) + ["updated_at"])
    return Response(success_response(SessionSerializer(session).data))
```

- [ ] **Step 6: Implement urls**

Create `apps/sessions/urls.py`:

```python
from django.urls import path

from . import views

urlpatterns = [
    path("sessions", views.session_collection, name="session_collection"),
    path("sessions/<slug:slug>", views.session_detail, name="session_detail"),
]
```

- [ ] **Step 7: Wire into config/urls.py**

Modify `config/urls.py`. The current top-level urls include `apps.common.urls` at `api/`. Add the sessions urls under the same prefix:

```python
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    path("api/", include("apps.sessions.urls")),
    re_path(
        r"^(?!api/|admin/|static/|assets/).*$",
        TemplateView.as_view(template_name="index.html"),
        name="spa",
    ),
]
```

- [ ] **Step 8: Run the view tests, expect pass**

Run: `pytest apps/sessions/tests/test_views.py -v`
Expected: 10 passed.

- [ ] **Step 9: Commit**

```bash
git add apps/sessions/views.py apps/sessions/serializers.py apps/sessions/urls.py apps/sessions/tests/ config/urls.py
git commit -m "feat(sessions): add REST API for session CRUD and listing"
```

---

## Task 8: Messages send endpoint and SSE streaming

**Files:**
- Create: `apps/sessions/streaming.py`
- Modify: `apps/sessions/views.py`
- Modify: `apps/sessions/urls.py`
- Create: `apps/sessions/tests/test_streaming.py`
- Modify: `apps/sessions/tests/test_views.py` (append send-message tests)

The two endpoints that drive the actual chat. `POST /api/sessions/<slug>/messages` creates the user `Message` (status=complete) and a placeholder assistant `Message` (status=pending) and returns both ids. `GET /api/messages/<id>/stream` is the SSE endpoint — it drives the `CLIBackend.stream_completion()` async iterator for the placeholder message and streams events to the client. Reconnect semantics per the spec: if the message is `streaming` already, yield current `plaintext` first then continue; if `complete` or `error`, yield final state and close.

- [ ] **Step 1: Write the send-message tests (append to test_views.py)**

Append to `apps/sessions/tests/test_views.py`:

```python
def test_post_message_creates_user_and_assistant_rows(client, user):
    s = Session.objects.create(owner=user, title="x")
    resp = client.post(f"/api/sessions/{s.slug}/messages", {"text": "hello"}, format="json")
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert "user_message_id" in body
    assert "assistant_message_id" in body

    user_msg = Message.objects.get(id=body["user_message_id"])
    asst_msg = Message.objects.get(id=body["assistant_message_id"])
    assert user_msg.role == "user"
    assert user_msg.plaintext == "hello"
    assert user_msg.status == "complete"
    assert asst_msg.role == "assistant"
    assert asst_msg.status == "pending"


def test_post_message_assigns_monotonic_turn_index(client, user):
    s = Session.objects.create(owner=user, title="x")
    Message.objects.create(
        session=s, turn_index=5, role="user",
        content={"text": "old"}, plaintext="old", status="complete",
    )
    resp = client.post(f"/api/sessions/{s.slug}/messages", {"text": "next"}, format="json")
    body = resp.json()["data"]
    user_msg = Message.objects.get(id=body["user_message_id"])
    asst_msg = Message.objects.get(id=body["assistant_message_id"])
    assert user_msg.turn_index == 6
    assert asst_msg.turn_index == 7


def test_post_message_404_for_other_users_session(client, other_user):
    s = Session.objects.create(owner=other_user)
    resp = client.post(f"/api/sessions/{s.slug}/messages", {"text": "x"}, format="json")
    assert resp.status_code == 404
```

Add the necessary import at the top of the file:

```python
from apps.sessions.models import Message, Session
```

- [ ] **Step 2: Implement the send-message view**

Append to `apps/sessions/views.py`:

```python
from django.db import transaction

from .models import Message  # add to imports at top of file


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def send_message(request: Request, slug: str) -> Response:
    try:
        session = Session.objects.get(slug=slug, owner=request.user)
    except Session.DoesNotExist:
        return Response(
            error_response(message="session not found", code="not_found"),
            status=404,
        )

    text = (request.data or {}).get("text", "").strip()
    if not text:
        return Response(
            error_response(message="text is required", code="validation_error"),
            status=400,
        )

    with transaction.atomic():
        last_turn = (
            Message.objects.filter(session=session)
            .order_by("-turn_index")
            .values_list("turn_index", flat=True)
            .first()
        )
        next_turn = (last_turn or 0) + 1
        user_msg = Message.objects.create(
            session=session,
            turn_index=next_turn,
            role="user",
            sender_user=request.user,
            content={"text": text},
            plaintext=text,
            status="complete",
            completed_at=timezone.now(),
        )
        assistant_msg = Message.objects.create(
            session=session,
            turn_index=next_turn + 1,
            role="assistant",
            content={"text": ""},
            plaintext="",
            status="pending",
        )

    return Response(
        success_response({
            "user_message_id": user_msg.id,
            "assistant_message_id": assistant_msg.id,
        }),
        status=201,
    )
```

Add `from django.utils import timezone` to the imports at the top.

- [ ] **Step 3: Wire the route**

Modify `apps/sessions/urls.py`:

```python
from django.urls import path

from . import streaming, views

urlpatterns = [
    path("sessions", views.session_collection, name="session_collection"),
    path("sessions/<slug:slug>", views.session_detail, name="session_detail"),
    path("sessions/<slug:slug>/messages", views.send_message, name="send_message"),
    path("messages/<int:message_id>/stream", streaming.stream_assistant_message, name="message_stream"),
]
```

(`streaming.stream_assistant_message` lands in step 5 — Django imports the urls module at startup, so the import will fail until the file exists. Implement Step 5 in the same loop and run tests at the end.)

- [ ] **Step 4: Implement the SSE streaming view**

Create `apps/sessions/streaming.py`:

```python
"""SSE streaming endpoint for assistant messages.

GET /api/messages/<id>/stream

Drives CLIBackend.stream_completion() for the given placeholder Message (which
must be in status=pending or status=streaming) and writes the resulting tokens
into the message row, while also yielding SSE frames to the client.

Reconnect semantics:
- If the message is already in status=streaming, yield the current plaintext
  as a single delta event first, then continue.
- If the message is already complete or error, yield the final state and close.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from asgiref.sync import sync_to_async
from django.http import HttpRequest, StreamingHttpResponse
from django.utils import timezone

from apps.common.chat_backend import StreamEvent, StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError

from .models import Message, Session

logger = logging.getLogger(__name__)


# Module-level singleton — fine for Phase 2 (single instance Cloud Run).
_backend: CLIBackend | None = None


def _get_backend() -> CLIBackend:
    global _backend
    if _backend is None:
        _backend = CLIBackend()
    return _backend


async def stream_assistant_message(request: HttpRequest, message_id: int):
    """Async view that returns a text/event-stream response."""
    user = await sync_to_async(lambda: request.user)()
    if not user or not user.is_authenticated:
        return StreamingHttpResponse(
            iter([_sse_frame("error", {"message": "unauthenticated"})]),
            content_type="text/event-stream",
            status=401,
        )

    try:
        message = await sync_to_async(_load_message_for_user)(message_id, user)
    except Message.DoesNotExist:
        return StreamingHttpResponse(
            iter([_sse_frame("error", {"message": "message not found"})]),
            content_type="text/event-stream",
            status=404,
        )

    response = StreamingHttpResponse(
        _generate(message),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # disable proxy buffering
    return response


def _load_message_for_user(message_id: int, user) -> Message:
    return Message.objects.select_related("session").get(
        id=message_id, session__owner=user
    )


async def _generate(message: Message) -> AsyncIterator[bytes]:
    """The SSE generator. Replays existing state if reconnecting, then drives
    the backend if the message is still pending."""
    # Reconnect: if already complete/error, yield current state and close
    if message.status == "complete":
        if message.plaintext:
            yield _sse_frame("delta", {"text": message.plaintext})
        yield _sse_frame("done", {})
        return
    if message.status == "error":
        yield _sse_frame(
            "error", {"message": message.error_detail or "unknown error"}
        )
        return

    # Reconnect to a streaming message: replay current plaintext, then continue
    if message.status == "streaming" and message.plaintext:
        yield _sse_frame("delta", {"text": message.plaintext})

    # Otherwise drive the backend
    user_text = await sync_to_async(_load_last_user_text)(message)
    backend = _get_backend()

    # Mark streaming
    await sync_to_async(_mark_streaming)(message)

    accumulated = list(message.plaintext) if message.plaintext else []
    last_db_write = asyncio.get_event_loop().time()

    try:
        async for event in backend.stream_completion(
            session=message.session, new_user_message=user_text
        ):
            yield _sse_frame_for(event)

            if event.type is StreamEventType.DELTA and event.text:
                accumulated.append(event.text)
                # Debounce DB writes to ~250ms
                now = asyncio.get_event_loop().time()
                if now - last_db_write > 0.25:
                    await sync_to_async(_update_plaintext)(
                        message, "".join(accumulated)
                    )
                    last_db_write = now

            elif event.type is StreamEventType.SESSION_ID:
                # Session.cli_session_id is persisted by the CLIBackend itself
                pass

            elif event.type is StreamEventType.TOOL_USE:
                await sync_to_async(_create_tool_message)(
                    message.session, event.tool_block, role="tool_use"
                )

            elif event.type is StreamEventType.TOOL_RESULT:
                await sync_to_async(_create_tool_message)(
                    message.session, event.tool_block, role="tool_result"
                )

            elif event.type is StreamEventType.DONE:
                await sync_to_async(_mark_complete)(
                    message, "".join(accumulated)
                )
                return

            elif event.type is StreamEventType.ERROR:
                await sync_to_async(_mark_error)(
                    message, event.error or "unknown"
                )
                return

    except CLIBackendError as exc:
        logger.exception("CLIBackend failed during stream")
        await sync_to_async(_mark_error)(message, str(exc))
        yield _sse_frame("error", {"message": str(exc)})

    except asyncio.CancelledError:
        logger.info("SSE stream cancelled by client for message %s", message.id)
        await sync_to_async(_mark_error)(
            message, f"cancelled (partial: {len(''.join(accumulated))} chars)"
        )
        raise


# ────────────────────────────── helpers ──────────────────────────────

def _sse_frame(event_name: str, data: dict) -> bytes:
    return f"event: {event_name}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


def _sse_frame_for(event: StreamEvent) -> bytes:
    if event.type is StreamEventType.DELTA:
        return _sse_frame("delta", {"text": event.text})
    if event.type is StreamEventType.TOOL_USE:
        return _sse_frame("tool_use", {"block": event.tool_block})
    if event.type is StreamEventType.TOOL_RESULT:
        return _sse_frame("tool_result", {"block": event.tool_block})
    if event.type is StreamEventType.SESSION_ID:
        return _sse_frame("session_id", {"session_id": event.session_id})
    if event.type is StreamEventType.DONE:
        return _sse_frame("done", {})
    if event.type is StreamEventType.ERROR:
        return _sse_frame("error", {"message": event.error or ""})
    return b""


def _load_last_user_text(asst_message: Message) -> str:
    """The user message that immediately precedes this assistant placeholder."""
    user_msg = (
        Message.objects.filter(session=asst_message.session, role="user")
        .order_by("-turn_index")
        .first()
    )
    return user_msg.plaintext if user_msg else ""


def _mark_streaming(message: Message) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="streaming", started_at=timezone.now()
    )


def _update_plaintext(message: Message, text: str) -> None:
    Message.objects.filter(pk=message.pk).update(plaintext=text)


def _mark_complete(message: Message, text: str) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="complete",
        plaintext=text,
        content={"text": text},
        completed_at=timezone.now(),
    )


def _mark_error(message: Message, detail: str) -> None:
    Message.objects.filter(pk=message.pk).update(
        status="error", error_detail=detail
    )


def _create_tool_message(session: Session, block: dict, *, role: str) -> None:
    last_turn = (
        Message.objects.filter(session=session)
        .order_by("-turn_index")
        .values_list("turn_index", flat=True)
        .first()
    )
    Message.objects.create(
        session=session,
        turn_index=(last_turn or 0) + 1,
        role=role,
        content=block,
        plaintext=str(block.get("content") or block.get("input") or ""),
        status="complete",
        completed_at=timezone.now(),
    )
```

- [ ] **Step 5: Write the streaming tests**

Create `apps/sessions/tests/test_streaming.py`:

```python
"""Tests for the SSE streaming endpoint. CLIBackend is patched to a fake that
yields a deterministic StreamEvent sequence."""
import json
from unittest.mock import patch

import pytest

from apps.common.chat_backend import StreamEvent
from apps.sessions.models import Message, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )
    return Session.objects.create(owner=user, title="x")


@pytest.fixture
def assistant_message(session):
    Message.objects.create(
        session=session, turn_index=1, role="user",
        content={"text": "hi"}, plaintext="hi", status="complete",
    )
    return Message.objects.create(
        session=session, turn_index=2, role="assistant",
        content={"text": ""}, plaintext="", status="pending",
    )


class FakeBackend:
    def __init__(self, events):
        self._events = events

    async def stream_completion(self, *, session, new_user_message):
        for e in self._events:
            yield e


def _consume(generator):
    """Drain a sync iterable of bytes into a single string."""
    return b"".join(generator).decode("utf-8")


def test_complete_message_replays_then_done(client_authenticated_for, session, assistant_message):
    assistant_message.status = "complete"
    assistant_message.plaintext = "hello there"
    assistant_message.save()

    client = client_authenticated_for(session.owner)
    resp = client.get(f"/api/messages/{assistant_message.id}/stream")
    body = _consume(resp.streaming_content)
    assert "event: delta" in body
    assert "hello there" in body
    assert "event: done" in body


def test_error_message_yields_error(client_authenticated_for, session, assistant_message):
    assistant_message.status = "error"
    assistant_message.error_detail = "boom"
    assistant_message.save()

    client = client_authenticated_for(session.owner)
    resp = client.get(f"/api/messages/{assistant_message.id}/stream")
    body = _consume(resp.streaming_content)
    assert "event: error" in body
    assert "boom" in body


def test_pending_message_drives_backend(client_authenticated_for, session, assistant_message):
    fake = FakeBackend([
        StreamEvent.delta(text="Hi "),
        StreamEvent.delta(text="there!"),
        StreamEvent.done(),
    ])
    client = client_authenticated_for(session.owner)

    with patch("apps.sessions.streaming._get_backend", return_value=fake):
        resp = client.get(f"/api/messages/{assistant_message.id}/stream")
        body = _consume(resp.streaming_content)

    assert body.count("event: delta") == 2
    assert "event: done" in body

    assistant_message.refresh_from_db()
    assert assistant_message.status == "complete"
    assert assistant_message.plaintext == "Hi there!"


def test_tool_use_event_creates_message_row(client_authenticated_for, session, assistant_message):
    fake = FakeBackend([
        StreamEvent.delta(text="Reading file"),
        StreamEvent.tool_use(block={"id": "t1", "name": "Read", "input": {"file_path": "/x"}}),
        StreamEvent.tool_result(block={"tool_use_id": "t1", "content": "file body"}),
        StreamEvent.delta(text="Done"),
        StreamEvent.done(),
    ])
    client = client_authenticated_for(session.owner)
    with patch("apps.sessions.streaming._get_backend", return_value=fake):
        client.get(f"/api/messages/{assistant_message.id}/stream").streaming_content
        # consume the generator
        list(_)  # noqa - prior line consumed already

    tool_messages = Message.objects.filter(
        session=session, role__in=["tool_use", "tool_result"]
    )
    assert tool_messages.count() == 2
```

Add a fixture in `apps/sessions/tests/conftest.py` (create the file if it doesn't exist) for the auth helper:

```python
import pytest
from rest_framework.test import APIClient


@pytest.fixture
def client_authenticated_for():
    def _make(user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c
    return _make
```

- [ ] **Step 6: Run all the streaming and view tests**

Run: `pytest apps/sessions/ -v`
Expected: all tests pass. The send-message tests from Step 1 + the new streaming tests + the existing view tests.

If `test_tool_use_event_creates_message_row` flakes due to the awkward generator-consumption pattern, replace its body with a cleaner consume:

```python
def test_tool_use_event_creates_message_row(client_authenticated_for, session, assistant_message):
    fake = FakeBackend([
        StreamEvent.delta(text="Reading file"),
        StreamEvent.tool_use(block={"id": "t1", "name": "Read", "input": {"file_path": "/x"}}),
        StreamEvent.tool_result(block={"tool_use_id": "t1", "content": "file body"}),
        StreamEvent.delta(text="Done"),
        StreamEvent.done(),
    ])
    client = client_authenticated_for(session.owner)
    with patch("apps.sessions.streaming._get_backend", return_value=fake):
        resp = client.get(f"/api/messages/{assistant_message.id}/stream")
        list(resp.streaming_content)

    tool_messages = Message.objects.filter(
        session=session, role__in=["tool_use", "tool_result"]
    )
    assert tool_messages.count() == 2
```

- [ ] **Step 7: Commit**

```bash
git add apps/sessions/views.py apps/sessions/streaming.py apps/sessions/urls.py apps/sessions/tests/
git commit -m "feat(sessions): add send-message and SSE streaming endpoints"
```

---

## Task 9: Auto-titling on first user message

**Files:**
- Create: `apps/sessions/auto_title.py`
- Modify: `apps/sessions/views.py` (`send_message` triggers the title task on first turn)
- Create: `apps/sessions/tests/test_auto_title.py`

When a session has a blank title and the user sends their first message, generate a 6-word summary in the background and set it as the session title. Uses the same `CLIBackend` as the main chat. Failure is non-blocking — if the title call fails, the title stays blank.

Background task strategy: spawn a fresh asyncio task that runs after the SSE stream completes (not before — the user message has already created the SSE turn). The simplest approach is to have the streaming view enqueue the title call after `_mark_complete`. Since Django+asyncio doesn't ship with a real task queue, we use `asyncio.create_task(...)` and accept that the task is best-effort within the worker process lifetime.

Alternative: trigger the auto-title on `POST /api/sessions/<slug>/messages` (Task 8), in a background task, before returning. Either works. We pick the SSE-completion approach so the title generation does not contend with the in-flight chat call.

- [ ] **Step 1: Write the auto-title test**

Create `apps/sessions/tests/test_auto_title.py`:

```python
"""Tests for the auto-titling background task."""
from unittest.mock import patch

import pytest

from apps.common.chat_backend import StreamEvent
from apps.sessions.auto_title import generate_title_for_session
from apps.sessions.models import Message, Session

pytestmark = pytest.mark.django_db


@pytest.fixture
def session(django_user_model):
    user = django_user_model.objects.create_user(
        email="t@example.com", display_name="t"
    )
    s = Session.objects.create(owner=user, title="")
    Message.objects.create(
        session=s, turn_index=1, role="user",
        content={"text": "explain quicksort to me"},
        plaintext="explain quicksort to me", status="complete",
    )
    return s


class FakeBackend:
    def __init__(self, title_text):
        self._text = title_text

    async def stream_completion(self, *, session, new_user_message):
        for chunk in self._text.split():
            yield StreamEvent.delta(text=chunk + " ")
        yield StreamEvent.done()


async def test_generates_and_persists_title(session):
    fake = FakeBackend("Quicksort algorithm explained simply for beginners")
    with patch("apps.sessions.auto_title._get_backend", return_value=fake):
        await generate_title_for_session(session)

    session.refresh_from_db()
    assert session.title == "Quicksort algorithm explained simply for beginners"


async def test_does_nothing_if_title_already_set(session):
    session.title = "manually set"
    session.save()
    fake = FakeBackend("would be auto generated")
    with patch("apps.sessions.auto_title._get_backend", return_value=fake):
        await generate_title_for_session(session)

    session.refresh_from_db()
    assert session.title == "manually set"


async def test_failure_leaves_title_blank(session):
    from apps.common.cli_backend import CLIBackendError

    class FailingBackend:
        async def stream_completion(self, *, session, new_user_message):
            raise CLIBackendError("boom")
            yield  # unreachable but makes this a generator

    with patch("apps.sessions.auto_title._get_backend", return_value=FailingBackend()):
        await generate_title_for_session(session)  # should not raise

    session.refresh_from_db()
    assert session.title == ""
```

- [ ] **Step 2: Implement auto_title.py**

Create `apps/sessions/auto_title.py`:

```python
"""Background task that generates a 6-word title for a session.

Triggered from the SSE streaming view after the first assistant turn completes.
Best-effort: any failure is logged and swallowed so it cannot break the chat
experience.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from apps.common.chat_backend import StreamEventType
from apps.common.cli_backend import CLIBackend, CLIBackendError

from .models import Session

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "Summarize the following user message in exactly 6 words or fewer. "
    "Respond with ONLY the title, no quotes, no punctuation, no explanation:\n\n"
    "{text}"
)


_backend: CLIBackend | None = None


def _get_backend() -> CLIBackend:
    global _backend
    if _backend is None:
        _backend = CLIBackend()
    return _backend


async def generate_title_for_session(session: Session) -> None:
    """Generate and persist a title. Idempotent — does nothing if title is set."""
    await sync_to_async(session.refresh_from_db)()
    if session.title.strip():
        return

    user_text = await sync_to_async(_load_first_user_message_text)(session)
    if not user_text:
        return

    prompt = _TITLE_PROMPT.format(text=user_text)
    backend = _get_backend()

    accumulated: list[str] = []
    try:
        async for event in backend.stream_completion(
            session=session, new_user_message=prompt
        ):
            if event.type is StreamEventType.DELTA and event.text:
                accumulated.append(event.text)
            elif event.type in (
                StreamEventType.DONE, StreamEventType.ERROR
            ):
                break
    except CLIBackendError as exc:
        logger.warning("Auto-title backend failed for session %s: %s", session.slug, exc)
        return

    title = "".join(accumulated).strip().strip('"').strip("'")
    if not title:
        return
    await sync_to_async(_save_title)(session, title)


def _load_first_user_message_text(session: Session) -> str:
    msg = (
        session.messages.filter(role="user")
        .order_by("turn_index")
        .first()
    )
    return msg.plaintext if msg else ""


def _save_title(session: Session, title: str) -> None:
    Session.objects.filter(pk=session.pk).update(title=title)
```

**Note:** auto-title uses its own `CLIBackend` instance. Calling it during a streaming chat turn would re-enter the same module. Since we trigger it AFTER the main chat completes (not in parallel), there's no contention. The auto-title call runs `claude -p` standalone — it does NOT use `--resume`. We don't want to pollute the user's session history with the title prompt.

Update `auto_title.py` so the auto-title backend call uses a synthetic Session-like object that has `cli_session_id=None` to force the no-resume path:

Actually, the cleanest fix is to make the title generation NOT go through the user's `Session.cli_session_id`. We do this by passing a different session-shaped object — but the typing is awkward. Simpler: temporarily pass an in-memory `Session` with `cli_session_id=None` for the title call, OR add a parameter to `stream_completion` to opt out of resume.

Add a `force_fresh_session: bool = False` parameter to `CLIBackend.stream_completion` that bypasses the resume path. Modify Task 4's CLIBackend with this.

- [ ] **Step 3: Add `force_fresh_session` to CLIBackend**

Modify `apps/common/cli_backend.py`. Update the signature and the early branch:

```python
async def stream_completion(
    self,
    *,
    session: Session,
    new_user_message: str,
    force_fresh_session: bool = False,
) -> AsyncIterator[StreamEvent]:
    try:
        self._breaker.check()
    except CircuitOpenError as exc:
        raise CLIBackendError(str(exc)) from exc

    # First attempt: resume if we have a CLI session id and resume is allowed
    if session.cli_session_id and not force_fresh_session:
        ...
```

And update the `ChatBackend` Protocol in `apps/common/chat_backend.py`:

```python
async def stream_completion(
    self,
    *,
    session: Session,
    new_user_message: str,
    force_fresh_session: bool = False,
) -> AsyncIterator[StreamEvent]: ...
```

And update `auto_title.generate_title_for_session` to pass `force_fresh_session=True`:

```python
async for event in backend.stream_completion(
    session=session, new_user_message=prompt, force_fresh_session=True
):
```

The streaming view in `apps/sessions/streaming.py` uses the default (`force_fresh_session=False`), so it's unchanged.

**Important:** when using `force_fresh_session=True`, the CLIBackend should NOT update `session.cli_session_id` with the captured id from the title call (we don't want the title call to clobber the real session id). Add a guard in the SESSION_ID branch:

```python
# In _spawn → _drain → main loop body, when handling SESSION_ID
elif event.type is StreamEventType.SESSION_ID:
    if not force_fresh_session:
        await self._persist_session_id(session, event.session_id)
```

Adjust both branches (resume and fresh) of `stream_completion` accordingly. The `_persist_session_id` call in CLIBackend.stream_completion should be guarded by `not force_fresh_session`.

- [ ] **Step 4: Trigger auto-title from streaming view after first complete**

Modify `apps/sessions/streaming.py`. In `_generate`, after the `_mark_complete` call inside the `DONE` branch, schedule the auto-title task:

```python
elif event.type is StreamEventType.DONE:
    await sync_to_async(_mark_complete)(message, "".join(accumulated))
    asyncio.create_task(_maybe_auto_title(message.session))
    return
```

Add the helper:

```python
async def _maybe_auto_title(session: Session) -> None:
    """Fire-and-forget auto-title call. Wraps generate_title_for_session in
    a task-safe shell so any exception is swallowed."""
    from .auto_title import generate_title_for_session
    try:
        await generate_title_for_session(session)
    except Exception:
        logger.exception("Auto-title task failed for session %s", session.slug)
```

- [ ] **Step 5: Run the auto-title and streaming tests**

Run: `pytest apps/sessions/tests/test_auto_title.py apps/sessions/tests/test_streaming.py -v`
Expected: all auto_title tests pass; streaming tests still pass (the new `asyncio.create_task` is fire-and-forget and doesn't change observable behavior in synchronous test mode).

If `test_pending_message_drives_backend` fails because the auto-title task references a sync FakeBackend, the FakeBackend's `stream_completion` must accept the new `force_fresh_session=False` keyword. Update it:

```python
class FakeBackend:
    def __init__(self, events):
        self._events = events

    async def stream_completion(self, *, session, new_user_message, force_fresh_session=False):
        for e in self._events:
            yield e
```

Apply the same kwarg fix in `test_streaming.py`.

- [ ] **Step 6: Commit**

```bash
git add apps/sessions/auto_title.py apps/sessions/tests/test_auto_title.py apps/sessions/streaming.py apps/common/cli_backend.py apps/common/chat_backend.py
git commit -m "feat(sessions): auto-generate session title after first turn"
```

---

## Task 10: Frontend types and SSE consumer hook

**Files:**
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/sessions.ts`
- Create: `frontend/src/api/messages.ts`
- Create: `frontend/src/api/auth.ts`
- Create: `frontend/src/hooks/useStreamingMessage.ts`
- Modify: `frontend/src/api/client.ts` (extend with envelope unwrap helper)

The frontend half of the SSE pipeline. The hook opens an `EventSource` to `/api/messages/<id>/stream`, accumulates `delta` text, collects tool blocks, and exposes a finalized state when `done` arrives.

- [ ] **Step 1: Define shared types**

Create `frontend/src/api/types.ts`:

```typescript
export type SessionStatus = "active" | "archived" | "imported";
export type BackendKind = "cli" | "api" | "mcp";
export type SessionSource = "web" | "upload";
export type MessageStatus = "pending" | "streaming" | "complete" | "error";
export type MessageRole =
  | "user"
  | "assistant"
  | "system"
  | "tool_use"
  | "tool_result";

export interface Session {
  slug: string;
  title: string;
  status: SessionStatus;
  backend_kind: BackendKind;
  source: SessionSource;
  cli_session_id: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface SessionDetail extends Session {
  messages: Message[];
}

export interface Message {
  id: number;
  turn_index: number;
  role: MessageRole;
  content: Record<string, unknown>;
  plaintext: string;
  status: MessageStatus;
  error_detail: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export type StreamEvent =
  | { type: "delta"; text: string }
  | { type: "tool_use"; block: Record<string, unknown> }
  | { type: "tool_result"; block: Record<string, unknown> }
  | { type: "session_id"; session_id: string }
  | { type: "done" }
  | { type: "error"; message: string };

export interface ApiEnvelope<T> {
  data: T | null;
  error: { code: string; message: string } | null;
}

export interface CliAuthStatus {
  authenticated: boolean;
}

export interface CliAuthStartResult {
  auth_url: string | null;
  token: string | null;
  status: "complete" | "awaiting_code";
}

export interface CliAuthPollResult {
  active: boolean;
  authenticated: boolean;
  elapsed_seconds?: number;
}
```

- [ ] **Step 2: Extend the API client**

Modify `frontend/src/api/client.ts`. The current file is a small fetch wrapper. Add an `unwrap` helper that throws on `error` and returns `data`:

```typescript
import type { ApiEnvelope } from "./types";

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const resp = await fetch(path, { ...init, headers });
  let envelope: ApiEnvelope<T>;
  try {
    envelope = await resp.json();
  } catch {
    throw new ApiError("invalid_response", `${resp.status} ${resp.statusText}`);
  }
  if (envelope.error) {
    throw new ApiError(envelope.error.code, envelope.error.message);
  }
  if (envelope.data === null) {
    throw new ApiError("empty_response", "no data in envelope");
  }
  return envelope.data;
}
```

- [ ] **Step 3: Implement sessions/messages/auth API modules**

Create `frontend/src/api/sessions.ts`:

```typescript
import { apiFetch } from "./client";
import type { Session, SessionDetail } from "./types";

export const listSessions = (limit = 20, status?: string) => {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  return apiFetch<Session[]>(`/api/sessions?${params}`);
};

export const createSession = () =>
  apiFetch<Session>("/api/sessions", { method: "POST", body: "{}" });

export const getSession = (slug: string) =>
  apiFetch<SessionDetail>(`/api/sessions/${slug}`);

export const updateSession = (slug: string, updates: Partial<Session>) =>
  apiFetch<Session>(`/api/sessions/${slug}`, {
    method: "PATCH",
    body: JSON.stringify(updates),
  });
```

Create `frontend/src/api/messages.ts`:

```typescript
import { apiFetch } from "./client";

export interface SendMessageResult {
  user_message_id: number;
  assistant_message_id: number;
}

export const sendMessage = (slug: string, text: string) =>
  apiFetch<SendMessageResult>(`/api/sessions/${slug}/messages`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });

export const streamUrl = (assistantMessageId: number) =>
  `/api/messages/${assistantMessageId}/stream`;
```

Create `frontend/src/api/auth.ts`:

```typescript
import { apiFetch } from "./client";
import type {
  CliAuthPollResult,
  CliAuthStartResult,
  CliAuthStatus,
} from "./types";

export const cliAuthStatus = () =>
  apiFetch<CliAuthStatus>("/api/auth/cli/status");

export const cliAuthStart = () =>
  apiFetch<CliAuthStartResult>("/api/auth/cli/start", { method: "POST" });

export const cliAuthComplete = (code: string) =>
  apiFetch<{ status: string; token_set: boolean }>(
    "/api/auth/cli/complete",
    { method: "POST", body: JSON.stringify({ code }) },
  );

export const cliAuthPoll = () =>
  apiFetch<CliAuthPollResult>("/api/auth/cli/poll");

export const cliAuthCancel = () =>
  apiFetch<{ cancelled: boolean }>(
    "/api/auth/cli/cancel",
    { method: "POST" },
  );
```

- [ ] **Step 4: Implement the useStreamingMessage hook**

Create `frontend/src/hooks/useStreamingMessage.ts`:

```typescript
import { useEffect, useRef, useState } from "react";

import { streamUrl } from "../api/messages";
import type { StreamEvent } from "../api/types";

export type StreamPhase = "idle" | "streaming" | "complete" | "error" | "cancelled";

export interface ToolBlock {
  kind: "tool_use" | "tool_result";
  block: Record<string, unknown>;
}

export interface StreamingState {
  phase: StreamPhase;
  text: string;
  tools: ToolBlock[];
  error: string | null;
}

const INITIAL: StreamingState = {
  phase: "idle",
  text: "",
  tools: [],
  error: null,
};

/**
 * Opens an EventSource against /api/messages/<id>/stream and accumulates
 * delta text + tool blocks until done|error or the consumer cancels.
 */
export function useStreamingMessage(assistantMessageId: number | null) {
  const [state, setState] = useState<StreamingState>(INITIAL);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (assistantMessageId == null) {
      setState(INITIAL);
      return;
    }

    setState({ ...INITIAL, phase: "streaming" });
    const source = new EventSource(streamUrl(assistantMessageId));
    sourceRef.current = source;

    const onDelta = (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as { text: string };
      setState((s) => ({ ...s, text: s.text + payload.text }));
    };
    const onToolUse = (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as { block: Record<string, unknown> };
      setState((s) => ({
        ...s,
        tools: [...s.tools, { kind: "tool_use", block: payload.block }],
      }));
    };
    const onToolResult = (e: MessageEvent) => {
      const payload = JSON.parse(e.data) as { block: Record<string, unknown> };
      setState((s) => ({
        ...s,
        tools: [...s.tools, { kind: "tool_result", block: payload.block }],
      }));
    };
    const onDone = () => {
      setState((s) => ({ ...s, phase: "complete" }));
      source.close();
    };
    const onError = (e: MessageEvent) => {
      let message = "stream error";
      try {
        message = (JSON.parse(e.data) as { message: string }).message;
      } catch {
        // EventSource also fires generic error events with no data — leave default
      }
      setState((s) => ({ ...s, phase: "error", error: message }));
      source.close();
    };

    source.addEventListener("delta", onDelta);
    source.addEventListener("tool_use", onToolUse);
    source.addEventListener("tool_result", onToolResult);
    source.addEventListener("done", onDone);
    source.addEventListener("error", onError);

    return () => {
      source.close();
    };
  }, [assistantMessageId]);

  const cancel = () => {
    if (sourceRef.current) {
      sourceRef.current.close();
      sourceRef.current = null;
      setState((s) => ({ ...s, phase: "cancelled" }));
    }
  };

  return { ...state, cancel };
}
```

- [ ] **Step 5: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/ frontend/src/hooks/useStreamingMessage.ts
git commit -m "feat(frontend): add API client, types, and SSE consumer hook"
```

---

## Task 11: Frontend ChatPage with MessageList, SendBox, stop button

**Files:**
- Create: `frontend/src/components/MessageList.tsx`
- Create: `frontend/src/components/MessageItem.tsx`
- Create: `frontend/src/components/SendBox.tsx`
- Create: `frontend/src/pages/ChatPage.tsx`
- Create: `frontend/src/pages/ChatRedirectPage.tsx`

The single-session chat view. Renders the message history, hooks the streaming hook into the live assistant message, and exposes a send box that flips to a stop button while streaming.

- [ ] **Step 1: Implement MessageItem**

Create `frontend/src/components/MessageItem.tsx`:

```typescript
import type { Message } from "../api/types";

interface Props {
  message: Message;
  liveText?: string;
  isLive?: boolean;
}

export function MessageItem({ message, liveText, isLive }: Props) {
  const text = isLive ? liveText ?? message.plaintext : message.plaintext;

  if (message.role === "tool_use") {
    return (
      <details className="my-2 rounded border border-zinc-200 bg-zinc-50 p-2 text-sm">
        <summary className="cursor-pointer text-zinc-600">
          tool_use: {String(message.content?.name ?? "unknown")}
        </summary>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-zinc-700">
          {JSON.stringify(message.content, null, 2)}
        </pre>
      </details>
    );
  }
  if (message.role === "tool_result") {
    return (
      <details className="my-2 rounded border border-zinc-200 bg-zinc-50 p-2 text-sm">
        <summary className="cursor-pointer text-zinc-600">tool_result</summary>
        <pre className="mt-2 whitespace-pre-wrap text-xs text-zinc-700">
          {message.plaintext}
        </pre>
      </details>
    );
  }

  const bubbleClass =
    message.role === "user"
      ? "ml-auto bg-blue-600 text-white"
      : "mr-auto bg-zinc-100 text-zinc-900";
  return (
    <div
      className={`my-2 max-w-[80%] rounded-2xl px-4 py-2 ${bubbleClass}`}
      aria-live={isLive ? "polite" : undefined}
    >
      <div className="whitespace-pre-wrap">{text}</div>
      {isLive && message.status === "streaming" && (
        <span className="ml-1 inline-block h-3 w-1 animate-pulse bg-current align-middle" />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Implement MessageList**

Create `frontend/src/components/MessageList.tsx`:

```typescript
import type { Message } from "../api/types";
import { MessageItem } from "./MessageItem";

interface Props {
  messages: Message[];
  liveAssistantId: number | null;
  liveText: string;
}

export function MessageList({ messages, liveAssistantId, liveText }: Props) {
  return (
    <div className="flex flex-col px-4 py-2">
      {messages.map((m) => (
        <MessageItem
          key={m.id}
          message={m}
          isLive={m.id === liveAssistantId}
          liveText={m.id === liveAssistantId ? liveText : undefined}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Implement SendBox**

Create `frontend/src/components/SendBox.tsx`:

```typescript
import { useState, type KeyboardEvent } from "react";

interface Props {
  disabled: boolean;
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}

export function SendBox({ disabled, isStreaming, onSend, onStop }: Props) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setText("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="flex items-end gap-2 border-t border-zinc-200 p-3">
      <textarea
        className="flex-1 resize-none rounded border border-zinc-300 px-3 py-2 outline-none focus:border-blue-500"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        disabled={disabled && !isStreaming}
        placeholder="Type a message…"
      />
      {isStreaming ? (
        <button
          type="button"
          onClick={onStop}
          className="rounded bg-red-600 px-4 py-2 text-white hover:bg-red-700"
        >
          Stop
        </button>
      ) : (
        <button
          type="button"
          onClick={submit}
          disabled={disabled || !text.trim()}
          className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50 hover:bg-blue-700"
        >
          Send
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Implement ChatPage**

Create `frontend/src/pages/ChatPage.tsx`:

```typescript
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getSession } from "../api/sessions";
import { sendMessage } from "../api/messages";
import { MessageList } from "../components/MessageList";
import { SendBox } from "../components/SendBox";
import { useStreamingMessage } from "../hooks/useStreamingMessage";
import type { SessionDetail } from "../api/types";

export function ChatPage() {
  const { slug = "" } = useParams();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [liveAssistantId, setLiveAssistantId] = useState<number | null>(null);
  const stream = useStreamingMessage(liveAssistantId);

  useEffect(() => {
    if (!slug) return;
    getSession(slug).then(setSession);
  }, [slug]);

  // When the live stream completes, refetch the session so the message list
  // includes any tool_use/tool_result rows that landed during streaming.
  useEffect(() => {
    if (stream.phase === "complete" || stream.phase === "error") {
      getSession(slug).then((s) => {
        setSession(s);
        setLiveAssistantId(null);
      });
    }
  }, [stream.phase, slug]);

  const handleSend = async (text: string) => {
    if (!session) return;
    const result = await sendMessage(slug, text);
    // Optimistically refresh so the user message shows up immediately
    const refreshed = await getSession(slug);
    setSession(refreshed);
    setLiveAssistantId(result.assistant_message_id);
  };

  if (!session) {
    return <div className="p-4 text-zinc-500">Loading…</div>;
  }

  const isStreaming = stream.phase === "streaming";

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-zinc-200 px-4 py-2">
        <h1 className="text-lg font-semibold">{session.title || "Untitled"}</h1>
      </header>
      <main className="flex-1 overflow-y-auto">
        <MessageList
          messages={session.messages}
          liveAssistantId={liveAssistantId}
          liveText={stream.text}
        />
      </main>
      <SendBox
        disabled={false}
        isStreaming={isStreaming}
        onSend={handleSend}
        onStop={stream.cancel}
      />
    </div>
  );
}
```

- [ ] **Step 5: Implement ChatRedirectPage**

Create `frontend/src/pages/ChatRedirectPage.tsx`:

```typescript
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { createSession } from "../api/sessions";

export function ChatRedirectPage() {
  const navigate = useNavigate();

  useEffect(() => {
    createSession().then((s) => {
      navigate(`/chat/${s.slug}`, { replace: true });
    });
  }, [navigate]);

  return <div className="p-4 text-zinc-500">Starting a new chat…</div>;
}
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ frontend/src/pages/ChatPage.tsx frontend/src/pages/ChatRedirectPage.tsx
git commit -m "feat(frontend): add ChatPage with streaming-aware MessageList and SendBox"
```

---

## Task 12: Recent sessions sidebar and inline title edit

**Files:**
- Create: `frontend/src/components/RecentSessionsSidebar.tsx`
- Create: `frontend/src/components/InlineTitleEdit.tsx`
- Create: `frontend/src/hooks/useRecentSessions.ts`
- Modify: `frontend/src/pages/ChatPage.tsx` (mount the sidebar + title editor)

The recent-sessions sidebar shows the last 10 active sessions with click-to-navigate. Inline title editing on the chat header. New-chat button at the top of the sidebar.

- [ ] **Step 1: Implement useRecentSessions hook**

Create `frontend/src/hooks/useRecentSessions.ts`:

```typescript
import { useCallback, useEffect, useState } from "react";

import { listSessions } from "../api/sessions";
import type { Session } from "../api/types";

export function useRecentSessions(limit = 10) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    const data = await listSessions(limit, "active");
    setSessions(data);
    setLoading(false);
  }, [limit]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { sessions, loading, refresh };
}
```

- [ ] **Step 2: Implement RecentSessionsSidebar**

Create `frontend/src/components/RecentSessionsSidebar.tsx`:

```typescript
import { Link, useNavigate } from "react-router-dom";

import { createSession } from "../api/sessions";
import { useRecentSessions } from "../hooks/useRecentSessions";

interface Props {
  currentSlug: string | null;
}

export function RecentSessionsSidebar({ currentSlug }: Props) {
  const { sessions, refresh } = useRecentSessions(10);
  const navigate = useNavigate();

  const handleNew = async () => {
    const s = await createSession();
    await refresh();
    navigate(`/chat/${s.slug}`);
  };

  return (
    <aside className="flex w-64 flex-col border-r border-zinc-200 bg-zinc-50">
      <button
        type="button"
        onClick={handleNew}
        className="m-3 rounded bg-blue-600 px-3 py-2 text-white hover:bg-blue-700"
      >
        + New Chat
      </button>
      <nav className="flex-1 overflow-y-auto px-2">
        {sessions.length === 0 && (
          <div className="px-2 py-4 text-sm text-zinc-500">No chats yet.</div>
        )}
        {sessions.map((s) => {
          const isActive = s.slug === currentSlug;
          return (
            <Link
              key={s.slug}
              to={`/chat/${s.slug}`}
              className={`block rounded px-3 py-2 text-sm ${
                isActive
                  ? "bg-blue-100 text-blue-900"
                  : "text-zinc-700 hover:bg-zinc-200"
              }`}
            >
              <div className="truncate font-medium">
                {s.title || "Untitled"}
              </div>
              <div className="truncate text-xs text-zinc-500">
                {new Date(s.updated_at).toLocaleString()}
              </div>
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
```

- [ ] **Step 3: Implement InlineTitleEdit**

Create `frontend/src/components/InlineTitleEdit.tsx`:

```typescript
import { useState, type KeyboardEvent } from "react";

interface Props {
  value: string;
  onSave: (newTitle: string) => Promise<void>;
}

export function InlineTitleEdit({ value, onSave }: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  const start = () => {
    setDraft(value);
    setEditing(true);
  };

  const commit = async () => {
    if (draft !== value) {
      await onSave(draft);
    }
    setEditing(false);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      void commit();
    }
    if (e.key === "Escape") {
      setDraft(value);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <input
        autoFocus
        className="rounded border border-blue-500 px-2 py-1 text-lg font-semibold outline-none"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={onKeyDown}
      />
    );
  }
  return (
    <button
      type="button"
      onClick={start}
      className="rounded px-1 text-lg font-semibold hover:bg-zinc-100"
    >
      {value || "Untitled"}
    </button>
  );
}
```

- [ ] **Step 4: Update ChatPage to mount the sidebar and title editor**

Modify `frontend/src/pages/ChatPage.tsx`:

```typescript
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { getSession, updateSession } from "../api/sessions";
import { sendMessage } from "../api/messages";
import { InlineTitleEdit } from "../components/InlineTitleEdit";
import { MessageList } from "../components/MessageList";
import { RecentSessionsSidebar } from "../components/RecentSessionsSidebar";
import { SendBox } from "../components/SendBox";
import { useStreamingMessage } from "../hooks/useStreamingMessage";
import type { SessionDetail } from "../api/types";

export function ChatPage() {
  const { slug = "" } = useParams();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [liveAssistantId, setLiveAssistantId] = useState<number | null>(null);
  const stream = useStreamingMessage(liveAssistantId);

  useEffect(() => {
    if (!slug) return;
    getSession(slug).then(setSession);
  }, [slug]);

  useEffect(() => {
    if (stream.phase === "complete" || stream.phase === "error") {
      getSession(slug).then((s) => {
        setSession(s);
        setLiveAssistantId(null);
      });
    }
  }, [stream.phase, slug]);

  const handleSend = async (text: string) => {
    if (!session) return;
    const result = await sendMessage(slug, text);
    const refreshed = await getSession(slug);
    setSession(refreshed);
    setLiveAssistantId(result.assistant_message_id);
  };

  const handleTitleSave = async (newTitle: string) => {
    if (!session) return;
    const updated = await updateSession(slug, { title: newTitle });
    setSession({ ...session, title: updated.title });
  };

  if (!session) {
    return <div className="p-4 text-zinc-500">Loading…</div>;
  }

  const isStreaming = stream.phase === "streaming";

  return (
    <div className="flex h-screen">
      <RecentSessionsSidebar currentSlug={slug} />
      <div className="flex flex-1 flex-col">
        <header className="border-b border-zinc-200 px-4 py-2">
          <InlineTitleEdit value={session.title} onSave={handleTitleSave} />
        </header>
        <main className="flex-1 overflow-y-auto">
          <MessageList
            messages={session.messages}
            liveAssistantId={liveAssistantId}
            liveText={stream.text}
          />
        </main>
        <SendBox
          disabled={false}
          isStreaming={isStreaming}
          onSend={handleSend}
          onStop={stream.cancel}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Verify TS compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/RecentSessionsSidebar.tsx frontend/src/components/InlineTitleEdit.tsx frontend/src/hooks/useRecentSessions.ts frontend/src/pages/ChatPage.tsx
git commit -m "feat(frontend): add recent sessions sidebar and inline title editor"
```

---

## Task 13: AuthCliPage and CliAuthBanner

**Files:**
- Create: `frontend/src/pages/AuthCliPage.tsx`
- Create: `frontend/src/components/CliAuthBanner.tsx`
- Create: `frontend/src/hooks/useCliAuthStatus.ts`

The PTY auth UI: a "Connect Claude" button that calls `/api/auth/cli/start`, displays the returned auth URL, accepts the pasted code, and shows the result. The banner appears at the top of any chat page when the CLI is not authenticated.

- [ ] **Step 1: Implement useCliAuthStatus**

Create `frontend/src/hooks/useCliAuthStatus.ts`:

```typescript
import { useEffect, useState } from "react";

import { cliAuthStatus } from "../api/auth";

export function useCliAuthStatus(pollIntervalMs = 30000) {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    const tick = async () => {
      try {
        const result = await cliAuthStatus();
        if (!cancelled) setAuthenticated(result.authenticated);
      } catch {
        if (!cancelled) setAuthenticated(false);
      }
    };
    tick();
    const id = setInterval(tick, pollIntervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [pollIntervalMs]);

  return authenticated;
}
```

- [ ] **Step 2: Implement CliAuthBanner**

Create `frontend/src/components/CliAuthBanner.tsx`:

```typescript
import { Link } from "react-router-dom";

import { useCliAuthStatus } from "../hooks/useCliAuthStatus";

export function CliAuthBanner() {
  const authenticated = useCliAuthStatus();
  if (authenticated !== false) return null;
  return (
    <div className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-900">
      Claude CLI is not connected.{" "}
      <Link to="/auth/cli" className="font-semibold underline">
        Connect now →
      </Link>
    </div>
  );
}
```

- [ ] **Step 3: Implement AuthCliPage**

Create `frontend/src/pages/AuthCliPage.tsx`:

```typescript
import { useState } from "react";

import {
  cliAuthCancel,
  cliAuthComplete,
  cliAuthStart,
  cliAuthStatus,
} from "../api/auth";

type Phase = "idle" | "awaiting_code" | "submitting" | "complete" | "error";

export function AuthCliPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [authUrl, setAuthUrl] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setError(null);
    setPhase("idle");
    try {
      const r = await cliAuthStart();
      if (r.status === "complete") {
        setPhase("complete");
      } else {
        setPhase("awaiting_code");
        setAuthUrl(r.auth_url);
      }
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  };

  const submit = async () => {
    setPhase("submitting");
    setError(null);
    try {
      await cliAuthComplete(code);
      setPhase("complete");
      // refresh status to make sure the banner clears
      await cliAuthStatus();
    } catch (e) {
      setError(String(e));
      setPhase("error");
    }
  };

  const cancel = async () => {
    await cliAuthCancel();
    setPhase("idle");
    setAuthUrl(null);
    setCode("");
  };

  return (
    <div className="mx-auto max-w-2xl p-6">
      <h1 className="mb-4 text-2xl font-semibold">Connect Claude CLI</h1>
      <p className="mb-4 text-zinc-600">
        ace-web uses your team's Claude subscription via the local CLI. To
        authorize this server, generate an OAuth token using the flow below.
      </p>

      {phase === "idle" && (
        <button
          type="button"
          onClick={start}
          className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
        >
          Begin authorization
        </button>
      )}

      {phase === "awaiting_code" && authUrl && (
        <div className="space-y-4">
          <div className="rounded border border-zinc-200 bg-zinc-50 p-4">
            <p className="mb-2 text-sm text-zinc-700">
              1. Open this URL in a browser logged into your Claude account:
            </p>
            <a
              href={authUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all font-mono text-sm text-blue-600 underline"
            >
              {authUrl}
            </a>
          </div>
          <div>
            <p className="mb-2 text-sm text-zinc-700">
              2. Paste the resulting code here:
            </p>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className="w-full rounded border border-zinc-300 px-3 py-2 font-mono"
              placeholder="paste-code-here"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={submit}
              disabled={!code.trim()}
              className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50 hover:bg-blue-700"
            >
              Submit code
            </button>
            <button
              type="button"
              onClick={cancel}
              className="rounded border border-zinc-300 px-4 py-2 text-zinc-700 hover:bg-zinc-100"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {phase === "submitting" && (
        <div className="text-zinc-500">Submitting code…</div>
      )}

      {phase === "complete" && (
        <div className="rounded border border-green-300 bg-green-50 p-4 text-green-900">
          ✅ Claude CLI is now connected. You can return to{" "}
          <a href="/chat" className="font-semibold underline">
            the chat page
          </a>
          .
        </div>
      )}

      {phase === "error" && (
        <div className="rounded border border-red-300 bg-red-50 p-4 text-red-900">
          <div className="font-semibold">Authorization failed</div>
          <div className="text-sm">{error}</div>
          <button
            type="button"
            onClick={() => setPhase("idle")}
            className="mt-2 rounded border border-red-300 px-3 py-1 text-sm hover:bg-red-100"
          >
            Try again
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Mount the banner in ChatPage**

Modify `frontend/src/pages/ChatPage.tsx`. Add the import and mount the banner above the header:

```typescript
import { CliAuthBanner } from "../components/CliAuthBanner";

// inside the return, replace the inner div structure:
return (
  <div className="flex h-screen">
    <RecentSessionsSidebar currentSlug={slug} />
    <div className="flex flex-1 flex-col">
      <CliAuthBanner />
      <header className="border-b border-zinc-200 px-4 py-2">
        <InlineTitleEdit value={session.title} onSave={handleTitleSave} />
      </header>
      <main className="flex-1 overflow-y-auto">
        <MessageList
          messages={session.messages}
          liveAssistantId={liveAssistantId}
          liveText={stream.text}
        />
      </main>
      <SendBox
        disabled={false}
        isStreaming={isStreaming}
        onSend={handleSend}
        onStop={stream.cancel}
      />
    </div>
  </div>
);
```

- [ ] **Step 5: Verify TS compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/AuthCliPage.tsx frontend/src/components/CliAuthBanner.tsx frontend/src/hooks/useCliAuthStatus.ts frontend/src/pages/ChatPage.tsx
git commit -m "feat(frontend): add CLI auth page and connection banner"
```

---

## Task 14: Router updates

**Files:**
- Modify: `frontend/src/router.tsx`

Wire `/chat`, `/chat/:slug`, and `/auth/cli` into the router.

- [ ] **Step 1: Read the existing router**

Open `frontend/src/router.tsx`. Note the existing route shape so the new routes match.

- [ ] **Step 2: Add the new routes**

Modify `frontend/src/router.tsx`. Add the three new routes alongside the existing ones:

```typescript
import { createBrowserRouter } from "react-router-dom";

import { App } from "./App";
import { HealthPage } from "./pages/HealthPage";
import { HomePage } from "./pages/HomePage";
import { ChatPage } from "./pages/ChatPage";
import { ChatRedirectPage } from "./pages/ChatRedirectPage";
import { AuthCliPage } from "./pages/AuthCliPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <HomePage /> },
      { path: "health", element: <HealthPage /> },
      { path: "chat", element: <ChatRedirectPage /> },
      { path: "chat/:slug", element: <ChatPage /> },
      { path: "auth/cli", element: <AuthCliPage /> },
    ],
  },
]);
```

If the existing `App` component renders an `<Outlet />` already, the children pattern works as-is. If it doesn't, restructure to a flat route list. Inspect first.

- [ ] **Step 3: Build the frontend bundle to check for errors**

Run: `cd frontend && npm run build`
Expected: build completes without errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router.tsx
git commit -m "feat(frontend): wire /chat, /chat/:slug, /auth/cli routes"
```

---

## Task 15: Filestore mount, docker-compose volume, entrypoint symlink

**Files:**
- Modify: `entrypoint.sh`
- Modify: `docker-compose.yml`
- Modify: `cloudbuild.yaml`
- Modify: `config/settings/base.py`
- Modify: `docs/deploy.md`

Persistent storage for the OAuth token (`/var/lib/ace-claude/oauth-token`) and the CLI's `~/.claude` session store. Cloud Run uses Filestore (NFS) mounted at `/var/lib/ace-claude`. Local dev uses a named Docker volume. The entrypoint symlinks `~/.claude` to a subdirectory of the mount.

- [ ] **Step 1: Add settings**

Modify `config/settings/base.py`. Add near the bottom (after the existing settings):

```python
# --- Claude CLI integration (Phase 2) ---
ACE_CLAUDE_HOME = env(
    "ACE_CLAUDE_HOME",
    default=str(BASE_DIR / ".ace-claude-home"),
)
ACE_CLAUDE_TOKEN_FILE = env(
    "ACE_CLAUDE_TOKEN_FILE",
    default=str(BASE_DIR / ".ace-claude-home" / "oauth-token"),
)
```

- [ ] **Step 2: Update entrypoint.sh**

Modify `entrypoint.sh`. Add lines (after the existing migration step) to ensure the mount directory exists, create a symlink from `~/.claude` to `/var/lib/ace-claude/.claude`, and set HOME so the CLI sees the symlink:

```bash
#!/bin/sh
set -e

# Ensure the persistent CLI state directory exists
ACE_CLAUDE_DIR="${ACE_CLAUDE_HOME:-/var/lib/ace-claude}"
mkdir -p "$ACE_CLAUDE_DIR/.claude"

# Symlink ~/.claude into the persistent directory so the CLI's session store
# survives container restarts.
if [ ! -L "$HOME/.claude" ]; then
  rm -rf "$HOME/.claude" 2>/dev/null || true
  ln -s "$ACE_CLAUDE_DIR/.claude" "$HOME/.claude"
fi

# Existing Phase 1 logic
python manage.py migrate --noinput
python manage.py collectstatic --noinput

if [ "${DJANGO_DEBUG}" = "True" ]; then
  exec uvicorn config.asgi:application --host 0.0.0.0 --port 8080 --reload
else
  exec uvicorn config.asgi:application --host 0.0.0.0 --port 8080
fi
```

(The exact existing entrypoint.sh body should be preserved — just add the `mkdir -p` and symlink lines near the top, and make sure the `HOME` variable is set in production.)

- [ ] **Step 3: Update docker-compose.yml**

Modify `docker-compose.yml`. Add a named volume and mount it on the `app` service:

```yaml
services:
  db:
    # ... unchanged ...

  app:
    build: .
    environment:
      DJANGO_SETTINGS_MODULE: config.settings.development
      DJANGO_DEBUG: "True"
      DJANGO_SECRET_KEY: dev-insecure
      DATABASE_URL: postgres://ace:ace@db:5432/ace_web
      ACE_IAP_REQUIRED: "False"
      ACE_CLAUDE_HOME: /var/lib/ace-claude
      ACE_CLAUDE_TOKEN_FILE: /var/lib/ace-claude/oauth-token
      HOME: /root
    ports:
      - "8000:8080"
    volumes:
      - ./apps:/app/apps
      - ./config:/app/config
      - ./manage.py:/app/manage.py
      - ace-claude-data:/var/lib/ace-claude
    depends_on:
      db:
        condition: service_healthy

volumes:
  ace-pg-data:
  ace-claude-data:
```

- [ ] **Step 4: Update cloudbuild.yaml**

Modify `cloudbuild.yaml`. Add the Filestore mount to the Cloud Run deploy step. Filestore on Cloud Run is configured via `--add-volume` and `--add-volume-mount`:

```yaml
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    entrypoint: gcloud
    args:
      - run
      - deploy
      - ${_SERVICE_NAME}
      - --image=us-central1-docker.pkg.dev/$PROJECT_ID/ace-web/app:$BUILD_ID
      - --region=${_REGION}
      - --platform=managed
      - --add-cloudsql-instances=$PROJECT_ID:us-central1:ace-web-db
      - --set-env-vars=DJANGO_SETTINGS_MODULE=config.settings.production
      - --set-env-vars=DJANGO_ALLOWED_HOSTS=${_ALLOWED_HOSTS}
      - --set-env-vars=CLOUD_SQL_CONNECTION_NAME=$PROJECT_ID:us-central1:ace-web-db
      - --set-env-vars=ACE_IAP_REQUIRED=True
      - --set-env-vars=ACE_CLAUDE_HOME=/var/lib/ace-claude
      - --set-env-vars=ACE_CLAUDE_TOKEN_FILE=/var/lib/ace-claude/oauth-token
      - --set-env-vars=HOME=/root
      - --set-secrets=DJANGO_SECRET_KEY=ace-web-django-secret:latest
      - --set-secrets=DATABASE_URL=ace-web-database-url:latest
      - --add-volume=name=ace-claude-data,type=nfs,location=${_FILESTORE_IP}:/${_FILESTORE_SHARE}
      - --add-volume-mount=volume=ace-claude-data,mount-path=/var/lib/ace-claude
      - --min-instances=1
      - --max-instances=1
      - --memory=1Gi
      - --cpu=1
      - --no-allow-unauthenticated
      - --vpc-connector=${_VPC_CONNECTOR}
      - --vpc-egress=private-ranges-only

substitutions:
  _SERVICE_NAME: ace-web
  _REGION: us-central1
  _ALLOWED_HOSTS: ace-web-hhhi4yut3q-uc.a.run.app
  _FILESTORE_IP: 10.0.0.2          # Set after Filestore is provisioned
  _FILESTORE_SHARE: ace_claude     # The NFS share name
  _VPC_CONNECTOR: ace-web-connector  # VPC connector name

options:
  logging: CLOUD_LOGGING_ONLY
```

- [ ] **Step 5: Update docs/deploy.md**

Modify `docs/deploy.md`. Add a new section after the existing setup steps:

```markdown
## Filestore (persistent CLI state)

ace-web mounts a Filestore (NFS) volume at `/var/lib/ace-claude` on Cloud Run
to persist the OAuth token and the Claude CLI's `~/.claude` session store
across instance restarts. Without it, every cold start would require the
CLIBackend to fall back to its Django-replay path.

### One-time provisioning

```bash
# Create a VPC network if you don't have one
gcloud compute networks create ace-web --subnet-mode=auto

# Allocate a Filestore instance (~$25/mo minimum)
gcloud filestore instances create ace-web-claude \
  --region=us-central1 \
  --tier=BASIC_HDD \
  --file-share=name=ace_claude,capacity=1024 \
  --network=name=ace-web

# Note the IP address — you need it in cloudbuild.yaml
gcloud filestore instances describe ace-web-claude --region=us-central1 \
  --format='value(networks.ipAddresses[0])'

# Create the VPC connector that Cloud Run uses to reach Filestore
gcloud compute networks vpc-access connectors create ace-web-connector \
  --region=us-central1 \
  --network=ace-web \
  --range=10.8.0.0/28
```

Then update `cloudbuild.yaml` substitutions `_FILESTORE_IP`, `_FILESTORE_SHARE`,
and `_VPC_CONNECTOR` to match.

### Why Filestore (and not GCS Fuse)

Filestore gives the CLI POSIX semantics that the Claude CLI's session store
relies on. GCS Fuse is cheaper but its sync and locking semantics are not
guaranteed to match a real POSIX filesystem, and the CLI was not designed
against it.

If Filestore cost is a problem, the CLIBackend's hybrid resume strategy is
the safety net — drop the Filestore mount, accept that every cold start
rehydrates from Django history, and document the trade-off.
```

- [ ] **Step 6: Build and run docker-compose locally to verify**

Run: `docker compose down -v && docker compose up --build`
Expected: app starts, no errors. The new volume `ace-claude-data` is created. The entrypoint creates `/var/lib/ace-claude/.claude` and symlinks it.

Tear down: `docker compose down`

- [ ] **Step 7: Commit**

```bash
git add config/settings/base.py entrypoint.sh docker-compose.yml cloudbuild.yaml docs/deploy.md
git commit -m "chore(deploy): add Filestore mount and CLI state persistence"
```

---

## Task 16: Documentation pass

**Files:**
- Create: `docs/learnings/sse-django-async.md`
- Create: `docs/learnings/cli-stream-json-format.md`
- Modify: `CLAUDE.md` (Phase 2 status, learnings index)

Capture two non-obvious things this phase introduces, and update the agent context.

- [ ] **Step 1: Capture a real stream-json sample**

If a real Claude CLI is available locally, run:

```bash
echo "What is 2+2?" | claude -p --output-format stream-json > /tmp/sample.txt
```

Open `/tmp/sample.txt` and review the actual event shapes. Compare against the fixtures in `apps/common/tests/fixtures/stream_json_*.txt`. If the real format differs in any field, update the fixtures AND `apps/common/cli_event_parser.py` to match. Re-run `pytest apps/common/tests/test_cli_event_parser.py` to verify.

- [ ] **Step 2: Document the stream-json format**

Create `docs/learnings/cli-stream-json-format.md`:

```markdown
# Learning: Claude CLI stream-json output format

**Date**: 2026-04-08
**Context**: Phase 2 CLIBackend parses `claude -p --output-format stream-json` output. The format is an external dependency we should pin via fixtures.
**Status**: Active

## Problem

The Claude Code CLI's `stream-json` output format is JSON-Lines but the event shapes are not formally documented. ace-web's `apps/common/cli_event_parser.py` parses these events into `StreamEvent` records; if the CLI changes its event shapes, the parser breaks and we get garbled chat.

## Root Cause

External dependency on a CLI output format that has no stability contract.

## Fix / Key Takeaway

Capture real CLI output as fixtures and commit them. The fixtures live at `apps/common/tests/fixtures/stream_json_*.txt`. The parser tests run against these fixtures, so any format drift surfaces as a test failure.

Event shapes captured at the time Phase 2 shipped:

- `{"type": "system", "subtype": "init", "session_id": "<id>", ...}` — first event of every fresh session, contains the new CLI session id
- `{"type": "assistant", "message": {"content": [{"type": "text", "text": "..."}]}}` — assistant text deltas (one event per chunk)
- `{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "...", "name": "...", "input": {...}}]}}` — tool use blocks
- `{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "...", "content": "..."}]}}` — tool result blocks
- `{"type": "result", "subtype": "success", ...}` — terminal "done" event
- `{"type": "result", "subtype": "error_max_turns", ...}` — terminal error variant

If you upgrade the Claude CLI and tests start failing, recapture fixtures and update the parser.
```

- [ ] **Step 3: Document SSE-in-Django-async gotchas**

Create `docs/learnings/sse-django-async.md`:

```markdown
# Learning: SSE in Django async views

**Date**: 2026-04-08
**Context**: Phase 2 implements `GET /api/messages/<id>/stream` as a Django async view returning `StreamingHttpResponse` with `text/event-stream`. There are several non-obvious gotchas.
**Status**: Active

## Problem

Streaming responses from Django async views to a browser via SSE has several layers that can buffer or break the stream.

## Root Cause

ASGI server defaults, proxy buffering, and HTTP middleware can all buffer or close streaming responses.

## Fix / Key Takeaway

For SSE to work end-to-end:

1. **Set `Cache-Control: no-cache` and `X-Accel-Buffering: no` on the response.** These tell intermediate proxies (Cloud Run's edge, nginx if you ever add one) not to buffer chunks.
2. **The middleware must allow streaming.** `IAPHeaderAuthMiddleware` does, because it's a thin wrapper around `get_response(request)`. Be careful adding any middleware that wraps the response body.
3. **uvicorn streams chunks immediately** by default. If you ever switch to gunicorn-with-workers, the answer changes.
4. **Use `sync_to_async` for ALL ORM access** inside the async view. A bare `Message.objects.get(...)` raises `SynchronousOnlyOperation`.
5. **Handle `asyncio.CancelledError` in the streaming generator.** It fires when the client disconnects. Catch it, mark the message as `error` with `cancelled` detail, and re-raise so Django can clean up.
6. **Browser EventSource auto-reconnects on connection loss.** The reconnect semantics in `apps/sessions/streaming.py` (replay current `plaintext` on reconnect) handle this gracefully.
7. **Never write a single SSE frame larger than the kernel TCP buffer.** Token-by-token deltas are small, so this is fine; just be aware if you start sending large tool_result blocks.
```

- [ ] **Step 4: Update CLAUDE.md**

Modify `CLAUDE.md`. Update the Phase 2 row to mark it complete (after the final task lands), and add the two new learnings to the learnings index.

In the status table, change Phase 2's status from `**Next**` to `**Done**` (do this in the final commit of the phase, not now). For now, just add the two new learnings:

Find the "API conventions" section in the learnings index. Add two new sections above or below as appropriate:

```markdown
Conversation engine:
- [cli-stream-json-format](docs/learnings/cli-stream-json-format.md) — Claude CLI stream-json event shapes captured as fixtures; recapture if the CLI is upgraded.
- [sse-django-async](docs/learnings/sse-django-async.md) — `Cache-Control`/`X-Accel-Buffering` headers and `sync_to_async` ORM access are mandatory for SSE views to work end-to-end.
```

- [ ] **Step 5: Commit**

```bash
git add docs/learnings/cli-stream-json-format.md docs/learnings/sse-django-async.md CLAUDE.md
git commit -m "docs: add Phase 2 learnings and update CLAUDE.md index"
```

---

## Self-review (engineer running this plan should also do this)

Before declaring Phase 2 done, verify:

- [ ] `pytest -v` passes locally with all tests green
- [ ] `cd frontend && npm run build` completes without errors
- [ ] `docker compose up --build` starts the stack cleanly; `curl localhost:8000/api/health` returns ok
- [ ] In a browser at `http://localhost:8000/`, navigate to `/auth/cli`, click "Begin authorization", complete the flow, see the success state
- [ ] Navigate to `/chat`, get redirected to `/chat/<slug>`, type "hello", watch tokens stream in
- [ ] Mid-stream, click "Stop". The message ends in `error` status with `cancelled` detail
- [ ] Refresh the page; the partial assistant message is preserved in the message list
- [ ] Send another message; verify the new turn streams independently
- [ ] Edit the title via the inline editor; verify it persists across page reloads
- [ ] Send a question that uses tools (e.g., "what's in /etc/hosts" if local) and verify tool_use/tool_result blocks render as collapsed sections
- [ ] Open a second tab to the same `/chat/<slug>`; the second tab should show the existing messages but is NOT expected to receive live streaming events (that's Phase 3)
- [ ] Visit `/api/sessions` (after auth) and verify the JSON envelope shape `{data: [...], error: null}`
- [ ] Cloud Run deploy: `gcloud builds submit --config=cloudbuild.yaml`. After deploy, navigate to `${URL}/auth/cli`, complete auth, then `/chat`, send a message, verify streaming works behind IAP.
- [ ] No `TODO` / `FIXME` strings in any committed file (`grep -r "TODO\|FIXME"`)

If any of these fail, fix before declaring Phase 2 done.

---

## What ships at the end of Phase 2

- A working single-user chat experience: create a session, send a message, watch streaming tokens with tool use blocks, navigate back later, edit titles, stop in-flight responses
- ChatBackend abstraction with the only implementation (CLIBackend) wrapping `claude -p --output-format stream-json` with hybrid resume + circuit breaker + cancellation
- Self-service in-app CLI authentication via PTY-based `claude setup-token`
- SSE streaming pipeline with reconnect semantics and tool-block fan-out
- Auto-titling of new sessions
- Recent sessions sidebar
- Filestore mount for persistent `~/.claude` and OAuth token storage on Cloud Run
- Two new learnings documenting the externals (`stream-json` event format) and the Django gotchas (SSE async views)

## What does NOT ship in Phase 2 (deferred to later phases)

- WebSocket consumer, channels-redis, ASGI IAP middleware → **Phase 3**
- Drafts model, multi-player composition → **Phase 3**
- Presence indicators → **Phase 3**
- Session list page (search, filter, archive UI) → **Phase 4**
- Share tokens (public read-only links) → **Phase 4**
- `ace upload` CLI and ingest UI → **Phase 4**
- Observability, eval harness, accessibility audit, security review → **Phase 5**
- API key backend, MCP backend → **never** (out of scope per spec §7)

---

## References

- Design spec: `docs/specs/2026-04-08-ace-web-design.md` (read sections 4.1, 4.2, 5.2, 5.3, 5.4)
- Phase 1 plan + post-execution corrections: `docs/plans/2026-04-07-1a-foundation.md`
- canopy-web pattern source: `../canopy-web/apps/common/anthropic_client.py`, `../canopy-web/apps/common/auth_flow.py`
- Existing learnings to respect: `docs/learnings/api-envelope-convention.md`, `docs/learnings/channels-single-instance.md`, `docs/learnings/iap-websocket-coverage.md`, `docs/learnings/user-google-sub-nullable.md`
