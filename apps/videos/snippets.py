"""Snippet manifest ingest — canopy manifest → VideoSnippet rows.

A snippet manifest (schema_version 1) describes N labeled ranges into
one master clip. ``ingest_manifest`` upserts one ``VideoSnippet`` per
entry, keyed idempotently on ``(workspace, snippet_key)`` so re-running
the same manifest is a no-op (or picks up edits).

Kept separate from the management command (which only does arg parsing
+ I/O) so the upsert logic is unit-testable and could be called from an
API or task later — mirrors the ``library/sync.py`` split.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from apps.videos.models import STATUS_OK, VideoLibraryEntry, VideoSnippet
from apps.workspaces.models import Workspace


def _basename(ref: str | None) -> str | None:
    """Filename component of a local path or hosted url, or None."""
    if not ref:
        return None
    # Works for both POSIX paths and URLs (strip any query/fragment).
    cleaned = ref.split("?", 1)[0].split("#", 1)[0]
    name = PurePosixPath(cleaned).name
    return name or None


def _find_clip(workspace: Workspace, source_clip: str | None) -> VideoLibraryEntry | None:
    """Best-effort: match a manifest source_clip to a library entry by
    filename basename within the workspace. Returns None on no match."""
    base = _basename(source_clip)
    if not base:
        return None
    return (
        VideoLibraryEntry.objects.filter(workspace=workspace, filename=base)
        .order_by("subfolder", "filename")
        .first()
    )


def ingest_manifest(workspace: Workspace, manifest: dict) -> dict[str, int]:
    """Upsert every snippet in ``manifest`` into the workspace.

    Idempotent by ``(workspace, snippet_key)``. Top-level
    ``narrative_slug`` / ``run_id`` are denormalized onto every row.
    Each snippet's ``source_clip`` (or the manifest top-level one) is
    used both to set ``source_clip_ref`` and to best-effort link the
    ``clip`` FK by filename basename.

    Returns ``{"created", "updated", "linked", "unlinked"}``.
    ``linked`` counts rows whose clip FK is set after the upsert;
    ``unlinked`` counts rows left without a clip.
    """
    narrative_slug = str(manifest.get("narrative_slug") or "")
    source_run = str(manifest.get("run_id") or "")
    top_source_clip = manifest.get("source_clip")
    top_source_clip_url = manifest.get("source_clip_url")

    created = updated = linked = unlinked = 0
    for snip in manifest.get("snippets", []):
        snippet_key = snip.get("id")
        if not snippet_key:
            # A snippet with no stable id can't be upserted idempotently.
            continue

        source_clip = snip.get("source_clip") or top_source_clip
        source_clip_url = snip.get("source_clip_url") or top_source_clip_url
        clip = _find_clip(workspace, source_clip)

        sentence = str(snip.get("sentence") or "")

        defaults = dict(
            title=str(snip.get("title") or ""),
            narration_sentence=sentence,
            in_seconds=float(snip.get("in_seconds") or 0.0),
            out_seconds=float(snip.get("out_seconds") or 0.0),
            duration_seconds=float(snip.get("duration_seconds") or 0.0),
            tags=list(snip.get("tags") or []),
            provenance=snip.get("provenance"),
            source_run=source_run,
            narrative_slug=narrative_slug,
            scene_index=snip.get("scene_index"),
            clip=clip,
            source_clip_ref=str(source_clip or ""),
            source_clip_url=str(source_clip_url or ""),
            status=STATUS_OK,
        )

        row, was_created = VideoSnippet.objects.update_or_create(
            workspace=workspace,
            snippet_key=snippet_key,
            defaults=defaults,
        )
        if was_created:
            created += 1
        else:
            updated += 1
        if row.clip_id is not None:
            linked += 1
        else:
            unlinked += 1

    return {"created": created, "updated": updated, "linked": linked, "unlinked": unlinked}
