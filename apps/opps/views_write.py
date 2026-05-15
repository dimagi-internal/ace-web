"""Helpers for in-flight fork progress tracking.

All DRF write-view functions have been removed; the v2 Ninja router in
apps/opps/api.py handles all mutations.  This module is kept as a
shim because api.py still imports _FORK_PROGRESS_TTL and
_fork_progress_key via lazy imports.
"""
from __future__ import annotations

# Progress for an in-flight fork is written to django.core.cache by the
# request thread doing the copy and read by the polling status endpoint
# in a sibling request. The polling endpoint identifies the in-flight
# fork by ``(source_slug, source_run_id)`` since the new run-id isn't
# known until the fork has minted it.
_FORK_PROGRESS_TTL = 600  # seconds — well past the worst-case fork time


def _fork_progress_key(workspace, source_slug: str, source_run_id: str) -> str:
    ws_key = workspace.pk if workspace is not None else "_"
    return f"opp-fork:{ws_key}:{source_slug}:{source_run_id or '_latest'}"
