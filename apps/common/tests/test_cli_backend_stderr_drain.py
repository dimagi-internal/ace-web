"""Tests for the stderr-drain + heartbeat helpers added to CLIBackend.

Direct unit tests on the helpers (rather than full subprocess integration)
because mocking asyncio.subprocess.Process for stderr deadlock simulation
is fragile and the helpers are small enough to test in isolation.
"""
from collections import deque
from unittest.mock import MagicMock

import pytest

from apps.common import cli_backend


class _FakeStderr:
    """Minimal stand-in for proc.stderr — yields a fixed list of bytes lines, then EOF."""

    def __init__(self, lines: list[bytes]):
        self._lines = list(lines) + [b""]  # b"" is real-StreamReader EOF

    async def readline(self) -> bytes:
        return self._lines.pop(0)


@pytest.mark.asyncio
async def test_drain_stderr_into_accumulates_and_logs_each_line(caplog):
    proc = MagicMock()
    proc.stderr = _FakeStderr([b"first warning\n", b"second warning\n"])
    buf: deque[str] = deque(maxlen=10)

    with caplog.at_level("WARNING", logger="apps.common.cli_backend"):
        await cli_backend._drain_stderr_into(proc, buf, "test-slug")

    assert list(buf) == ["first warning", "second warning"]
    messages = [r.getMessage() for r in caplog.records]
    assert any("first warning" in m for m in messages)
    assert any("second warning" in m for m in messages)
    # Session slug appears in every line for grep-ability.
    assert all("test-slug" in m for m in messages if "stderr" in m)


@pytest.mark.asyncio
async def test_drain_stderr_into_stops_on_eof():
    proc = MagicMock()
    proc.stderr = _FakeStderr([b"only line\n"])
    buf: deque[str] = deque(maxlen=10)
    await cli_backend._drain_stderr_into(proc, buf, "x")
    assert list(buf) == ["only line"]


@pytest.mark.asyncio
async def test_drain_stderr_handles_no_stderr_attribute():
    """If proc.stderr is None (e.g. PIPE wasn't requested), no-op cleanly."""
    proc = MagicMock()
    proc.stderr = None
    buf: deque[str] = deque(maxlen=10)
    await cli_backend._drain_stderr_into(proc, buf, "x")
    assert list(buf) == []


@pytest.mark.asyncio
async def test_drain_stderr_skips_blank_lines():
    proc = MagicMock()
    proc.stderr = _FakeStderr([b"\n", b"real\n", b"\n"])
    buf: deque[str] = deque(maxlen=10)
    await cli_backend._drain_stderr_into(proc, buf, "x")
    assert list(buf) == ["real"]


def test_proc_stderr_tail_returns_joined_buffer():
    proc = MagicMock()
    proc._ace_stderr_buf = deque(["line1", "line2", "line3"])
    out = cli_backend._proc_stderr_tail(proc, char_limit=2000)
    assert out == "line1\nline2\nline3"


def test_proc_stderr_tail_clips_to_char_limit():
    proc = MagicMock()
    long_line = "x" * 100
    proc._ace_stderr_buf = deque([long_line, long_line, long_line])
    out = cli_backend._proc_stderr_tail(proc, char_limit=50)
    assert len(out) == 50
    # The clip keeps the END of the buffer (most recent stderr).
    assert out.endswith("x")


def test_proc_stderr_tail_empty_buf_returns_empty_string():
    proc = MagicMock()
    proc._ace_stderr_buf = deque()
    assert cli_backend._proc_stderr_tail(proc) == ""


def test_proc_stderr_tail_missing_attribute_returns_empty_string():
    """Defensive — if cleanup ran early or _spawn never set the attr."""
    proc = MagicMock(spec=[])  # no attributes
    assert cli_backend._proc_stderr_tail(proc) == ""


@pytest.mark.asyncio
async def test_heartbeat_exits_when_returncode_set(monkeypatch):
    """Heartbeat task must terminate naturally once the subprocess exits."""
    # Stub sleep so the test doesn't block for 30s.
    sleeps = []

    async def _fast_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(cli_backend.asyncio, "sleep", _fast_sleep)

    proc = MagicMock()
    proc.returncode = None
    proc._ace_started_at = 0.0
    proc._ace_stderr_buf = deque()
    proc.pid = 999

    # First wakeup: still running. Second: exited. Heartbeat should return.
    state = {"calls": 0}
    real_sleep = cli_backend.asyncio.sleep

    async def _trigger_exit_after_first_wakeup(seconds):
        sleeps.append(seconds)
        state["calls"] += 1
        if state["calls"] == 2:
            proc.returncode = 0
        await real_sleep(0)  # yield

    monkeypatch.setattr(cli_backend.asyncio, "sleep", _trigger_exit_after_first_wakeup)

    await cli_backend._heartbeat(proc, "test-slug")
    # Should have slept at least twice — one to log, one to detect exit.
    assert state["calls"] >= 2
