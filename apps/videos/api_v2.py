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
from typing import Annotated

from django.conf import settings
from django.http import FileResponse, HttpRequest, HttpResponse, StreamingHttpResponse
from ninja import Path as PathParam
from ninja import Router

from apps.api_v2.auth import session_auth
from apps.api_v2.deps import resolve_workspace_for_member
from apps.api_v2.errors import TYPE_NOT_FOUND, TYPE_VALIDATION, ProblemError

from . import service
from .schemas import (
    BuildTriggerIn,
    BuildTriggerOut,
    ClipEditIn,
    ClipEditOut,
    CopyRunOut,
    FeedbackLogOut,
    FeedbackPostIn,
    FeedbackPostOut,
    LibraryEntryOut,
    LibraryOut,
    ProgramCardOut,
    ProgramDetailOut,
    RenderStatusOut,
    RunDetailOut,
    RunSummaryOut,
)

log = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["videos"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_program(workspace_slug: str, program_slug: str) -> service.ProgramRecord:
    """Resolve a program (latest run) for a workspace member; 404 otherwise."""
    if not service.is_valid_slug(program_slug):
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    record = service.load_program(program_slug)
    if record is None or record.workspace_slug != workspace_slug:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    return record


def _require_run(workspace_slug: str, program_slug: str, run_id: str) -> service.ProgramRecord:
    """Resolve a specific run + check workspace membership."""
    if not service.is_valid_slug(program_slug) or not service.is_valid_run_id(run_id):
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    record = service.load_program_run(program_slug, run_id)
    if record is None or record.workspace_slug != workspace_slug:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)
    return record


def _explorer_url(workspace_slug: str, program_slug: str, run_id: str) -> str:
    return f"/api/w/{workspace_slug}/videos/programs/{program_slug}/runs/{run_id}/explorer.html"


def _program_card(latest: service.ProgramRecord) -> dict:
    runs = service.list_run_ids(latest.slug)
    return {
        "slug": latest.slug,
        "name": latest.name,
        "tagline": latest.tagline,
        "country_focus": latest.country_focus,
        "status": latest.status,
        "program_url": latest.program_url,
        "manifest_count": latest.manifest_count,
        "has_explorer_build": latest.has_explorer_build,
        "latest_run_id": latest.run_id,
        "run_count": len(runs),
    }


def _yaml_repo_path(yaml_path) -> str:
    """Repo-relative path display (relative to the parent of ACE_VIDEOS_ROOT)."""
    from pathlib import Path as _Path
    yaml_root = _Path(settings.ACE_VIDEOS_ROOT).parent.parent
    try:
        return str(yaml_path.relative_to(yaml_root))
    except ValueError:
        return yaml_path.name


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
    resolve_workspace_for_member(request, workspace_slug)
    return [
        ProgramCardOut.model_validate(_program_card(r))
        for r in service.list_programs_for_workspace(workspace_slug)
    ]


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
    resolve_workspace_for_member(request, workspace_slug)
    latest = _require_program(workspace_slug, program_slug)
    run_ids = service.list_run_ids(program_slug)
    runs = []
    for rid in run_ids:
        out_p = service.output_path(program_slug, rid)
        exp_p = service.explorer_dir(program_slug, rid) / "index.html"
        runs.append(RunSummaryOut(
            run_id=rid,
            has_output=out_p.exists(),
            has_explorer_build=exp_p.exists(),
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
    resolve_workspace_for_member(request, workspace_slug)
    latest = _require_program(workspace_slug, program_slug)
    new_run_id = service.copy_run(program_slug, latest.run_id)
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
    resolve_workspace_for_member(request, workspace_slug)
    record = _require_run(workspace_slug, program_slug, run_id)
    return RunDetailOut(
        program_slug=program_slug,
        run_id=run_id,
        name=record.name,
        manifest_count=record.manifest_count,
        has_output=record.has_output,
        has_explorer_build=record.has_explorer_build,
        explorer_url=_explorer_url(workspace_slug, program_slug, run_id),
        yaml_path=_yaml_repo_path(record.yaml_path),
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
    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)
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
    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)
    return RenderStatusOut.model_validate(service.render_status(program_slug, run_id))


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
    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)
    path = service.feedback_path(program_slug, run_id)
    markdown = path.read_text(encoding="utf-8") if path.exists() else ""
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

    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)
    ts = dt.datetime.now(dt.UTC).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    scope = f"beat:{body.beatId}" if body.scope == "beat" and body.beatId else "global"
    time_bit = f" (video t={body.timestampSec:.1f}s)" if body.timestampSec is not None else ""
    line = f"\n## [{ts}] {scope}{time_bit}\n\n{body.note}\n"
    path = service.feedback_path(program_slug, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
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
    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)
    result = service.apply_edit(program_slug, run_id, body.model_dump(exclude_none=True))
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
    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)
    if body.mode == "build-only":
        triggered = service.trigger_build_only(program_slug, run_id)
    else:
        triggered = service.trigger_rerender(program_slug, run_id)
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
    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)
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
    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)
    return _serve_rewritten_html(workspace_slug, program_slug, run_id, "library.html")


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
    resolve_workspace_for_member(request, workspace_slug)
    _require_run(workspace_slug, program_slug, run_id)

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
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)

    response = FileResponse(target.open("rb"), as_attachment=False)
    suffix = target.suffix.lower()
    if suffix in {".mp4", ".m4v"}:
        response["Content-Type"] = "video/mp4"
    elif suffix == ".webm":
        response["Content-Type"] = "video/webm"
    return response
