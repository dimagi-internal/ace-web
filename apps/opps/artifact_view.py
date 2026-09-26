"""One run file, in the form an in-page viewer can render.

The Phases screen opens what a run made — the PDD, a training deck, a sheet,
screenshots — in place rather than sending the reader off to Drive. That needs
each file in a shape a browser draws without a Google sign-in:

    Google Doc (prose, *.md)   → markdown export, passed through VERBATIM
    Google Doc (yaml/json)     → plain text (a markdown export escapes YAML)
    Google Slides              → PDF export
    Google Sheet               → CSV
    image/* · video/* · PDF    → the bytes
    text/*, yaml, json         → text
    anything else              → not viewable (the viewer offers Drive)

Markdown is passed through verbatim because the viewer's renderer is
CommonMark and resolves Drive's backslash escapes itself — the same call the
public summary makes for the build memo (docs/learnings/drive-prose-export.md).

**Authorization.** The id must belong to the run: a step artifact, a product's
``file_id`` (both off the cached rich snapshot), or a file directly in the run
folder. That scan is the boundary — without it any workspace member could read
any file the service account can see. It mirrors ``download_artifact_bytes``.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.opps.drive_client import DriveClient
from apps.opps.drive_export import GOOGLE_DOC_MIME, MARKDOWN_EXPORT, prose_export_mime

SLIDES_MIME = "application/vnd.google-apps.presentation"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
PDF_MIME = "application/pdf"

#: Bytes above which a file is not streamed into the page. Drive's own export
#: limit is 10 MB; this bounds the raw-media path (screen recordings).
MAX_VIEW_BYTES = 50 * 1024 * 1024

_TEXT_SUFFIXES = (".yaml", ".yml", ".json", ".txt", ".csv", ".md", ".markdown")


class ArtifactNotFound(Exception):
    """The id is not a file of this run."""


class ArtifactTooLarge(Exception):
    """The file is bigger than :data:`MAX_VIEW_BYTES`."""


class ArtifactNotViewable(Exception):
    """No in-page representation exists for this file type."""


@dataclass(frozen=True)
class FileMeta:
    file_id: str
    name: str
    mime_type: str
    web_link: str | None
    size_bytes: int | None


@dataclass(frozen=True)
class ArtifactView:
    body: bytes
    content_type: str
    name: str
    web_link: str | None


def find_in_snapshot(snapshot: dict, file_id: str) -> FileMeta | None:
    """Metadata for ``file_id`` when the snapshot already knows it as a step
    artifact. Product file ids are known to belong to the run but carry no
    MIME, so they are answered by :func:`is_product_file` instead."""
    run = snapshot.get("current_run") or {}
    for step in run.get("steps") or []:
        for art in step.get("artifacts") or []:
            if art.get("drive_file_id") == file_id:
                return FileMeta(
                    file_id=file_id,
                    name=str(art.get("name") or art.get("path") or file_id),
                    mime_type=str(art.get("mime_type") or ""),
                    web_link=art.get("drive_web_link") or None,
                    size_bytes=art.get("size_bytes"),
                )
    return None


def is_product_file(snapshot: dict, file_id: str) -> bool:
    run = snapshot.get("current_run") or {}
    return any(
        isinstance(p, dict) and p.get("file_id") == file_id for p in run.get("products") or []
    )


def resolve(drive: DriveClient, snapshot: dict, file_id: str) -> FileMeta:
    """Resolve ``file_id`` to a file of this run, or raise ArtifactNotFound."""
    known = find_in_snapshot(snapshot, file_id)
    if known is not None and known.mime_type:
        return known

    belongs = known is not None or is_product_file(snapshot, file_id)
    if not belongs:
        folder_id = (snapshot.get("current_run") or {}).get("folder_id") or ""
        if folder_id:
            belongs = any(f.id == file_id for f in drive.list_folder(folder_id))
    if not belongs:
        raise ArtifactNotFound(file_id)

    f = drive.get_file(file_id)
    return FileMeta(
        file_id=file_id,
        name=f.name or file_id,
        mime_type=f.mime_type or "",
        web_link=f.web_view_link or None,
        size_bytes=f.size_bytes,
    )


def render(drive: DriveClient, meta: FileMeta) -> ArtifactView:
    """Fetch ``meta``'s file in its viewable representation."""
    mime = meta.mime_type
    name = meta.name
    lowered = name.lower()

    def view(body: bytes, content_type: str) -> ArtifactView:
        return ArtifactView(body=body, content_type=content_type, name=name, web_link=meta.web_link)

    if mime == GOOGLE_DOC_MIME:
        if prose_export_mime(name, mime) == MARKDOWN_EXPORT or not lowered.endswith(
            _TEXT_SUFFIXES
        ):
            # A Doc with a prose name, or no extension at all (a PDD titled
            # "Turmeric Market Survey"), reads as a document.
            content = drive.get_content(meta.file_id, mime, export_as=MARKDOWN_EXPORT)
            return view(_utf8(content.content), "text/markdown; charset=utf-8")
        content = drive.get_content(meta.file_id, mime)
        return view(_utf8(content.content), "text/plain; charset=utf-8")
    if mime == SLIDES_MIME:
        return view(drive.export_bytes(meta.file_id, PDF_MIME), PDF_MIME)
    if mime == SHEET_MIME:
        content = drive.get_content(meta.file_id, mime)
        return view(_utf8(content.content), "text/csv; charset=utf-8")

    if meta.size_bytes is not None and meta.size_bytes > MAX_VIEW_BYTES:
        raise ArtifactTooLarge(name)
    if mime.startswith(("image/", "video/")) or mime == PDF_MIME:
        body = drive.get_binary(meta.file_id)
        if len(body) > MAX_VIEW_BYTES:
            raise ArtifactTooLarge(name)
        return view(body, mime)
    if mime.startswith("text/") or mime in {
        "application/json",
        "application/x-yaml",
        "application/yaml",
    } or lowered.endswith(_TEXT_SUFFIXES):
        body = drive.get_binary(meta.file_id)
        if lowered.endswith((".md", ".markdown")):
            return view(body, "text/markdown; charset=utf-8")
        if lowered.endswith(".csv") or mime == "text/csv":
            return view(body, "text/csv; charset=utf-8")
        return view(body, "text/plain; charset=utf-8")
    raise ArtifactNotViewable(f"{name} ({mime or 'unknown type'})")


def _utf8(text: str | bytes) -> bytes:
    return text if isinstance(text, bytes) else str(text).encode("utf-8")
