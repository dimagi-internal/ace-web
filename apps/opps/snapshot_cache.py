"""Long-lived OppSnapshot / OppCard cache.

Full implementation lands in the next task. This stub exposes
`clear_workspace` so apps.opps.drive_changes can call it during 410
re-seed.
"""
from __future__ import annotations


def clear_workspace(workspace_id: int) -> None:
    """No-op until snapshot caching is wired in (Task 4)."""
    return None
