"""Django Ninja v2 router for the opps Workbench surface."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated

from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Path, Router

from apps.api_v2.auth import session_auth
from apps.api_v2.deps import require_write_global, resolve_workspace_for_member
from apps.api_v2.errors import (
    TYPE_CONFLICT,
    TYPE_NOT_FOUND,
    TYPE_VALIDATION,
    ProblemError,
)
from apps.api_v2.etag import compute_etag, maybe_not_modified
from apps.api_v2.pagination import Page, paginate

from .schemas import (
    ArtifactOut,
    ForkProgress,
    GateDecisionIn,
    GateOut,
    OppCardOut,
    OppCompareOut,
    OppCreateIn,
    OppForkIn,
    OppForkOut,
    OppHealthOut,
    OppPatchIn,
    OppRunOut,
    OppSnapshotOut,
    ScorecardOut,
    SeedChatIn,
    SeedChatOut,
    StepSnapshotOut,
)

log = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["opps"])

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)


def list_opp_cards(workspace) -> list[dict]:
    """Return a list of dicts shaped for OppCardOut from the workspace's Drive root.

    Wraps the Drive-reading machinery in apps/opps/sync.py and
    apps/opps/views._opp_list_impl. The monkeypatch target in contract
    tests is this module-level function.

    Field mapping from OppCard / OppManifest to OppCardOut:
      title        <- card.opp.display_name
      current_phase <- card.current_phase (unchanged)
      current_skill <- card.current_step
      run_count    <- card.run_count
      last_run_id  <- card.opp.current_run_id
      updated_at   <- card.last_activity_at (ISO-8601 string) or epoch fallback
    """
    from apps.opps import access, snapshot_cache
    from apps.opps.drive_cache import CachedDriveClient
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import load_opp_card
    from apps.opps.touched_tracker import TouchedFileTracker
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        return []

    try:
        inner = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound:
        log.warning("list_opp_cards: Drive not configured for workspace %s", workspace.slug)
        return []

    client = CachedDriveClient(inner, bypass=False)

    try:
        root_children = client.list_files(ace_folder_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("list_opp_cards: root Drive listing failed: %s", exc)
        return []

    out: list[dict] = []
    for child in root_children:
        if child.mime_type != "application/vnd.google-apps.folder":
            continue
        opp_children = client.list_files(child.id)
        names = {f.name for f in opp_children}
        if not (
            "idea.md" in names
            or "run_state.yaml" in names
            or "opp.yaml" in names
            or "runs" in names
        ):
            continue

        card = snapshot_cache.get_card(workspace.pk, child.name)
        if card is None:
            try:
                cold_client = snapshot_cache.cold_load_client(client)
                with TouchedFileTracker() as tracker:
                    tracker.record(child.id, child.modified_time)
                    for f in opp_children:
                        tracker.record(f.id, f.modified_time)
                    card = load_opp_card(cold_client, opp_folder=child, opp_children=opp_children)
                access.overlay_workspace_display_name(card.opp, child.name, workspace=workspace)
                snapshot_cache.set_card(
                    workspace_id=workspace.pk,
                    slug=child.name,
                    card=card,
                    file_ids=tracker.file_ids,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("list_opp_cards: failed to load card for %r: %s", child.name, exc)
                continue
        else:
            access.overlay_workspace_display_name(card.opp, child.name, workspace=workspace)

        # Normalise last_activity_at (Drive ISO-8601 string) to a datetime.
        raw_ts = card.last_activity_at
        if raw_ts:
            try:
                updated_at = dt.datetime.fromisoformat(
                    raw_ts.replace("Z", "+00:00") if raw_ts.endswith("Z") else raw_ts
                )
            except ValueError:
                updated_at = _EPOCH
        else:
            updated_at = _EPOCH

        out.append({
            "slug": card.opp.slug,
            "title": card.opp.display_name,
            "current_phase": card.current_phase,
            "current_skill": card.current_step,
            "run_count": card.run_count,
            "last_run_id": card.opp.current_run_id,
            "updated_at": updated_at,
        })

    return out


@router.get(
    "",
    response=Page[OppCardOut],
    summary="List opps in workspace",
    openapi_extra={"x-mcp-expose": True},
)
def list_opps(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    offset: int = 0,
    limit: int = 100,
) -> Page[OppCardOut]:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    cards = list_opp_cards(workspace)
    return paginate(
        [OppCardOut.model_validate(c) for c in cards],
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Task 2.1.3 helpers — snapshot load
# ---------------------------------------------------------------------------


def load_opp_snapshot(workspace, slug: str, *, run_id: str | None = None) -> dict | None:
    """Load an OppSnapshot from Drive + cache and map it to an OppSnapshotOut-compatible dict.

    Wraps the existing workbench read path (snapshot_cache + load_opp).
    Returns None when the opp slug doesn't exist in Drive.

    The monkeypatch target in contract tests is this module-level function.

    Field mapping (OppSnapshot dataclass → OppSnapshotOut schema):
      slug           <- snap.opp.slug
      title          <- snap.opp.display_name
      runs           <- snap.runs_summary → list[OppRunOut]
      active_run_id  <- snap.current_run.run_id
      steps          <- snap.current_run.steps → list[StepSnapshotOut]
      pending_gates  <- []  (gates are step-level; top-level list not needed for v2)
      scorecard      <- None (scorecard is a separate endpoint in the legacy API)
      updated_at     <- latest step completed_at or epoch fallback
    """
    from apps.opps import access, drive_changes, snapshot_cache
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import load_opp
    from apps.opps.touched_tracker import TouchedFileTracker
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        return None

    try:
        inner = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound:
        log.warning("load_opp_snapshot: Drive not configured for workspace %s", workspace.slug)
        return None

    from apps.opps.drive_cache import CachedDriveClient
    client = CachedDriveClient(inner, bypass=False)

    # Invalidate stale cache entries via Drive Changes API.
    changed = drive_changes.observe(workspace, client)
    if changed:
        snapshot_cache.invalidate(changed)

    # Fast path: use cached snapshot.
    cached = snapshot_cache.get(workspace_id=workspace.pk, slug=slug, run_id=run_id)
    if cached is not None:
        access.overlay_workspace_display_name(cached.opp, slug, workspace=workspace)
        return _snapshot_to_dict(cached)

    # Cold load.
    bypass_client = snapshot_cache.cold_load_client(client)
    try:
        with TouchedFileTracker() as tracker:
            snap = load_opp(bypass_client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return None
    access.overlay_workspace_display_name(snap.opp, slug, workspace=workspace)
    snapshot_cache.set(
        workspace_id=workspace.pk, slug=slug, run_id=run_id,
        snap=snap, file_ids=tracker.file_ids,
    )
    return _snapshot_to_dict(snap)


def _snapshot_to_dict(snap) -> dict:
    """Map an OppSnapshot dataclass to a dict compatible with OppSnapshotOut.

    Kept deliberately minimal: only the fields declared in OppSnapshotOut.
    """
    import datetime as _dt

    # Build runs list from runs_summary (lightweight per-run metadata).
    runs: list[dict] = []
    for r in getattr(snap, "runs_summary", None) or []:
        raw_started = r.last_actor_at  # best proxy for run start time
        started_at: _dt.datetime
        if isinstance(raw_started, _dt.datetime):
            started_at = raw_started
        elif isinstance(raw_started, str) and raw_started:
            try:
                started_at = _dt.datetime.fromisoformat(
                    raw_started.replace("Z", "+00:00")
                )
            except ValueError:
                started_at = _EPOCH
        else:
            started_at = _EPOCH
        runs.append({
            "run_id": r.run_id,
            "label": r.run_id,
            "started_at": started_at,
            "finished_at": None,
            "is_active": (r.run_id == (snap.current_run.run_id if snap.current_run else None)),
            "scorecard": None,
        })

    # If runs_summary is empty, synthesise a single entry from current_run.
    if not runs and snap.current_run is not None:
        runs = [{
            "run_id": snap.current_run.run_id,
            "label": snap.current_run.run_id,
            "started_at": _EPOCH,
            "finished_at": None,
            "is_active": True,
            "scorecard": None,
        }]

    active_run_id = snap.current_run.run_id if snap.current_run else None

    # Build steps list from current_run.steps (StepSnapshot dataclass).
    steps: list[dict] = []
    if snap.current_run is not None:
        for s in snap.current_run.steps:
            steps.append({
                "skill": s.step.skill_name,
                "phase": s.step.phase or "",
                "status": s.step.status or "pending",
                "artifact_count": len(s.artifacts),
                "artifacts": [
                    {
                        "id": a.drive_file_id,
                        "name": a.name,
                        "mime_type": a.mime_type or "text/plain",
                        "size_bytes": a.size_bytes,
                        "url": a.drive_web_link,
                        "is_text": (
                            (a.mime_type or "").startswith("text/")
                            or a.name.endswith(".md")
                        ),
                        "preview": None,
                    }
                    for a in s.artifacts
                ],
                "verdicts": [],  # verdicts are per-skill; omit in v2 snapshot summary
                "gate": None,
                "preview": None,
            })

    # updated_at: use latest step completed_at or epoch.
    updated_at: _dt.datetime = _EPOCH
    if snap.current_run is not None:
        for s in snap.current_run.steps:
            raw_comp = s.step.completed_at
            if raw_comp:
                try:
                    ts = _dt.datetime.fromisoformat(
                        raw_comp.replace("Z", "+00:00")
                        if isinstance(raw_comp, str) and raw_comp.endswith("Z")
                        else str(raw_comp)
                    )
                    if ts > updated_at:
                        updated_at = ts
                except (ValueError, TypeError):
                    pass

    return {
        "slug": snap.opp.slug,
        "title": snap.opp.display_name,
        "runs": runs,
        "active_run_id": active_run_id,
        "steps": steps,
        "pending_gates": [],
        "scorecard": None,
        "updated_at": updated_at,
    }


# ---------------------------------------------------------------------------
# Task 2.1.3 — GET /w/{workspace_slug}/opps/{slug}
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}",
    summary="Opp Workbench snapshot",
    openapi_extra={"x-mcp-expose": True},
)
def get_opp(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: str | None = None,
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    snapshot = load_opp_snapshot(workspace, slug, run_id=run_id)
    if snapshot is None:
        raise ProblemError(404, "Opp not found", type_=TYPE_NOT_FOUND)
    payload = OppSnapshotOut.model_validate(snapshot).model_dump(mode="json")
    etag = compute_etag(payload)
    not_modified = maybe_not_modified(request, etag)
    if not_modified is not None:
        return not_modified
    response = JsonResponse(payload)
    response["ETag"] = etag
    return response


# ---------------------------------------------------------------------------
# Task 2.1.4 helpers — opp create
# ---------------------------------------------------------------------------


def create_opp_and_return_card(workspace, user, body: OppCreateIn) -> dict:
    """Create an opp via the existing creator and return an OppCardOut-compatible dict.

    Delegates to apps.opps.opp_creator.create_opp. The monkeypatch target
    in contract tests is this module-level function. Raises CreateOppError
    on slug collision or invalid input (callers map to 409 / 400).
    """
    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.opp_creator import create_opp

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise ProblemError(
            404, "ACE root folder not found", type_=TYPE_NOT_FOUND,
            detail="workspace has no drive_root_folder_id configured",
        )

    from apps.service_accounts.exceptions import ServiceAccountNotFound
    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise ProblemError(
            404, "Drive not configured", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc

    result = create_opp(
        drive=drive,
        ace_root_folder_id=ace_folder_id,
        owner=user,
        slug=body.slug,
        display_name=body.title,
        idea=body.idea,
        mode=body.mode,
        pdd=body.pdd,
        workspace=workspace,
    )
    return {
        "slug": result.slug,
        "title": body.title,
        "current_phase": None,
        "current_skill": None,
        "run_count": 1,
        "last_run_id": None,
        "updated_at": _EPOCH,
    }


# ---------------------------------------------------------------------------
# Task 2.1.4 — POST /w/{workspace_slug}/opps
# ---------------------------------------------------------------------------


@router.post("", summary="Create opp")
def create_opp_endpoint(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    body: OppCreateIn,
) -> HttpResponse:
    from apps.opps.opp_creator import CreateOppError

    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        card = create_opp_and_return_card(workspace, request.user, body)
    except CreateOppError as exc:
        if exc.code == "slug-taken":
            raise ProblemError(
                409, "Opp already exists", type_=TYPE_CONFLICT, detail=str(exc),
            ) from exc
        raise ProblemError(400, str(exc), type_=TYPE_VALIDATION, detail=exc.code) from exc
    payload = OppCardOut.model_validate(card).model_dump(mode="json")
    response = JsonResponse(payload, status=201)
    return response


# ---------------------------------------------------------------------------
# Task 2.1.5 helpers — opp patch
# ---------------------------------------------------------------------------


def patch_opp_and_return_card(workspace, slug: str, body: OppPatchIn) -> dict:
    """Apply PATCH body to OppWorkspace DB row and return OppCardOut-compatible dict.

    Currently supports: title (stored as display_name on OppWorkspace).
    Raises CreateOppError("opp-not-found", ...) if the slug doesn't exist on Drive
    (lightweight check via OppWorkspace; missing DB row for a valid Drive opp is
    materialised like the legacy patch_opp does with get_or_create).

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.opps.models import OppWorkspace
    from apps.opps.opp_creator import CreateOppError

    if body.title is None:
        # No fields to patch; treat as no-op but still verify membership.
        try:
            ow = OppWorkspace.objects.get(workspace=workspace, slug=slug)
        except OppWorkspace.DoesNotExist as exc:
            raise CreateOppError("opp-not-found", f"opp {slug!r} not found") from exc
        return {
            "slug": slug,
            "title": ow.display_name or slug,
            "current_phase": None,
            "current_skill": None,
            "run_count": 0,
            "last_run_id": None,
            "updated_at": _EPOCH,
        }

    ow, _ = OppWorkspace.objects.get_or_create(
        workspace=workspace,
        slug=slug,
        defaults={"display_name": slug},
    )
    ow.display_name = body.title
    ow.save(update_fields=["display_name", "updated_at"])
    return {
        "slug": slug,
        "title": ow.display_name,
        "current_phase": None,
        "current_skill": None,
        "run_count": 0,
        "last_run_id": None,
        "updated_at": _EPOCH,
    }


