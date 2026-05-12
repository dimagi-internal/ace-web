"""Redis-backed async job store for long-running mobile operations.

Why this exists. ``mobile_run_recipe`` invokes Maestro on the cloud EC2
runner via SSM and can take 60–300 s for a typical recipe. The AWS ALB
in front of the Fargate task has a 60 s default idle timeout, so a
synchronous POST that takes longer than ~50 s reliably dies as
``fetch failed`` on the client and leaks the singleton lock until its
TTL expires (30 min). Caught in vivo by the leep Phase 5 run on
2026-05-12 — five consecutive attempts each leaked one lock.

The fix is a classic 202-async pattern:

1. ``POST /api/mobile/run-recipe`` validates, acquires the singleton
   lock, kicks off the actual work in a Python thread, persists a job
   record, and returns ``202 {job_id}`` immediately. The connection
   closes well within the ALB idle window.
2. The background thread runs ``controller.run_recipe`` against SSM,
   writes the result envelope to Redis under
   ``mobile:job:<job_id>``, and releases the singleton lock.
3. Client polls ``GET /api/mobile/jobs/<job_id>`` every few seconds.
   ``200 {status: 'running'}`` while the worker is still going,
   ``200 {status: 'completed', result: ...}`` when done, or
   ``200 {status: 'failed', error: ...}``.

Job records live in Redis with a 1-hour TTL — long enough that a slow
operator can re-poll after a coffee break, short enough that finished
jobs don't accumulate indefinitely. The singleton lock is the sole
arbiter of "is the runner busy"; this module just stores the job
result for the polling endpoint to read.

Thread safety: each request handler spawns a separate Python thread.
The singleton lock prevents two recipe jobs from running concurrently
on the same EC2 instance — so even though Python threads share state,
the controller calls are serialized at the AWS layer.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import redis as _redis_sync
from django.conf import settings

JOB_KEY_PREFIX = "mobile:job:"
JOB_TTL_SECONDS = 3600  # 1 hour — long enough for re-poll after operator break

_sync_redis: _redis_sync.Redis | None = None


def _get_redis() -> _redis_sync.Redis:
    """Return a cached sync Redis client. Tests monkeypatch this."""
    global _sync_redis
    if _sync_redis is None:
        _sync_redis = _redis_sync.from_url(
            settings.ACE_REDIS_URL, decode_responses=True
        )
    return _sync_redis


@dataclass
class JobRecord:
    """Server-side state of an async mobile job.

    ``status`` is the operator-visible state. ``result`` is populated on
    completion (the same envelope the sync endpoint used to return).
    ``error`` is populated on failure with the human-readable message
    and the typed MobileError code if any. ``started_at`` lets the
    poller compute elapsed time for UX ("running for 47s…").
    """

    job_id: str
    operation: str  # 'run_recipe' — leaves room for future async ops
    status: str  # 'running' | 'completed' | 'failed'
    owner: str  # singleton-lock owner string (for debugging concurrency)
    started_at: str
    completed_at: str | None = None
    result: Any = None
    error: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "job_id": self.job_id,
            "operation": self.operation,
            "status": self.status,
            "owner": self.owner,
            "started_at": self.started_at,
        }
        if self.completed_at is not None:
            d["completed_at"] = self.completed_at
        if self.result is not None:
            d["result"] = self.result
        if self.error is not None:
            d["error"] = self.error
            if self.error_code:
                d["error_code"] = self.error_code
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> JobRecord:
        return cls(
            job_id=d["job_id"],
            operation=d["operation"],
            status=d["status"],
            owner=d["owner"],
            started_at=d["started_at"],
            completed_at=d.get("completed_at"),
            result=d.get("result"),
            error=d.get("error"),
            error_code=d.get("error_code"),
        )


def make_job_id() -> str:
    """A 16-hex-char job id. Random enough that collisions inside the
    1h TTL window are astronomically unlikely; short enough to fit
    cleanly in a URL."""
    return secrets.token_hex(8)


def _key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def write(job: JobRecord) -> None:
    """Persist (or overwrite) a job record. Always refreshes the TTL so
    a long-running job's record can't expire mid-execution."""
    r = _get_redis()
    r.set(_key(job.job_id), json.dumps(job.to_dict()), ex=JOB_TTL_SECONDS)


def read(job_id: str) -> JobRecord | None:
    """Look up a job by id. Returns None if missing or expired."""
    r = _get_redis()
    raw = r.get(_key(job_id))
    if not raw:
        return None
    return JobRecord.from_dict(json.loads(raw))


def _iso_now() -> str:
    return datetime.now(tz=UTC).isoformat()


def submit(
    *,
    operation: str,
    owner: str,
    worker: callable,  # type: ignore[valid-type]
) -> JobRecord:
    """Persist an initial 'running' job record and spawn the worker
    thread. The worker MUST be a callable taking no arguments — caller
    closes over whatever state it needs.

    The worker is responsible for catching its own exceptions and
    calling ``mark_completed`` or ``mark_failed`` accordingly. Lock
    release MUST also live in the worker (typically in a try/finally
    around the actual work) — this module deliberately does not release
    the lock, because that's the caller's domain-specific concern.

    Returns the initial JobRecord so the view can echo back the
    ``job_id`` to the client.
    """
    job = JobRecord(
        job_id=make_job_id(),
        operation=operation,
        status="running",
        owner=owner,
        started_at=_iso_now(),
    )
    write(job)
    # daemon=True so the thread doesn't keep the worker process alive
    # past container shutdown — the singleton lock TTL will eventually
    # free up downstream state if a container is killed mid-job.
    t = threading.Thread(target=worker, name=f"mobile-job-{job.job_id}", daemon=True)
    t.start()
    return job


def mark_completed(job_id: str, result: Any) -> None:
    """Mark a job complete and store its result envelope. Idempotent.

    If the job record has expired (operator polled after >1h), we
    re-create it as a completed record with the same id so the final
    poll can still see the result rather than a 404 — operator gets
    closure even on a slow re-poll.
    """
    existing = read(job_id)
    if existing is None:
        existing = JobRecord(
            job_id=job_id,
            operation="run_recipe",
            status="completed",
            owner="(expired)",
            started_at=_iso_now(),
        )
    existing.status = "completed"
    existing.completed_at = _iso_now()
    existing.result = result
    existing.error = None
    existing.error_code = None
    write(existing)


def mark_failed(
    job_id: str,
    *,
    error: str,
    error_code: str | None = None,
    include_traceback: bool = False,
) -> None:
    """Mark a job failed and store the error message. Idempotent.

    ``include_traceback=True`` appends ``sys.exc_info()``'s traceback
    to the error field. Only set when called from inside an ``except``
    block. Tracebacks help diagnose unexpected exceptions (the typed
    MobileError messages are already operator-actionable on their own).
    """
    existing = read(job_id)
    if existing is None:
        existing = JobRecord(
            job_id=job_id,
            operation="run_recipe",
            status="failed",
            owner="(expired)",
            started_at=_iso_now(),
        )
    existing.status = "failed"
    existing.completed_at = _iso_now()
    msg = error
    if include_traceback:
        tb = traceback.format_exc()
        if tb and tb != "NoneType: None\n":
            msg = f"{error}\n\n{tb}"
    existing.error = msg
    existing.error_code = error_code
    existing.result = None
    write(existing)


def wait_for_completion(
    job_id: str,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.05,
) -> JobRecord:
    """Test helper: block until the job reaches a terminal state or
    ``timeout_seconds`` elapses. Tight poll interval (50 ms) so tests
    don't sleep unnecessarily long. Raises ``TimeoutError`` if the
    job is still running after the deadline."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        rec = read(job_id)
        if rec is not None and rec.status in ("completed", "failed"):
            return rec
        time.sleep(poll_interval_seconds)
    raise TimeoutError(f"job {job_id} did not reach terminal state in {timeout_seconds}s")
