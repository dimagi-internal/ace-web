"""Parse + resolve the ``library:<media>/[<subfolder>/]<filename>`` spec
reference syntax.

Used by the render-prep code path to turn a stable ``library:`` ref into
a concrete Drive file id before the renderer sees the spec. The renderer
keeps parsing ``gdrive:<id>.<ext>`` — the rewrite is invisible to it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from apps.videos import drive as drive_mod
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
    """Resolve a library ref against the workspace's Drive layout.

    Returns None when the target file does not exist; raises
    LibraryRefError on malformed refs.
    """
    parsed = parse_library_ref(ref)
    # Lazy import to avoid cycles between apps.videos.service and this module.
    from apps.videos.service import layout_for
    layout, client = layout_for(workspace)
    if parsed.media == "audio":
        files = drive_mod.list_audio_library_files(layout, client)
    else:
        assert parsed.subfolder is not None  # parser guarantees
        files = drive_mod.list_library_files(
            layout, client, drive_mod.LIBRARY_VIDEO, parsed.subfolder,
        )
    for f in files:
        if f.name == parsed.filename:
            return ResolvedRef(parsed=parsed, drive_id=f.id)
    return None