# ---------------------------------------------------------------------------
# Task 2.1.5 — PATCH /w/{workspace_slug}/opps/{slug}
# ---------------------------------------------------------------------------


@router.patch("/{slug}", summary="Update opp")
def update_opp(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    body: OppPatchIn,
) -> HttpResponse:
    from apps.opps.opp_creator import CreateOppError

    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        card = patch_opp_and_return_card(workspace, slug, body)
    except CreateOppError as exc:
        if exc.code == "opp-not-found":
            raise ProblemError(
                404, "Opp not found", type_=TYPE_NOT_FOUND, detail=str(exc),
            ) from exc
        raise ProblemError(400, str(exc), type_=TYPE_VALIDATION, detail=exc.code) from exc
    payload = OppCardOut.model_validate(card).model_dump(mode="json")
    return JsonResponse(payload, status=200)


# ---------------------------------------------------------------------------
# Task 2.1.6 helpers — opp delete
# ---------------------------------------------------------------------------


def delete_opp_by_slug(workspace, slug: str) -> None:
    """Delete an opp from Drive + cascade-delete linked sessions.

    Delegates to apps.opps.sync.delete_opp_folder and replicates the
    OppWorkspace + Session cleanup from the legacy delete_opp view.
    Raises FileNotFoundError when the opp doesn't exist in Drive.

    The monkeypatch target in contract tests is this module-level function.
    """
    from django.db import models, transaction

    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.models import OppWorkspace
    from apps.opps.sync import delete_opp_folder
    from apps.service_accounts.exceptions import ServiceAccountNotFound
    from apps.sessions.models import Session

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise FileNotFoundError(f"no opp named {slug!r} — ACE root folder not configured")

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise FileNotFoundError(f"Drive not configured: {exc}") from exc

    delete_opp_folder(drive, ace_folder_id=ace_folder_id, slug=slug)

    with transaction.atomic():
        Session.objects.filter(opp_slug=slug).filter(
            models.Q(workspace=workspace) | models.Q(workspace__isnull=True)
        ).delete()
        OppWorkspace.objects.filter(workspace=workspace, slug=slug).delete()


