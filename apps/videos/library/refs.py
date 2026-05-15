"""Parse + resolve the ``library:<media>/[<subfolder>/]<filename>`` spec
reference syntax.

Used by the render-prep code path to turn a stable ``library:`` ref into
a concrete Drive file id before the renderer sees the spec. The renderer
keeps parsing ``gdrive:<id>.<ext>`` — the rewrite is invisible to it.

Resolution hits the DB-backed library tables (populated by
``apps.videos.library.sync``); the previous Drive-walking implementation
was 60-90s at scale.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from apps.workspaces.models import Workspace


class LibraryRefError(ValueError):
    """Raised on malformed library refs."""


@dataclass(frozen=True)
class ParsedRef:
    media: str            # "video" or "audio"
    subfolder: str | None  # None for audio (flat layout)
    filename: str


@dataclass(frozen=True)
class ResolvedRef:
    parsed: ParsedRef
    drive_id: str


_VIDEO_RE = re.compile(r"^library:video/([^/]+)/([^/]+)$")
_AUDIO_RE = re.compile(r"^library:audio/([^/]+)$")


def is_library_ref(ref: str) -> bool:
    return isinstance(ref, str) and ref.startswith("library:")


def parse_library_ref(ref: str) -> ParsedRef:
    """Parse a ``library:`` reference. Raises LibraryRefError on bad input."""
    m = _VIDEO_RE.match(ref)
    if m is not None:
        subfolder, filename = m.group(1), m.group(2)
        return ParsedRef(media="video", subfolder=subfolder, filename=filename)
    m = _AUDIO_RE.match(ref)
    if m is not None:
        return ParsedRef(media="audio", subfolder=None, filename=m.group(1))
    raise LibraryRefError(f"not a library reference: {ref!r}")


def resolve_library_ref(workspace: Workspace, ref: str) -> ResolvedRef | None:
    """Resolve a library ref against the workspace's library tables.

    Returns None when the target row does not exist; raises
    LibraryRefError on malformed refs.
    """
    parsed = parse_library_ref(ref)
    # Local imports — avoid the ORM at module load.
    if parsed.media == "audio":
        from apps.videos.models import AudioLibraryEntry
        # The library:audio/<filename> ref uses the full filename incl. extension;
        # the DB row keys on the bare hash (the stem of the filename).
        stem = parsed.filename.rsplit(".", 1)[0]
        row = AudioLibraryEntry.objects.filter(workspace=workspace, hash=stem).first()
    else:
        from apps.videos.models import VideoLibraryEntry
        assert parsed.subfolder is not None  # parser guarantees
        row = VideoLibraryEntry.objects.filter(
            workspace=workspace, subfolder=parsed.subfolder, filename=parsed.filename,
        ).first()
    if row is None or not row.drive_id:
        return None
    return ResolvedRef(parsed=parsed, drive_id=row.drive_id)
