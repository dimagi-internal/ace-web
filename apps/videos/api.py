"""Django Ninja v2 router for the workspace-scoped Videos surface.

URL structure mirrors opps/runs:

    GET    /programs                           — list programs (latest run summary)
    GET    /programs/{slug}                    — program detail incl. runs list
    POST   /programs/{slug}/runs               — fork a new run from the latest
    GET    /programs/{slug}/runs/{run_id}      — run detail (spec metadata + media URLs)
    POST   /programs/{slug}/runs/{run_id}/build   — render or rebuild this run
    POST   /programs/{slug}/runs/{run_id}/edit    — mutate the run's spec.yaml
    GET    /programs/{slug}/runs/{run_id}/render-status
    GET    /programs/{slug}/runs/{run_id}/library.json
    GET    /programs/{slug}/runs/{run_id}/feedback   (+ POST)
    GET    /programs/{slug}/runs/{run_id}/explorer.html
    GET    /programs/{slug}/runs/{run_id}/library.html
    GET    /programs/{slug}/runs/{run_id}/media/{file_name}
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse, StreamingHttpResponse
from ninja import Path as PathParam
from ninja import Router

from apps.api.auth import session_auth
from apps.api.deps import resolve_workspace_for_member
from apps.api.errors import TYPE_NOT_FOUND, TYPE_VALIDATION, ProblemError

from . import drive, service, templates
from .library import reader as library_reader
from .schemas import (
    BuildTriggerIn,
    BuildTriggerOut,
    ClipEditIn,
    ClipEditOut,
    CopyRunOut,
    CreateProgramIn,
    CreateProgramOut,
    EditBatchIn,
    EditBatchOut,
    FeedbackLogOut,
    FeedbackPostIn,
    FeedbackPostOut,
    LibraryEntryOut,
    LibraryOut,
    MediaLibraryAudioItemOut,
    MediaLibraryAudioOut,
    MediaLibraryVideoItemOut,
    MediaLibraryVideoOut,
    MediaLibraryVideoSubfolderOut,
    ProgramCardOut,
    ProgramDetailOut,
    RenderLogOut,
    RenderStatusOut,
    RunDetailOut,
    RunSummaryOut,
    TemplateBundleOut,
    TemplateMetaOut,
)

log = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["videos"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_program(workspace, program_slug: str) -> service.ProgramRecord:
    """Resolve a program (latest run) in this workspace; 404 otherwise."""
    if not service.is_valid_slug(program_slug):
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    record = service.load_program(workspace, program_slug)
    if record is None or record.workspace_slug != workspace.slug:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    return record


def _require_run(workspace, program_slug: str, run_id: str) -> service.ProgramRecord:
    """Resolve a specific run in this workspace; 404 otherwise."""
    if not service.is_valid_slug(program_slug) or not service.is_valid_run_id(run_id):
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    record = service.load_program_run(workspace, program_slug, run_id)
    if record is None or record.workspace_slug != workspace.slug:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    return record


def _explorer_url(workspace_slug: str, program_slug: str, run_id: str) -> str:
    return f"/api/w/{workspace_slug}/videos/programs/{program_slug}/runs/{run_id}/explorer.html"


def _program_card(workspace, latest: service.ProgramRecord) -> dict:
    runs = service.list_run_ids(workspace, latest.slug)
    return {
        "slug": latest.slug,
        "name": latest.name,
        "tagline": latest.tagline,
        "country_focus": latest.country_focus,
        "status": latest.status,
        "program_url": latest.program_url,
        "manifest_count": latest.manifest_count,
        "has_explorer_build": _has_explorer_anywhere(workspace, latest.slug, latest.run_id, latest.has_explorer_build),
        "latest_run_id": latest.run_id,
        "run_count": len(runs),
    }


def _has_explorer_anywhere(workspace, slug: str, run_id: str, local_truth: bool) -> bool:
    """Local-FS first, fall through to Drive metadata existence.

    The local check (`explorer/index.html` exists) is correct for the
    rendering host but lies on every other host. Labs ECS — the
    motivating case — never runs the render chain (no ElevenLabs
    key); a published explorer.tar.gz on Drive is the truth. Without
    this fallback, every program reads "not built" on labs even when
    a Mac-host ran ``render_locally.py --publish`` and the artifact
    is sitting in Drive ready to serve.

    Drive flake collapses to the local truth so a metadata-API hiccup
    doesn't break the program list.
    """
    if local_truth:
        return True
    try:
        layout, client = service.layout_for(workspace)
        return drive.explorer_archive_drive_meta(layout, client, slug, run_id) is not None
    except Exception:
        return False


def _has_output_anywhere(workspace, slug: str, run_id: str, local_truth: bool) -> bool:
    """Sibling of `_has_explorer_anywhere` for the output.mp4 flag.
    Falls through to Drive's output.mp4 metadata when local FS doesn't
    have the file. Same Drive-flake fallthrough."""
    if local_truth:
        return True
    try:
        layout, client = service.layout_for(workspace)
        return drive.output_mp4_drive_meta(layout, client, slug, run_id) is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Templates — MCP-callable, used by an agent (Claude session) to discover
# what templates exist and pull the skeleton + skill prompt for one.
# The agent generates the spec.yaml itself (fetching source content,
# applying the prompt, filling placeholders) and POSTs it back to
# /programs below.
# ---------------------------------------------------------------------------


@router.get(
    "/templates",
    response=list[TemplateMetaOut],
    summary="List available video-spec templates",
    openapi_extra={"x-mcp-expose": True},
)
def list_video_templates(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
) -> list[TemplateMetaOut]:
    resolve_workspace_for_member(request, workspace_slug)
    return [TemplateMetaOut.model_validate(t.__dict__) for t in templates.list_templates()]


@router.get(
    "/templates/{template_id}",
    response=TemplateBundleOut,
    summary="Get the full template bundle (meta + skeleton + skill prompt)",
    openapi_extra={"x-mcp-expose": True},
)
def get_video_template(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    template_id: Annotated[str, PathParam()],
) -> TemplateBundleOut:
    resolve_workspace_for_member(request, workspace_slug)
    bundle = templates.load_template(template_id)
    if bundle is None:
        raise ProblemError(404, "Template not found", type_=TYPE_NOT_FOUND)
    return TemplateBundleOut(
        meta=TemplateMetaOut.model_validate(bundle.meta.__dict__),
        skeleton_yaml=bundle.skeleton_yaml,
        prompt_md=bundle.prompt_md,
    )


# ---------------------------------------------------------------------------
# Media library — MCP-exposed so the video-spec generator can browse it.
# ---------------------------------------------------------------------------


@router.get(
    "/library/video",
    response=MediaLibraryVideoOut,
    summary="List curated video library items grouped by subfolder",
    openapi_extra={"x-mcp-expose": True},
)
def list_media_library_video(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
) -> MediaLibraryVideoOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    raw = library_reader.list_video_library(workspace)
    return MediaLibraryVideoOut(subfolders=[
        MediaLibraryVideoSubfolderOut(
            subfolder=s.subfolder,
            items=[
                MediaLibraryVideoItemOut(
                    ref=i.ref, drive_id=i.drive_id, drive_url=i.drive_url,
                    filename=i.filename, name=i.name, description=i.description,
                    tags=i.tags, status=i.status,
                )
                for i in s.items
            ],
        )
        for s in raw.subfolders
    ])


@router.get(
    "/library/audio",
    response=MediaLibraryAudioOut,
    summary="List the audio library (TTS clips with voice + text metadata)",
    openapi_extra={"x-mcp-expose": True},
)
def list_media_library_audio(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
) -> MediaLibraryAudioOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    raw = library_reader.list_audio_library(workspace)
    return MediaLibraryAudioOut(items=[
        MediaLibraryAudioItemOut(
            hash=i.hash, drive_id=i.drive_id, drive_url=i.drive_url,
            voice_id=i.voice_id, model=i.model, text=i.text,
            duration_sec=i.duration_sec, generated_at=i.generated_at,
            status=i.status,
        )
        for i in raw.items
    ])


@router.get(
    "/library/video/{subfolder}/{filename}/stream",
    summary="Stream a video library clip's bytes (Range-aware)",
)
def stream_library_video(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    subfolder: Annotated[str, PathParam()],
    filename: Annotated[str, PathParam()],
) -> HttpResponse | StreamingHttpResponse:
    """Serve raw bytes for one video library entry — used by the clip
    picker so the user can scrub thumbnails for clips that aren't yet
    in the open program's manifest. Lazy-caches into
    ``<videos_root>/assets/clip-cache/<gdriveId>.<ext>`` so repeat
    requests skip the Drive round-trip. Mirrors the audio library
    stream path above.
    """
    import os.path as _osp
    import re as _re
    # Defensive path validation — neither argument should slip out of
    # its component. The library reader uses these verbatim as PK-like
    # lookups; reject anything that smells like traversal.
    if (
        not _re.fullmatch(r"[A-Za-z0-9_.-]+", subfolder)
        or not _re.fullmatch(r"[A-Za-z0-9_.-]+", filename)
        or filename != _osp.basename(filename)
    ):
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)

    workspace = resolve_workspace_for_member(request, workspace_slug)

    from apps.videos.models import VideoLibraryEntry
    try:
        entry = VideoLibraryEntry.objects.get(
            workspace=workspace, subfolder=subfolder, filename=filename,
        )
    except VideoLibraryEntry.DoesNotExist:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND) from None

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "mp4"
    cache_path = service._root() / "assets" / "clip-cache" / f"{entry.drive_id}.{ext}"
    if not cache_path.is_file():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        client = service.drive.get_drive_client()
        # Library entries are typically Drive *shortcuts* — populated by
        # ``scripts/seed_video_library`` to keep the canonical clip files
        # in place under their original CHC Media Shoot folders. Drive
        # refuses to ``get_binary`` a shortcut directly ("fileNotDownloadable"
        # → 403). Resolve to the target id first, then fetch.
        meta = client._service.files().get(
            fileId=entry.drive_id,
            fields="id,mimeType,shortcutDetails",
            supportsAllDrives=True,
        ).execute()
        target_id = entry.drive_id
        if meta.get("mimeType") == "application/vnd.google-apps.shortcut":
            target_id = meta.get("shortcutDetails", {}).get("targetId") or target_id
        try:
            content = client.get_binary(target_id)
        except Exception as e:  # pragma: no cover — surfaces as 502
            raise ProblemError(
                502, "Drive fetch failed", detail=str(e)[:200],
            ) from e
        cache_path.write_bytes(content)

    suffix = cache_path.suffix.lower()
    if suffix in {".mp4", ".m4v"}:
        content_type = "video/mp4"
    elif suffix == ".webm":
        content_type = "video/webm"
    else:
        content_type = "application/octet-stream"
    return _range_aware_file_response(request, cache_path, content_type)


@router.get(
    "/library/audio/{hash}/stream",
    summary="Stream the audio clip bytes (Range-aware)",
)
def stream_library_audio(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    hash: Annotated[str, PathParam()],
) -> HttpResponse | StreamingHttpResponse:
    """Serve the raw MP3 bytes for one library audio entry.

    Lazy-caches into the same on-disk audio cache the renderer uses
    (``<videos_root>/assets/audio/<hash>.mp3``) so repeat playback hits
    local disk. First playback fetches via the workspace's Drive SA.
    """
    import re as _re
    if not _re.fullmatch(r"[a-f0-9]{16}", hash):
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)

    workspace = resolve_workspace_for_member(request, workspace_slug)

    from apps.videos.models import AudioLibraryEntry
    try:
        entry = AudioLibraryEntry.objects.get(workspace=workspace, hash=hash)
    except AudioLibraryEntry.DoesNotExist:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND) from None

    cache_path = service._root() / "assets" / "audio" / f"{hash}.mp3"
    if not cache_path.is_file():
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        client = service.drive.get_drive_client()
        try:
            content = client.get_binary(entry.drive_id)
        except Exception as e:  # pragma: no cover — surfaces as 502 to caller
            raise ProblemError(
                502, "Drive fetch failed", detail=str(e)[:200],
            ) from e
        cache_path.write_bytes(content)

    return _range_aware_file_response(request, cache_path, "audio/mpeg")


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------


@router.get(
    "/programs",
    response=list[ProgramCardOut],
    summary="List video programs in workspace (latest run per program)",
    openapi_extra={"x-mcp-expose": True},
)
def list_programs(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
) -> list[ProgramCardOut]:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    return [
        ProgramCardOut.model_validate(_program_card(workspace, r))
        for r in service.list_programs_for_workspace(workspace)
    ]


@router.post(
    "/programs",
    response=CreateProgramOut,
    summary="Create a new program from a generated spec.yaml (agent-authored)",
)
def create_program(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    body: CreateProgramIn,
) -> CreateProgramOut:
    """Accept a complete spec.yaml body (generated by an agent following
    a template's prompt) and write it as programs/<slug>/runs/run-001/spec.yaml.

    The server validates structure + slug uniqueness; the agent owns
    content quality. Workspace membership is checked here, and the
    spec_yaml's ``workspace:`` field must match the URL workspace_slug.
    """
    workspace = resolve_workspace_for_member(request, workspace_slug)
    if not service.is_valid_slug(body.slug):
        raise ProblemError(
            400,
            "Invalid program slug",
            type_=TYPE_VALIDATION,
            detail=f"Slug must match {service._SLUG_RE.pattern!r}; got {body.slug!r}",
        )
    try:
        service.create_program_from_spec(workspace, body.slug, body.spec_yaml)
    except FileExistsError as e:
        raise ProblemError(409, "Program already exists", type_=TYPE_VALIDATION, detail=str(e))
    except ValueError as e:
        raise ProblemError(400, "Invalid spec", type_=TYPE_VALIDATION, detail=str(e))

    rel = service.drive_spec_display(body.slug, "run-001")
    return CreateProgramOut(
        program_slug=body.slug,
        run_id="run-001",
        spec_path=rel,
        message=(
            f"Wrote {rel} to Drive. Click Re-render in the UI "
            f"(or POST /programs/{body.slug}/runs/run-001/build) "
            "to generate the first output."
        ),
    )


@router.get(
    "/programs/{program_slug}",
    response=ProgramDetailOut,
    summary="Program detail including runs list",
    openapi_extra={"x-mcp-expose": True},
)
def get_program(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
) -> ProgramDetailOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    latest = _require_program(workspace, program_slug)
    run_ids = service.list_run_ids(workspace, program_slug)
    runs = []
    for rid in run_ids:
        out_p = service.output_path(program_slug, rid)
        exp_p = service.explorer_dir(program_slug, rid) / "index.html"
        runs.append(RunSummaryOut(
            run_id=rid,
            # Local FS first, fall through to Drive metadata so the
            # run picker on hosts that didn't render (labs, fresh
            # dev) doesn't lie. Same pattern as _has_explorer_anywhere
            # and the program card.
            has_output=_has_output_anywhere(workspace, program_slug, rid, out_p.exists()),
            has_explorer_build=_has_explorer_anywhere(workspace, program_slug, rid, exp_p.exists()),
        ))
    return ProgramDetailOut(
        slug=latest.slug,
        name=latest.name,
        tagline=latest.tagline,
        country_focus=latest.country_focus,
        status=latest.status,
        program_url=latest.program_url,
        runs=runs,
    )


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@router.post(
    "/programs/{program_slug}/runs",
    response=CopyRunOut,
    summary="Snapshot the latest run into a new run (save-as; both stay mutable)",
)
def copy_run(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
) -> CopyRunOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    latest = _require_program(workspace, program_slug)
    new_run_id = service.copy_run(workspace, program_slug, latest.run_id)
    log.info("videos.copy_run: %s/%s → %s", program_slug, latest.run_id, new_run_id)
    return CopyRunOut(
        program_slug=program_slug,
        new_run_id=new_run_id,
        copied_from=latest.run_id,
    )


@router.get(
    "/programs/{program_slug}/runs/{run_id}",
    response=RunDetailOut,
    summary="Run detail",
    openapi_extra={"x-mcp-expose": True},
)
def get_run(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
) -> RunDetailOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    record = _require_run(workspace, program_slug, run_id)
    # final.mp4 mtime is the render completion time; the UI uses it to
    # render "rendered Nm ago" in the run summary. Local FS mtime
    # first; if no local file exists (labs, fresh dev), fall back to
    # the Drive-side modifiedTime on the published output.mp4 so the
    # chip works on every host that can see Drive.
    rendered_at: str | None = None
    spec_modified_at: str | None = None
    drive_output_meta = None
    if record.has_output:
        from datetime import UTC, datetime
        out_p = service.output_path(program_slug, run_id)
        try:
            rendered_at = datetime.fromtimestamp(out_p.stat().st_mtime, tz=UTC).isoformat()
        except OSError:
            rendered_at = None
    # One Drive metadata batch — spec.yaml's modifiedTime (drives the
    # "stale" qualifier) + output.mp4 metadata. The output meta is
    # also needed for has_output fallthrough on non-rendering hosts
    # AND for exposing the Drive webViewLink in the editor's kebab
    # menu (so always fetched, not just when rendered_at is None).
    try:
        layout, client = service.layout_for(workspace)
        spec_modified_at = drive.spec_modified_time(layout, client, program_slug, run_id)
        drive_output_meta = drive.output_mp4_drive_meta(layout, client, program_slug, run_id)
        if rendered_at is None and drive_output_meta is not None:
            rendered_at = drive_output_meta.modified_time
    except Exception:
        # Drive flake — keep the locally-derived values, don't 500.
        pass
    has_output = record.has_output or drive_output_meta is not None
    output_drive_url = (
        drive_output_meta.web_view_link if drive_output_meta is not None else None
    )
    return RunDetailOut(
        program_slug=program_slug,
        run_id=run_id,
        name=record.name,
        manifest_count=record.manifest_count,
        has_output=has_output,
        has_explorer_build=_has_explorer_anywhere(
            workspace, program_slug, run_id, record.has_explorer_build,
        ),
        explorer_url=_explorer_url(workspace_slug, program_slug, run_id),
        yaml_path=record.yaml_path,
        spec=service.read_parsed_spec(workspace, program_slug, run_id),
        output_rendered_at=rendered_at,
        spec_modified_at=spec_modified_at,
        output_drive_url=output_drive_url,
    )


# ---------------------------------------------------------------------------
# JSON: library / render-status / feedback
# ---------------------------------------------------------------------------


@router.get(
    "/programs/{program_slug}/runs/{run_id}/library.json",
    response=LibraryOut,
    summary="Structured clip library for the explorer drawer",
    openapi_extra={"x-mcp-expose": True},
)
def get_library(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
) -> LibraryOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    entries = [LibraryEntryOut.model_validate(e) for e in service.load_library_entries(program_slug, run_id)]
    return LibraryOut(entries=entries)


@router.get(
    "/programs/{program_slug}/runs/{run_id}/render-status",
    response=RenderStatusOut,
    summary="Background-render busy flag for a run",
    openapi_extra={"x-mcp-expose": True},
)
def get_render_status(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
) -> RenderStatusOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    return RenderStatusOut.model_validate(service.render_status(program_slug, run_id))


@router.get(
    "/programs/{program_slug}/runs/{run_id}/render-log",
    response=RenderLogOut,
    summary="Captured stdout+stderr of the most recent render chain",
    openapi_extra={"x-mcp-expose": True},
)
def get_render_log(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
) -> RenderLogOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    log_path = service.render_log_path(program_slug, run_id)
    if log_path.is_file():
        try:
            body = log_path.read_text(encoding="utf-8", errors="replace")
            size = log_path.stat().st_size
        except OSError:
            body = ""
            size = 0
    else:
        body = ""
        size = 0
    status = service.render_status(program_slug, run_id)
    return RenderLogOut(
        program_slug=program_slug,
        run_id=run_id,
        started_at=status.get("started_at"),
        log=body,
        size_bytes=size,
        busy=bool(status.get("busy")),
    )


@router.get(
    "/programs/{program_slug}/runs/{run_id}/feedback",
    response=FeedbackLogOut,
    summary="Read the run's feedback markdown log",
    openapi_extra={"x-mcp-expose": True},
)
def get_feedback(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
) -> FeedbackLogOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    markdown = service.read_feedback(workspace, program_slug, run_id)
    return FeedbackLogOut(program_slug=program_slug, run_id=run_id, markdown=markdown)


@router.post(
    "/programs/{program_slug}/runs/{run_id}/feedback",
    response=FeedbackPostOut,
    summary="Append a note to the run's feedback markdown log",
)
def post_feedback(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
    body: FeedbackPostIn,
) -> FeedbackPostOut:
    import datetime as dt

    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    ts = dt.datetime.now(dt.UTC).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    scope = f"beat:{body.beatId}" if body.scope == "beat" and body.beatId else "global"
    time_bit = f" (video t={body.timestampSec:.1f}s)" if body.timestampSec is not None else ""
    line = f"\n## [{ts}] {scope}{time_bit}\n\n{body.note}\n"
    service.append_feedback(workspace, program_slug, run_id, line)
    return FeedbackPostOut(ok=True, timestamp=ts)


@router.post(
    "/programs/{program_slug}/runs/{run_id}/edit",
    response=ClipEditOut,
    summary="Save an edit to the run's spec.yaml (save only — does NOT render)",
)
def post_edit(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
    body: ClipEditIn,
) -> ClipEditOut:
    """Save an edit to spec.yaml. Does NOT trigger a render — that's a
    separate explicit step via POST /build. Splitting the two lets the
    operator batch many edits before paying the render cost; the
    "Re-render" button in the UI is the single canonical render entry.
    """
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    result = service.apply_edit(workspace, program_slug, run_id, body.model_dump(exclude_none=True))
    if not result.ok:
        raise ProblemError(
            400,
            "Edit could not be applied",
            type_=TYPE_VALIDATION,
            detail=result.message,
        )
    return ClipEditOut(
        ok=True,
        message=result.message + " — click Re-render to regenerate the output.",
        rerender_triggered=False,
    )


@router.post(
    "/programs/{program_slug}/runs/{run_id}/edit-batch",
    response=EditBatchOut,
    summary="Save N edits to spec.yaml in one Drive round-trip (save only — does NOT render)",
)
def post_edit_batch(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
    body: EditBatchIn,
) -> EditBatchOut:
    """Atomic batch edit. All ops are validated and applied in order;
    if any fails, the spec is not saved (all-or-nothing).
    """
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    ops = [op.model_dump(exclude_none=True) for op in body.ops]
    result = service.apply_edit_batch(workspace, program_slug, run_id, ops)
    if not result.ok:
        raise ProblemError(
            400,
            "Edit batch could not be applied",
            type_=TYPE_VALIDATION,
            detail=result.message,
        )
    return EditBatchOut(
        ok=True,
        applied=result.applied,
        message=result.message + " — click Re-render to regenerate.",
    )


@router.post(
    "/programs/{program_slug}/runs/{run_id}/build",
    response=BuildTriggerOut,
    summary="Trigger render or rebuild-only for this run",
)
def post_build(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
    body: BuildTriggerIn,
) -> BuildTriggerOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    if body.mode == "build-only":
        triggered = service.trigger_build_only(workspace, program_slug, run_id)
    else:
        triggered = service.trigger_rerender(workspace, program_slug, run_id)
    return BuildTriggerOut(
        ok=True,
        triggered=triggered,
        mode=body.mode,
        message=(
            "Kicked off in background; refresh in a few seconds."
            if triggered else
            "Render already in flight; skipped duplicate."
        ),
    )


# ---------------------------------------------------------------------------
# HTML + media (the iframe surface)
# ---------------------------------------------------------------------------


def _serve_rewritten_html(
    workspace_slug: str, program_slug: str, run_id: str, filename: str,
) -> HttpResponse:
    src = service.explorer_dir(program_slug, run_id) / filename
    if not src.exists():
        raise ProblemError(
            404,
            "Explorer build not found",
            type_=TYPE_NOT_FOUND,
            detail=(
                f"Run `npm run build-clip-explorer -- --program={program_slug} --run={run_id}` "
                "from video-production/connect-videos/ to generate it (or click 'Rebuild HTML' in the UI)."
            ),
        )
    prefix = f"/api/w/{workspace_slug}/videos/programs/{program_slug}/runs/{run_id}/"
    csrf_cookie = getattr(settings, "CSRF_COOKIE_NAME", "csrftoken")
    html = service.rewrite_explorer_html(
        src.read_text(encoding="utf-8"),
        prefix=prefix,
        csrf_cookie_name=csrf_cookie,
    )
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response


@router.get(
    "/programs/{program_slug}/runs/{run_id}/explorer.html",
    summary="Serve the run's generated explorer index.html",
)
def serve_explorer(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    return _serve_rewritten_html(workspace_slug, program_slug, run_id, "index.html")


@router.get(
    "/programs/{program_slug}/runs/{run_id}/library.html",
    summary="Serve the run's generated library.html",
)
def serve_library_html(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    return _serve_rewritten_html(workspace_slug, program_slug, run_id, "library.html")


# Pattern that matches the hydrate cache convention:
#   <HOME>/.cache/connect-videos/<gdriveId>.<ext>
# Captures the gdrive id so we can re-fetch via the SA.
_HYDRATE_CACHE_RE = re.compile(
    r"\.cache/connect-videos/(?P<gid>[A-Za-z0-9_-]{20,})\.(?P<ext>mp4|webm|m4v)$"
)


def _resolve_symlink_via_drive(target):
    """If `target` is a symlink to the hydrate cache, fetch the linked
    gdrive file through the workspace SA, write it to a stable on-disk
    cache, and return the cached Path. Returns None if the target isn't
    a recognisable symlink or the fetch fails.
    """
    try:
        link_dest = str(target.readlink()) if target.is_symlink() else None
    except OSError:
        return None
    if not link_dest:
        return None
    m = _HYDRATE_CACHE_RE.search(link_dest)
    if not m:
        return None
    gid, ext = m.group("gid"), m.group("ext")
    cache = service._root() / "assets" / "clip-cache" / f"{gid}.{ext}"
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        client = service.drive.get_drive_client()
        try:
            content = client.get_binary(gid)
        except Exception as e:  # pragma: no cover — surfaces as 404 to caller
            log.warning("serve_media: Drive fetch failed for %s: %s", gid, e)
            return None
        cache.write_bytes(content)
    return Path(cache)


def _lazy_pull_output_mp4(workspace, slug: str, run_id: str) -> Path | None:
    """Fetch the published ``output.mp4`` for a run from Drive into the
    local FS so we can serve it. Returns the local Path, or None when
    nothing is published yet.

    Why this exists: hosts that don't run the render chain (e.g. labs
    ECS — no ElevenLabs key, no node_modules at the right path) end up
    here when a user requests ``/media/final.mp4`` for a run whose
    output was published from another host. Without this, labs 404s
    even though the asset is sitting in Drive ready to serve. With it,
    a ``render_locally.py --publish`` from any Mac becomes "labs can
    play the result" without provisioning a render stack on labs.

    The fetch writes to the canonical local path (``output.mp4`` at
    the run dir) and re-creates the explorer's relative symlink
    (``explorer/media/final.mp4 → ../../output.mp4``) so a later
    ``build-clip-explorer`` run keeps working and subsequent requests
    serve from disk without re-fetching.
    """
    try:
        layout, client = service.layout_for(workspace)
        content = service.drive.read_output_mp4(layout, client, slug, run_id)
    except Exception as e:  # pragma: no cover — Drive flake → 404 to caller
        log.warning("serve_media: Drive output.mp4 fetch failed for %s/%s: %s",
                    slug, run_id, e)
        return None
    if content is None:
        return None
    out_p = service.output_path(slug, run_id)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_bytes(content)
    media_dir = service.explorer_dir(slug, run_id) / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    link = media_dir / "final.mp4"
    # Recreate the relative symlink build-clip-explorer creates so we
    # match the post-render directory shape. Tolerate a stale broken
    # symlink by unlinking first.
    if link.is_symlink() or link.exists():
        try:
            link.unlink()
        except OSError:
            pass
    try:
        link.symlink_to(Path("../..") / "output.mp4")
    except OSError:
        # Symlinks may not be supported (rare on Linux containers, but
        # safe-guard). Caller still gets the canonical Path back so
        # the request serves; subsequent requests will refetch + retry.
        pass
    return out_p


@router.get(
    "/programs/{program_slug}/runs/{run_id}/media/{file_name}",
    summary="Serve an MP4 from the run's explorer media directory (Range-aware)",
)
def serve_media(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
    file_name: Annotated[str, PathParam()],
) -> HttpResponse | StreamingHttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)

    import os.path
    if (
        "/" in file_name
        or "\\" in file_name
        or os.path.isabs(file_name)
        or file_name in {".", ".."}
        or file_name != os.path.basename(file_name)
    ):
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    media_dir = service.explorer_dir(program_slug, run_id) / "media"
    target = media_dir / file_name
    if not target.is_file():
        # Two recovery paths before 404'ing:
        #
        # 1. Clip-media broken symlink — the explorer build symlinks each
        #    ``@alias.mp4`` into the hydrate cache
        #    (``<HOME>/.cache/connect-videos/<gdriveId>.<ext>``); on a
        #    host that didn't do the hydrate (Django container, fresh
        #    labs task) the symlink dangles. Parse the gdrive id out and
        #    fetch through the workspace SA into ``assets/clip-cache/``.
        #
        # 2. Final.mp4 published from another host — labs doesn't run
        #    the render chain (no ElevenLabs key, see CLAUDE.md), so a
        #    ``render_locally.py --publish`` from a Mac is the only way
        #    final.mp4 ends up in Drive. Lazy-pull it on demand so the
        #    publish flow actually surfaces on labs.
        resolved = _resolve_symlink_via_drive(target)
        if resolved is None and file_name == "final.mp4":
            resolved = _lazy_pull_output_mp4(workspace, program_slug, run_id)
        if resolved is None:
            raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
        target = resolved

    suffix = target.suffix.lower()
    if suffix in {".mp4", ".m4v"}:
        content_type = "video/mp4"
    elif suffix == ".webm":
        content_type = "video/webm"
    else:
        content_type = "application/octet-stream"
    return _range_aware_file_response(request, target, content_type)


def _range_aware_file_response(
    request: HttpRequest, path: Path, content_type: str,
) -> HttpResponse | StreamingHttpResponse:
    """Serve a static file with HTTP Range support so HTML5 <video>
    elements can seek.

    Django 5.x FileResponse does NOT honor Range headers — it always
    returns the full body with 200, which means the browser scrubber
    can't actually move the playhead (it requests bytes=N- and the
    server hands back bytes=0-). We parse the Range header here and
    return 206 Partial Content + Content-Range when it's present, or
    fall through to the full file with Accept-Ranges: bytes so the
    browser learns the endpoint supports ranged requests.

    Supports the only Range forms HTML5 <video> sends in practice:
      bytes=N-           (open-ended, from N to end-of-file)
      bytes=N-M          (closed, N through M inclusive)
    Other forms (suffix ranges `bytes=-N`, multi-range) return 416
    Range Not Satisfiable so the browser falls back cleanly.
    """
    file_size = path.stat().st_size
    range_header = request.headers.get("Range") or request.META.get("HTTP_RANGE")
    if range_header:
        m = re.fullmatch(r"\s*bytes=(\d+)-(\d*)\s*", range_header)
        if m is None:
            # Unsupported Range form (suffix ranges, multi-range, etc.)
            # — clean 416 lets the browser drop back to full GET.
            from django.http import HttpResponse as _HR
            resp = _HR(status=416)
            resp["Content-Range"] = f"bytes */{file_size}"
            return resp
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else file_size - 1
        end = min(end, file_size - 1)
        if start > end or start >= file_size:
            from django.http import HttpResponse as _HR
            resp = _HR(status=416)
            resp["Content-Range"] = f"bytes */{file_size}"
            return resp
        length = end - start + 1

        def _chunks() -> Iterator[bytes]:
            # 64KB chunks — large enough to amortise syscall overhead,
            # small enough that one stuck client doesn't pin a worker
            # for long. Bookended by an explicit close on the generator
            # exit so Python doesn't rely on GC to release the fd.
            chunk = 64 * 1024
            with path.open("rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    data = f.read(min(chunk, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        response = StreamingHttpResponse(_chunks(), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response["Content-Length"] = str(length)
        response["Accept-Ranges"] = "bytes"
        response["Cache-Control"] = "private, max-age=3600"
        return response

    # No Range header: full file, but advertise range support so the
    # next seek goes through the 206 path above.
    response = FileResponse(path.open("rb"), as_attachment=False)
    response["Content-Type"] = content_type
    response["Content-Length"] = str(file_size)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, max-age=3600"
    return response


_QA_FRAME_BEATS = frozenset({
    "hook", "cycle", "handoff", "scene",
    "problem", "product", "impact", "cta",
})


@router.get(
    "/programs/{program_slug}/runs/{run_id}/qa-frame/{beat_id}",
    summary="Serve the post-render QA preview PNG for a beat (or 404)",
)
def serve_qa_frame(
    request: HttpRequest,
    workspace_slug: Annotated[str, PathParam()],
    program_slug: Annotated[str, PathParam()],
    run_id: Annotated[str, PathParam()],
    beat_id: Annotated[str, PathParam()],
) -> HttpResponse:
    """Serve the per-beat preview PNG the QA probe writes after each
    render (``programs/<slug>/runs/<run>/qa-frames/<beat>.png``). 404
    if the run hasn't been rendered yet or the beat isn't a known
    template beat — callers should fall back to a static icon.

    Beat-id allowlist (``_QA_FRAME_BEATS``) blocks path traversal:
    only canonical beat slugs render qa-frames, so unknown values
    return 404 without touching the filesystem."""
    workspace = resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace, program_slug, run_id)
    if beat_id not in _QA_FRAME_BEATS:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    target = service.qa_frames_dir(program_slug, run_id) / f"{beat_id}.png"
    if not target.is_file():
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    response = FileResponse(target.open("rb"), as_attachment=False)
    response["Content-Type"] = "image/png"
    # qa-frames are regenerated atomically on every render; cache for a
    # short window so consecutive widget renders hit disk once, but
    # invalidate quickly after a re-render lands.
    response["Cache-Control"] = "private, max-age=60"
    return response
