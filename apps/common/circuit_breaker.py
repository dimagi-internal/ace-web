"""Per-process circuit breaker for failing-fast on repeated downstream errors.

Used by CLIBackend to avoid hammering a broken `claude` subprocess (auth
expired, binary missing, network down, etc.) on every chat turn.
"""
from __future__ import annotations

import threading
import time


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

    After a half-open probe, the caller is responsible for recording
    `record_success()` or `record_failure()` to reflect the probe's outcome;
    otherwise the breaker stays in the reset state as if nothing happened.
    """

    def __init__(self, *, threshold: int, cooldown_seconds: float):
        self._threshold = threshold
        self._cooldown = cooldown_seconds
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def check(self) -> None:
        """Raise CircuitOpenError if the breaker is open (atomic, single lock acquisition)."""
        with self._lock:
            if self._opened_at is None:
                return
            if time.monotonic() - self._opened_at >= self._cooldown:
                # Cooldown elapsed — half-open: allow the next call through
                self._opened_at = None
                self._consecutive_failures = 0
                return
            raise CircuitOpenError("Circuit breaker is open")

    def is_open(self) -> bool:
        """Return True if the breaker is currently rejecting calls."""
        try:
            self.check()
            return False
        except CircuitOpenError:
            return True

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold:
                self._opened_at = time.monotonic()