# ---------------------------------------------------------------------------
# Task 2.1.6 — DELETE /w/{workspace_slug}/opps/{slug}
# ---------------------------------------------------------------------------


@router.delete("/{slug}", summary="Delete opp")
def delete_opp(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        delete_opp_by_slug(workspace, slug)
    except FileNotFoundError as exc:
        raise ProblemError(
            404, "Opp not found", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# Task 2.1.7 helpers — list runs
# ---------------------------------------------------------------------------


def list_opp_runs_for_workspace(workspace, slug: str) -> list[dict]:
    """Return a list of run dicts shaped for OppRunOut.

    Wraps list_opp_runs from apps/opps/sync.py. Returns [] when the
    opp has no runs/ subfolder (legacy flat layout).

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import list_opp_runs
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        return []

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound:
        return []

    runs = list_opp_runs(drive, ace_root_folder_id=ace_folder_id, opp_slug=slug)
    out: list[dict] = []
    for r in runs:
        started_at: dt.datetime
        raw = r.last_actor_at
        if raw and isinstance(raw, str):
            try:
                started_at = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                started_at = _EPOCH
        elif isinstance(raw, dt.datetime):
            started_at = raw
        else:
            started_at = _EPOCH
        out.append({
            "run_id": r.run_id,
            "label": r.run_id,
            "started_at": started_at,
            "finished_at": None,
            "is_active": (r.lifecycle_status != "complete"),
            "scorecard": None,
        })
    return out


# ---------------------------------------------------------------------------
# Task 2.1.7 — GET /w/{workspace_slug}/opps/{slug}/runs
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/runs",
    response=Page[OppRunOut],
    summary="List runs for opp",
    openapi_extra={"x-mcp-expose": True},
)
def list_runs(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    offset: int = 0,
    limit: int = 50,
) -> Page[OppRunOut]:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    runs = list_opp_runs_for_workspace(workspace, slug)
    return paginate(
        [OppRunOut.model_validate(r) for r in runs],
        offset=offset,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Task 2.1.8 — GET /w/{workspace_slug}/opps/{slug}/runs/{run_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/runs/{run_id}",
    response=OppRunOut,
    summary="Run detail",
    openapi_extra={"x-mcp-expose": True},
)
def get_run(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: Annotated[str, Path()],
) -> OppRunOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    runs = list_opp_runs_for_workspace(workspace, slug)
    match = next((r for r in runs if r["run_id"] == run_id), None)
    if match is None:
        raise ProblemError(404, "Run not found", type_=TYPE_NOT_FOUND)
    return OppRunOut.model_validate(match)


# ---------------------------------------------------------------------------
# Task 2.1.9 helpers — delete run
# ---------------------------------------------------------------------------


def delete_run_by_id(workspace, slug: str, run_id: str) -> None:
    """Trash a single run folder via drive.

    Delegates to apps/opps/sync.delete_run_folder and clears workspace cache.
    Raises FileNotFoundError when the run doesn't exist.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.opps import access, snapshot_cache
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import delete_run_folder
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise FileNotFoundError(f"no opp named {slug!r} — ACE root folder not configured")

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise FileNotFoundError(f"Drive not configured: {exc}") from exc

    delete_run_folder(drive, ace_folder_id=ace_folder_id, opp_slug=slug, run_id=run_id)
    snapshot_cache.clear_workspace(workspace.pk)


# ---------------------------------------------------------------------------
# Task 2.1.9 — DELETE /w/{workspace_slug}/opps/{slug}/runs/{run_id}
# ---------------------------------------------------------------------------


@router.delete("/{slug}/runs/{run_id}", summary="Delete run")
def delete_run(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: Annotated[str, Path()],
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        delete_run_by_id(workspace, slug, run_id)
    except FileNotFoundError as exc:
        raise ProblemError(
            404, "Run not found", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc
    return HttpResponse(status=204)


# ---------------------------------------------------------------------------
# Task 2.1.10 helpers — step detail
# ---------------------------------------------------------------------------


def load_step_snapshot(
    workspace, slug: str, skill: str, *, run_id: str | None = None
) -> dict | None:
    """Load a single step from an OppSnapshot and return a StepSnapshotOut-compatible dict.

    Returns None when the opp doesn't exist, or a dict with 'not_found'
    key set to 'opp' or 'skill' for downstream disambiguation.

    The monkeypatch target in contract tests is this module-level function.
    """
    snap = load_opp_snapshot(workspace, slug, run_id=run_id)
    if snap is None:
        return None
    for step in snap.get("steps", []):
        if step["skill"] == skill:
            return step
    return {"_not_found": "skill"}


# ---------------------------------------------------------------------------
# Task 2.1.10 — GET /w/{workspace_slug}/opps/{slug}/steps/{skill}
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/steps/{skill}",
    response=StepSnapshotOut,
    summary="Step detail",
    openapi_extra={"x-mcp-expose": True},
)
def get_step(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    skill: Annotated[str, Path()],
    run_id: str | None = None,
) -> StepSnapshotOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    step = load_step_snapshot(workspace, slug, skill, run_id=run_id)
    if step is None:
        raise ProblemError(404, "Opp not found", type_=TYPE_NOT_FOUND)
    if step.get("_not_found") == "skill":
        raise ProblemError(
            404, f"Step {skill!r} not found", type_=TYPE_NOT_FOUND,
        )
    return StepSnapshotOut.model_validate(step)


# ---------------------------------------------------------------------------
# Task 2.1.11 helpers — artifact read (metadata)
# ---------------------------------------------------------------------------


def load_artifact_meta(
    workspace, slug: str, artifact_id: str, *, run_id: str | None = None
) -> dict | None:
    """Find an artifact by Drive file_id across all steps of an OppSnapshot.

    Returns an ArtifactOut-compatible dict, or None if not found.
    The monkeypatch target in contract tests is this module-level function.
    """
    snap = load_opp_snapshot(workspace, slug, run_id=run_id)
    if snap is None:
        return None
    for step in snap.get("steps", []):
        for artifact in step.get("artifacts", []):
            if artifact["id"] == artifact_id:
                return artifact
    return {"_not_found": True}


# ---------------------------------------------------------------------------
# Task 2.1.11 — GET /w/{workspace_slug}/opps/{slug}/artifacts/{artifact_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/artifacts/{artifact_id}",
    response=ArtifactOut,
    summary="Artifact metadata",
    openapi_extra={"x-mcp-expose": True},
)
def get_artifact(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    artifact_id: Annotated[str, Path()],
    run_id: str | None = None,
) -> ArtifactOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    artifact = load_artifact_meta(workspace, slug, artifact_id, run_id=run_id)
    if artifact is None:
        raise ProblemError(404, "Opp not found", type_=TYPE_NOT_FOUND)
    if artifact.get("_not_found"):
        raise ProblemError(
            404, f"Artifact {artifact_id!r} not found", type_=TYPE_NOT_FOUND,
        )
    return ArtifactOut.model_validate(artifact)


# ---------------------------------------------------------------------------
# Task 2.1.12 helpers — artifact binary download
# ---------------------------------------------------------------------------


def download_artifact_bytes(workspace, slug: str, artifact_id: str) -> tuple[bytes, str]:
    """Download Drive binary for a given artifact_id.

    Returns (content_bytes, mime_type). Raises FileNotFoundError when the
    opp or artifact doesn't exist. The monkeypatch target for contract tests.
    """
    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import load_opp
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise FileNotFoundError("ACE root folder not configured")

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise FileNotFoundError(f"Drive not configured: {exc}") from exc

    try:
        snap = load_opp(drive, ace_folder_id=ace_folder_id, slug=slug)
    except FileNotFoundError:
        raise

    # Search all steps for the artifact by id.
    for step_snap in snap.current_run.steps:
        for artifact in step_snap.artifacts:
            if artifact.drive_file_id == artifact_id:
                content = drive.get_content(artifact.drive_file_id, artifact.mime_type)
                return content.content.encode() if isinstance(
                    content.content, str
                ) else content.content, artifact.mime_type or "application/octet-stream"

    raise FileNotFoundError(f"artifact {artifact_id!r} not found")


# ---------------------------------------------------------------------------
# Task 2.1.12 — GET /w/{workspace_slug}/opps/{slug}/artifacts/{artifact_id}/download
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/artifacts/{artifact_id}/download",
    summary="Download artifact binary",
)
def download_artifact(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    artifact_id: Annotated[str, Path()],
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        data, mime_type = download_artifact_bytes(workspace, slug, artifact_id)
    except FileNotFoundError as exc:
        raise ProblemError(
            404, "Artifact not found", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc
    return HttpResponse(data, content_type=mime_type)


# ---------------------------------------------------------------------------
# Task 2.1.13 helpers — fork opp
# ---------------------------------------------------------------------------


def fork_opp_and_return(workspace, user, slug: str, body: OppForkIn) -> dict:
    """Fork a run in this opp. Returns OppForkOut-compatible dict.

    Delegates to apps.opps.opp_forker.fork_opp. Raises ForkOppError on
    expected error cases (callers map to 400/404/409).
    The monkeypatch target in contract tests is this module-level function.
    """
    from django.core.cache import cache

    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.opp_forker import fork_opp
    from apps.opps.views_write import _FORK_PROGRESS_TTL, _fork_progress_key
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise ProblemError(404, "ACE root folder not found", type_=TYPE_NOT_FOUND)

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise ProblemError(
            404, "Drive not configured", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc

    source_run_id = body.source_run_id or None
    progress_key = _fork_progress_key(workspace, slug, source_run_id or "")

    def _write_progress(payload: dict) -> None:
        cache.set(progress_key, payload, timeout=_FORK_PROGRESS_TTL)

    result = fork_opp(
        drive=drive,
        ace_root_folder_id=ace_folder_id,
        owner=user,
        source_slug=slug,
        fork_at_phase=body.fork_at_phase,
        source_run_id=source_run_id,
        workspace=workspace,
        progress_cb=_write_progress,
    )
    return {
        "slug": result.opp_slug,
        "run_id": result.new_run_id,
        "working_session_slug": result.working_session.slug,
    }


# ---------------------------------------------------------------------------
# Task 2.1.13 — POST /w/{workspace_slug}/opps/{slug}/fork
# ---------------------------------------------------------------------------


@router.post("/{slug}/fork", summary="Fork opp run")
def fork_opp_endpoint(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    body: OppForkIn,
) -> HttpResponse:
    from apps.opps.opp_forker import ForkOppError

    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        result = fork_opp_and_return(workspace, request.user, slug, body)
    except ForkOppError as exc:
        if exc.code in ("source-not-found", "source-run-not-found"):
            raise ProblemError(
                404, str(exc), type_=TYPE_NOT_FOUND, detail=exc.code,
            ) from exc
        if exc.code == "no-runs":
            raise ProblemError(
                409, str(exc), type_=TYPE_CONFLICT, detail=exc.code,
            ) from exc
        raise ProblemError(
            400, str(exc), type_=TYPE_VALIDATION, detail=exc.code,
        ) from exc
    payload = OppForkOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload, status=201)


# ---------------------------------------------------------------------------
# Task 2.1.14 — GET /w/{workspace_slug}/opps/{slug}/fork/status
# ---------------------------------------------------------------------------


@router.get("/{slug}/fork/status", response=ForkProgress, summary="Fork progress")
def fork_status(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    source_run_id: str = "",
) -> ForkProgress:
    from django.core.cache import cache

    from apps.opps.views_write import _fork_progress_key

    workspace = resolve_workspace_for_member(request, workspace_slug)
    key = _fork_progress_key(workspace, slug, source_run_id.strip())
    payload = cache.get(key)
    if payload is None:
        payload = {"status": "unknown"}
    return ForkProgress.model_validate(payload)


# ---------------------------------------------------------------------------
# Task 2.1.15 helpers — scorecard
# ---------------------------------------------------------------------------


def load_scorecard_for_opp(workspace, slug: str) -> dict | None:
    """Load opp-eval scorecard from Drive.

    Returns a ScorecardOut-compatible dict, an empty dict (no scorecard yet),
    or None (opp not found). The monkeypatch target in contract tests.
    """
    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import load_scorecard
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        return None

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound:
        return None

    try:
        sc = load_scorecard(drive, ace_folder_id=ace_folder_id, slug=slug)
    except FileNotFoundError:
        return None

    if sc.latest_verdict is None:
        return {}  # opp exists but has no scorecard yet

    v = sc.latest_verdict
    decided_at: dt.datetime
    raw_ts = v.evaluated_at or ""
    if raw_ts:
        try:
            decided_at = dt.datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        except ValueError:
            decided_at = _EPOCH
    else:
        decided_at = _EPOCH

    # Normalise score to 0-100.
    score = v.score or 0
    if score <= 10:
        score = int(score * 10)

    verdict_str = "pass" if v.passed else "fail"

    return {
        "score": min(max(0, score), 100),
        "verdict": verdict_str,
        "rationale": v.rationale or "",
        "trend": [],
        "decided_at": decided_at,
    }


# ---------------------------------------------------------------------------
# Task 2.1.15 — GET /w/{workspace_slug}/opps/{slug}/scorecard
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/scorecard",
    summary="Opp-eval scorecard",
    openapi_extra={"x-mcp-expose": True},
)
def get_scorecard(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: str | None = None,  # informational; scorecard is per-opp not per-run
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    sc = load_scorecard_for_opp(workspace, slug)
    if sc is None:
        raise ProblemError(404, "Opp not found", type_=TYPE_NOT_FOUND)
    if not sc:
        # Opp exists but no scorecard yet — return null.
        return JsonResponse(None, safe=False)
    payload = ScorecardOut.model_validate(sc).model_dump(mode="json")
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# Task 2.1.16 helpers — gate decision
# ---------------------------------------------------------------------------


def record_gate_decision(
    workspace, slug: str, skill: str, body: GateDecisionIn, user
) -> dict:
    """Write a gate decision to state.yaml in Drive.

    Reads the current state.yaml, updates the gates: map, writes it back.
    Returns a GateOut-compatible dict. Raises FileNotFoundError when opp
    doesn't exist.

    The monkeypatch target in contract tests is this module-level function.
    """
    import yaml as _yaml

    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.sync import _find_child, _find_child_folder
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise FileNotFoundError("ACE root folder not configured")

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise FileNotFoundError(f"Drive not configured: {exc}") from exc

    # Find opp folder.
    opp_folder = _find_child_folder(drive.list_files(ace_folder_id), slug)
    if opp_folder is None:
        raise FileNotFoundError(f"no opp named {slug!r}")

    # Find active run folder — look for runs/<latest> or flat state.yaml.
    opp_children = drive.list_files(opp_folder.id)
    runs_folder = _find_child_folder(opp_children, "runs")
    state_file = None

    if runs_folder is not None:
        run_folders = sorted(
            [f for f in drive.list_files(runs_folder.id)
             if f.mime_type == "application/vnd.google-apps.folder"],
            key=lambda f: f.name, reverse=True,
        )
        if run_folders:
            state_file = _find_child(drive.list_files(run_folders[0].id), "run_state.yaml")
    else:
        state_file = _find_child(opp_children, "run_state.yaml")

    if state_file is None:
        raise FileNotFoundError(f"no run_state.yaml for opp {slug!r}")

    content = drive.get_content(state_file.id, "text/plain").content
    state = _yaml.safe_load(content) or {}
    gates = state.get("gates") or {}
    now_str = dt.datetime.now(tz=dt.UTC).isoformat()
    gates[skill] = {
        "decision": body.decision,
        "decided_by": user.email,
        "decided_at": now_str,
        "note": body.note,
    }
    state["gates"] = gates
    drive.update_file(state_file.id, _yaml.dump(state), "text/plain")

    return {
        "skill": skill,
        "decision": body.decision,
        "decided_by": user.email,
        "decided_at": dt.datetime.fromisoformat(now_str),
        "note": body.note,
    }


# ---------------------------------------------------------------------------
# Task 2.1.16 — POST /w/{workspace_slug}/opps/{slug}/gates/{skill}
# ---------------------------------------------------------------------------


@router.post("/{slug}/gates/{skill}", summary="Record gate decision")
def record_gate(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    skill: Annotated[str, Path()],
    body: GateDecisionIn,
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        gate = record_gate_decision(workspace, slug, skill, body, request.user)
    except FileNotFoundError as exc:
        raise ProblemError(
            404, "Opp not found", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc
    payload = GateOut.model_validate(gate).model_dump(mode="json")
    return JsonResponse(payload, status=200)


# ---------------------------------------------------------------------------
# Task 2.1.17 helpers — multi-run compare
# ---------------------------------------------------------------------------


def compare_opp_runs(workspace, slug: str, run_ids: list[str]) -> dict:
    """Load multiple runs of an opp and return a comparison payload.

    The monkeypatch target in contract tests is this module-level function.
    """
    snapshots: list[dict] = []
    for rid in run_ids:
        snap = load_opp_snapshot(workspace, slug, run_id=rid)
        if snap is None:
            raise FileNotFoundError(f"opp {slug!r} not found")
        snapshots.append(snap)
    return {
        "slug": slug,
        "run_ids": run_ids,
        "snapshots": snapshots,
    }


# ---------------------------------------------------------------------------
# Task 2.1.17 — GET /w/{workspace_slug}/opps/{slug}/compare
# ---------------------------------------------------------------------------


@router.get("/{slug}/compare", response=OppCompareOut, summary="Multi-run comparison")
def compare_runs(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_ids: list[str] | None = None,
) -> OppCompareOut:

    workspace = resolve_workspace_for_member(request, workspace_slug)
    # Ninja passes multi-value query params as list when annotated correctly;
    # fall back to a manual parse from the raw query string.
    if not run_ids:
        raw = request.GET.getlist("run_ids")
        run_ids = [r.strip() for r in raw if r.strip()]
    if len(run_ids) < 2:
        raise ProblemError(
            400, "At least 2 run_ids required", type_=TYPE_VALIDATION,
        )
    try:
        result = compare_opp_runs(workspace, slug, run_ids)
    except FileNotFoundError as exc:
        raise ProblemError(
            404, "Opp not found", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc
    return OppCompareOut.model_validate(result)


# ---------------------------------------------------------------------------
# Task 2.1.18 helpers — seed-chat
# ---------------------------------------------------------------------------


def seed_chat_for_step(workspace, slug: str, user, body: SeedChatIn) -> dict:
    """Create a seed chat session for a step. Returns SeedChatOut-compatible dict.

    Delegates to apps/opps/seed.py::build_chat_seed and Session.create_with_owner.
    Raises ValueError when the step doesn't exist.
    The monkeypatch target in contract tests is this module-level function.
    """
    from django.db import transaction

    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.seed import build_chat_seed
    from apps.opps.sync import load_opp
    from apps.opps.views_session import _skill_md_relative_path
    from apps.service_accounts.exceptions import ServiceAccountNotFound
    from apps.sessions.models import Message, Session

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise FileNotFoundError("ACE root folder not configured")

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise FileNotFoundError(f"Drive not configured: {exc}") from exc

    run_id = body.run_id or None
    try:
        snap = load_opp(drive, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        raise

    access.overlay_workspace_display_name(snap.opp, slug, workspace=workspace)
    seed_body = build_chat_seed(
        snap,
        skill=body.step_skill,
        drive_client=drive,
        skill_md_path=_skill_md_relative_path(body.step_skill),
    )
    idd_drive_id = ""
    for step_snap in snap.current_run.steps:
        if step_snap.step.skill_name == "idea-to-pdd":
            for artifact in step_snap.artifacts:
                if artifact.name in ("pdd.md", "idd.md"):
                    idd_drive_id = artifact.drive_file_id
                    break

    with transaction.atomic():
        session = Session.create_with_owner(
            owner=user,
            title=f"{body.step_skill}: {slug}",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
            opp_run_id=snap.current_run.run_id,
            opp_step_skill=body.step_skill,
            idd_ref=idd_drive_id,
            workspace=workspace,
        )
        Message.objects.create(
            session=session,
            turn_index=0,
            role="system",
            sender_user=user,
            content={"type": "system", "source": "opps-discuss"},
            plaintext=seed_body,
            status="complete",
        )
    return {"session_slug": session.slug}


# ---------------------------------------------------------------------------
# Task 2.1.18 — POST /w/{workspace_slug}/opps/{slug}/actions/seed-chat
# ---------------------------------------------------------------------------


@router.post("/{slug}/actions/seed-chat", summary="Seed chat from step")
def seed_chat(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    body: SeedChatIn,
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        result = seed_chat_for_step(workspace, slug, request.user, body)
    except FileNotFoundError as exc:
        raise ProblemError(
            404, "Opp not found", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise ProblemError(
            404, str(exc), type_=TYPE_NOT_FOUND,
        ) from exc
    payload = SeedChatOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload, status=201)


# ---------------------------------------------------------------------------
# Task 2.1.19 helpers — health probe
# ---------------------------------------------------------------------------


def probe_opp_health(workspace, slug: str) -> dict:
    """Probe Drive reachability for this opp.

    Returns an OppHealthOut-compatible dict with reachable=True/False.
    Non-member workspaces are rejected upstream; this only surfaces
    Drive errors.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    now = dt.datetime.now(tz=dt.UTC)
    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        return {"reachable": False, "last_checked_at": now, "error": "no drive root configured"}

    try:
        drive = get_drive_client(workspace=workspace)
        drive.list_files(ace_folder_id)
        return {"reachable": True, "last_checked_at": now, "error": None}
    except ServiceAccountNotFound as exc:
        return {"reachable": False, "last_checked_at": now, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "last_checked_at": now, "error": str(exc)}


# ---------------------------------------------------------------------------
# Task 2.1.19 — GET /w/{workspace_slug}/opps/{slug}/health
# ---------------------------------------------------------------------------


@router.get("/{slug}/health", response=OppHealthOut, summary="Drive health probe")
def opp_health(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> OppHealthOut:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    result = probe_opp_health(workspace, slug)
    return OppHealthOut.model_validate(result)


# ---------------------------------------------------------------------------
# Task 2.1.20 helpers — snapshot cache invalidate
# ---------------------------------------------------------------------------


def invalidate_opp_snapshot_cache(workspace) -> None:
    """Clear all cached snapshots for this workspace.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.opps.snapshot_cache import clear_workspace
    clear_workspace(workspace.pk)


# ---------------------------------------------------------------------------
# Task 2.1.20 — POST /w/{workspace_slug}/opps/{slug}/snapshot/invalidate
# ---------------------------------------------------------------------------


@router.post("/{slug}/snapshot/invalidate", summary="Invalidate snapshot cache (admin)")
def invalidate_snapshot(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
) -> HttpResponse:
    workspace = resolve_workspace_for_member(request, workspace_slug)
    require_write_global(request)
    invalidate_opp_snapshot_cache(workspace)
    return HttpResponse(status=204)
