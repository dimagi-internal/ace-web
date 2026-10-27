"""Archiving runs: hide them from ace-web's default views, keep everything else.

An archived run is a row in `ArchivedRun` and nothing more — Drive and every
external system are untouched. Readers that build a run list (the workbench's
runs endpoint and snapshot, the opp cards, the activity feed) drop archived
runs through the helpers here; the archive page reads `list_archived`.
"""
from __future__ import annotations

from collections import defaultdict

from .models import ArchivedRun


def archived_ids(workspace, slug: str) -> set[str]:
    """Run ids archived under one opp."""
    return set(
        ArchivedRun.objects.filter(workspace=workspace, opp_slug=slug)
        .values_list("run_id", flat=True)
    )


def archived_map(workspace) -> dict[str, set[str]]:
    """{opp_slug: archived run ids} for the whole workspace, in one query."""
    out: dict[str, set[str]] = defaultdict(set)
    for slug, run_id in ArchivedRun.objects.filter(workspace=workspace).values_list(
        "opp_slug", "run_id"
    ):
        out[slug].add(run_id)
    return out


def archive_run(workspace, slug: str, run_id: str, user) -> ArchivedRun:
    """Idempotent: archiving an archived run keeps the original row."""
    row, _ = ArchivedRun.objects.get_or_create(
        workspace=workspace, opp_slug=slug, run_id=run_id,
        defaults={"archived_by": user if getattr(user, "is_authenticated", False) else None},
    )
    return row


def unarchive_run(workspace, slug: str, run_id: str) -> bool:
    """True when a row was removed; False when the run was not archived."""
    deleted, _ = ArchivedRun.objects.filter(
        workspace=workspace, opp_slug=slug, run_id=run_id
    ).delete()
    return deleted > 0


def list_archived(workspace) -> list[dict]:
    """Newest-archived first, for the archive page."""
    rows = ArchivedRun.objects.filter(workspace=workspace).select_related("archived_by")
    return [
        {
            "opp_slug": r.opp_slug,
            "run_id": r.run_id,
            "archived_at": r.archived_at.isoformat(),
            "archived_by": r.archived_by.email if r.archived_by else None,
        }
        for r in rows
    ]
