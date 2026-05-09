"""Per-request tracker for file_ids visited during a Drive walk.

Used by views.workbench / _opp_list_impl to capture which file_ids the
cold-path `load_opp` / `load_opp_card` touched, so the snapshot cache
can populate its reverse index correctly.

Activation is via a contextvar so nested code in `load_opp` doesn't have
to thread a parameter through. CachedDriveClient.list_files /
.get_file / .get_content check `current_tracker()` and record into it
when one is active; outside a `with` block the cost is one contextvar
read.
"""
from __future__ import annotations

from contextvars import ContextVar


_current: ContextVar["TouchedFileTracker | None"] = ContextVar(
    "ace_touched_file_tracker", default=None,
)


def current_tracker() -> "TouchedFileTracker | None":
    return _current.get()


class TouchedFileTracker:
    """Context manager. Inside the `with` block, every Drive read through
    CachedDriveClient records the visited (file_id, modified_time) pair.
    """
    def __init__(self) -> None:
        self.file_ids: set[str] = set()
        self._mod_times: dict[str, str | None] = {}
        self._token = None

    def record(self, file_id: str, modified_time: str | None = None) -> None:
        self.file_ids.add(file_id)
        # Don't overwrite a non-empty modified_time with None; the first
        # source-of-truth wins.
        if modified_time is not None:
            self._mod_times[file_id] = modified_time
        elif file_id not in self._mod_times:
            self._mod_times[file_id] = None

    def pairs(self) -> list[tuple[str, str | None]]:
        return [(fid, self._mod_times.get(fid)) for fid in self.file_ids]

    def __enter__(self) -> "TouchedFileTracker":
        self._token = _current.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _current.reset(self._token)
            self._token = None
