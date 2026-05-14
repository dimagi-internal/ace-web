"""Django Ninja v2 router for the opps Workbench surface."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated

from django.http import HttpRequest, HttpResponse, JsonResponse
from ninja import Path, Router

from apps.api_v2.auth import session_auth
from apps.api_v2.deps import resolve_workspace_for_member
from apps.api_v2.errors import TYPE_CONFLICT, TYPE_NOT_FOUND, TYPE_VALIDATION, ProblemError
from apps.api_v2.etag import compute_etag, maybe_not_modified
from apps.api_v2.pagination import Page, paginate

from .schemas import OppCardOut, OppCreateIn, OppSnapshotOut

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


@router.get("", response=Page[OppCardOut], summary="List opps in workspace")
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


@router.get("/{slug}", summary="Opp Workbench snapshot")
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

