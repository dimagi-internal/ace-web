"""Retrying a Drive WRITE is only safe when the failure proves it never ran.

ace-web#758: a `fork_at_phase` copy of 178 files died at file 50 on a Drive
`userRateLimitExceeded` and stranded a half-populated run. The read path had
had backoff for months; the write path deliberately did not, on the reasoning
that "a duplicate create/upload on retry could leak resources".

That reasoning is right about 5xx and wrong about 429, and the distinction is
the whole point of this module:

- **429** — Drive rejects at the quota gate, BEFORE the operation runs. Nothing
  was created, so a retry cannot duplicate. Retrying is correct.
- **5xx** — the server may have applied the write and failed to answer. A retry
  would then leak a second copy. Retrying is not safe.

If a future edit widens `_RETRYABLE_WRITE_STATUS` to the read path's set, these
tests are what says no.
"""
from unittest.mock import MagicMock, patch

import pytest
from googleapiclient.errors import HttpError

from apps.opps import drive_client as dc


def _http_error(status: int) -> HttpError:
    resp = MagicMock()
    resp.status = status
    resp.reason = "boom"
    return HttpError(resp, b'{"error": {"message": "boom"}}')


class _Recorder:
    """Minimal object carrying the decorated method, counting invocations."""

    def __init__(self, failures: list[int | None]):
        self._failures = list(failures)
        self.calls = 0

    @dc._drive_write_retry
    def copy_file(self, *_args, **_kwargs) -> str:
        self.calls += 1
        status = self._failures.pop(0) if self._failures else None
        if status is not None:
            raise _http_error(status)
        return "new-id"


@pytest.fixture(autouse=True)
def _no_real_sleeping():
    # The backoff is 2s/4s/8s/16s by design — waiting out a 100s quota window
    # is the point. A test must not actually wait it.
    with patch.object(dc.time, "sleep") as slept:
        yield slept


def test_retries_a_rate_limit_and_succeeds():
    r = _Recorder([429, 429])
    assert r.copy_file("src", "dest") == "new-id"
    assert r.calls == 3


def test_does_not_retry_a_5xx_because_the_write_may_have_landed():
    r = _Recorder([500])
    with pytest.raises(HttpError):
        r.copy_file("src", "dest")
    assert r.calls == 1, "a 5xx retry could leak a duplicate copy"


def test_does_not_retry_a_permission_error():
    r = _Recorder([403])
    with pytest.raises(HttpError):
        r.copy_file("src", "dest")
    assert r.calls == 1


def test_gives_up_after_the_attempt_budget_and_raises_the_real_error():
    r = _Recorder([429] * dc._WRITE_RETRY_ATTEMPTS)
    with pytest.raises(HttpError):
        r.copy_file("src", "dest")
    assert r.calls == dc._WRITE_RETRY_ATTEMPTS


def test_backs_off_long_enough_to_outlast_a_quota_window(_no_real_sleeping):
    # Drive's user rate limit is per-100-seconds. Retrying four times inside a
    # couple of seconds would burn the budget without ever leaving the window,
    # which is a slower way to fail identically.
    r = _Recorder([429] * dc._WRITE_RETRY_ATTEMPTS)
    with pytest.raises(HttpError):
        r.copy_file("src", "dest")
    total = sum(call.args[0] for call in _no_real_sleeping.call_args_list)
    assert total >= 25, f"total backoff {total:.1f}s is short of a quota window"


def test_the_write_set_is_narrower_than_the_read_set():
    # The read path may retry 5xx because reads are idempotent. This is the
    # invariant that keeps the two from being "tidied" into one constant.
    assert dc._RETRYABLE_WRITE_STATUS < dc._RETRYABLE_STATUS
    assert 500 not in dc._RETRYABLE_WRITE_STATUS
    assert dc._RETRYABLE_WRITE_STATUS == {429}


def test_copy_file_is_the_wrapped_write():
    # Named explicitly: this is the one write in the fork's hot loop, and the
    # only write the 429-is-safe argument has been reasoned about for.
    assert getattr(dc.GoogleDriveClient.copy_file, "__wrapped__", None) is not None
