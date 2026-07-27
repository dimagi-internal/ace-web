"""Django Ninja v2 router for the opps Workbench surface."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from ninja import Path, Router

from apps.api.auth import session_auth
from apps.api.deps import require_write_global, resolve_workspace_for_member
from apps.api.errors import (
    TYPE_CONFLICT,
    TYPE_NOT_FOUND,
    TYPE_VALIDATION,
    ProblemError,
)
from apps.api.etag import compute_etag, maybe_not_modified

from .schemas import (
    ArtifactOut,
    DecisionOverridesSaveIn,
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
    ScorecardOut,
    SeedChatIn,
    SeedChatOut,
    SeededRunIn,
    SeededRunOut,
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
      updated_at   <- card.last_activity_at (ISO-8601 string) or None.
                     Pre-2026-05-20 this used to fall back to Unix epoch
                     (1970-01-01) which the frontend then rendered as
                     "last 12/31/1969" on opp cards with no completed runs.
                     See #466 for the bug + fix; the frontend OppCard guards
                     on truthy `last_activity_at` so None renders nothing.
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

    # Compute phase/skill display indices once per request — they're
    # plugin-derived and shared across all cards. Used below to enrich
    # each card's runs_summary so the Opps-list phase-chip strip can
    # render "P{ordinal}" without per-card fan-out (#512).
    phase_meta = _phase_display_index()
    skill_phase_index = _skill_display_index()

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
            # #510 / #511: NO card-level freshness overlays. The list view
            # renders N cards per request; per-card Drive listings fan out
            # to N parallel calls and block page render on the slowest
            # (observed 8-12s at N=5). card.run_count falls back to the
            # cached value, which the Drive Changes API keeps roughly fresh
            # for normal use. See apps/opps/freshness_overlays.CARD_OVERLAYS.

        # Normalise last_activity_at (Drive ISO-8601 string) to a datetime.
        # When the opp has no completed run, raw_ts is None — pass that
        # through as None instead of falling back to the Unix epoch, which
        # the frontend would otherwise render as "last 12/31/1969". (#466)
        raw_ts = card.last_activity_at
        updated_at: dt.datetime | None
        if raw_ts:
            try:
                updated_at = dt.datetime.fromisoformat(
                    raw_ts.replace("Z", "+00:00") if raw_ts.endswith("Z") else raw_ts
                )
            except ValueError:
                updated_at = None
        else:
            updated_at = None

        # Produce the FULL legacy OppCard shape the frontend expects
        # (display_name, tags, labels, eval_score, etc.) — see
        # apps/opps/serializers.py::serialize_opp_card.
        from apps.opps.serializers import serialize_opp_card
        rich = serialize_opp_card(
            card.opp,
            card.current_run if hasattr(card, "current_run") else None,
        )
        # Add fields the lighter v2 OppCardOut consumers also use.
        rich["title"] = card.opp.display_name
        rich["current_phase"] = card.current_phase
        rich["current_step"] = card.current_step
        rich["current_skill"] = card.current_step
        rich["run_count"] = card.run_count
        rich["last_run_id"] = card.opp.current_run_id
        rich["updated_at"] = updated_at
        rich["last_activity_at"] = raw_ts
        rich["runs_summary"] = _serialize_card_runs_summary(
            getattr(card, "runs_summary", None) or [],
            phase_meta=phase_meta,
            skill_phase_index=skill_phase_index,
        )
        out.append(rich)

    return out


@router.get(
    "",
    response={200: dict},
    summary="List opps in workspace",
    openapi_extra={"x-mcp-expose": True},
)
def list_opps(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    offset: int = 0,
    limit: int = 100,
) -> HttpResponse:
    """Return the full legacy OppCard shape (display_name, tags, labels,
    eval_score, etc.) the frontend expects. We bypass OppCardOut's strict
    Pydantic schema and return the rich dict directly — the v2 minimal
    schema was a Phase 1 over-simplification."""
    workspace = resolve_workspace_for_member(request, workspace_slug)
    cards = list_opp_cards(workspace)
    items = list(cards[offset:offset + limit])
    return JsonResponse({
        "items": items,
        "total": len(cards),
        "offset": offset,
        "limit": limit,
    })


# ---------------------------------------------------------------------------
# Task 2.1.3 helpers — snapshot load
# ---------------------------------------------------------------------------


def load_rich_opp_snapshot(workspace, slug: str, *, run_id: str | None = None) -> dict | None:
    """Like load_opp_snapshot but returns the full legacy serializer shape
    (opp + current_run with steps + decisions + phases + pdd_body) the
    frontend's OppSnapshot type expects.

    Returns None when the opp slug doesn't exist in Drive.
    """
    from apps.opps import access, drive_changes, snapshot_cache
    from apps.opps.drive_client import get_drive_client
    from apps.opps.serializers import serialize_opp_snapshot
    from apps.opps.sync import load_opp
    from apps.opps.touched_tracker import TouchedFileTracker
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        return None
    try:
        inner = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound:
        log.warning("load_rich_opp_snapshot: Drive not configured for workspace %s", workspace.slug)
        return None
    from apps.opps.drive_cache import CachedDriveClient
    client = CachedDriveClient(inner, bypass=False)
    changed = drive_changes.observe(workspace, client)
    if changed:
        snapshot_cache.invalidate(changed)
    cached = snapshot_cache.get(workspace_id=workspace.pk, slug=slug, run_id=run_id)
    if cached is not None:
        access.overlay_workspace_display_name(cached.opp, slug, workspace=workspace)
        # #484 / #495: cache-hit path must still detect Drive listings that
        # grew externally (Changes API doesn't reliably report parent-folder
        # modifications when children are added). The registry refreshes each
        # listing-derived field on every cache hit. See
        # apps/opps/freshness_overlays.py.
        from apps.opps.freshness_overlays import (
            OverlayContext,
            apply_freshness_overlays,
        )
        apply_freshness_overlays(
            cached, client,
            context=OverlayContext(ace_folder_id=ace_folder_id, slug=slug),
        )
        result = serialize_opp_snapshot(cached)
        # Inject multi-player pending edits from Redis shared buffer
        from apps.opps.decisions_buffer import get_edits
        run_id_for_edits = run_id or (result.get("current_run") or {}).get("run_id", "")
        result["pending_edits"] = get_edits(slug, run_id_for_edits)
        # Durable overrides from inputs/decision-overrides.yaml — kept
        # fresh by the saved_overrides overlay above (#673 PR 2).
        result["saved_overrides"] = getattr(cached, "saved_overrides", {}) or {}
        return result
    bypass_client = snapshot_cache.cold_load_client(client)
    try:
        with TouchedFileTracker() as tracker:
            snap = load_opp(bypass_client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
            # Read inputs/decision-overrides.yaml inside the tracker so
            # the file id lands in the snapshot's tracked set — content
            # edits to it then invalidate this cache entry normally.
            # First-creation freshness is the overlay's job (#673 PR 2).
            from apps.opps.decision_overrides import fetch_saved_overrides
            try:
                snap.saved_overrides = fetch_saved_overrides(
                    bypass_client, opp_folder_id=snap.opp_folder_id,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("load_rich_opp_snapshot: saved-overrides read failed: %s", exc)
                snap.saved_overrides = {}
    except FileNotFoundError:
        return None
    access.overlay_workspace_display_name(snap.opp, slug, workspace=workspace)
    snapshot_cache.set(
        workspace_id=workspace.pk, slug=slug, run_id=run_id,
        snap=snap, file_ids=tracker.file_ids,
    )
    result = serialize_opp_snapshot(snap)
    # Inject multi-player pending edits from Redis shared buffer
    from apps.opps.decisions_buffer import get_edits
    run_id_for_edits = run_id or (result.get("current_run") or {}).get("run_id", "")
    result["pending_edits"] = get_edits(slug, run_id_for_edits)
    result["saved_overrides"] = snap.saved_overrides or {}
    return result


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
        # #484 / #495: refresh listing-derived fields on cache hit — see
        # apps/opps/freshness_overlays.py.
        from apps.opps.freshness_overlays import (
            OverlayContext,
            apply_freshness_overlays,
        )
        apply_freshness_overlays(
            cached, client,
            context=OverlayContext(ace_folder_id=ace_folder_id, slug=slug),
        )
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
    """Return the full Workbench payload — opp + current_run with steps +
    decisions + phases + pdd_body. Uses the legacy serializer which
    matches the frontend's OppSnapshot shape (the v2 minimal
    OppSnapshotOut schema was a Phase 1 over-simplification)."""
    workspace = resolve_workspace_for_member(request, workspace_slug)
    payload = load_rich_opp_snapshot(workspace, slug, run_id=run_id)
    if payload is None:
        raise ProblemError(404, "Opp not found", type_=TYPE_NOT_FOUND)
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
        # Newly created opp has no run yet — leave None so the UI doesn't
        # render an epoch-zero "last 12/31/1969" timestamp. (#466)
        "updated_at": None,
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
            # No run completed yet — None instead of epoch-zero. (#466)
            "updated_at": None,
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
        # No run completed yet — None instead of epoch-zero. (#466)
        "updated_at": None,
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


def _phase_display_index() -> dict[str, tuple[str, int]]:
    """Return {phase_name: (phase_display, phase_ordinal)} from the ACE plugin.

    Used to enrich RunSummary dicts on the way out so the frontend's
    OppCardRunsStrip can render "P{ordinal}" chips and human-readable
    phase labels in tooltips. Empty dict if the plugin can't be read —
    callers degrade to the bare phase slug.
    """
    from django.conf import settings  # noqa: PLC0415

    from apps.system.reader import load_system_overview  # noqa: PLC0415

    plugin_path = getattr(settings, "ACE_PLUGIN_PATH", "") or ""
    if not plugin_path:
        return {}
    overview = load_system_overview(plugin_path)
    return {
        p["name"]: (p.get("display_name") or p["name"], int(p.get("ordinal") or 0))
        for p in overview.get("phases", [])
    }


def _skill_display_index() -> dict[str, str]:
    """Return {skill_name: skill_display} from the ACE plugin's skill registry."""
    from apps.system.reader import get_skill_phase_index  # noqa: PLC0415

    return {
        name: entry.get("skill_display") or name
        for name, entry in get_skill_phase_index().items()
    }


def _serialize_card_runs_summary(
    runs: list,
    *,
    phase_meta: dict[str, tuple[str, int]],
    skill_phase_index: dict[str, str],
) -> list[dict]:
    """Serialize an OppCard.runs_summary list to the dict shape the Opps-list
    frontend expects on each card.

    Mirrors the enrichment ``list_opp_runs_for_workspace`` applies to its
    own RunSummary dicts (current_phase_display / current_phase_ordinal /
    latest_phase_done_display / latest_phase_done_ordinal /
    current_step_display) so the OppCardRunsStrip can render colored
    "P{ordinal}" chips without firing a per-card /opps/<slug>/runs call.
    See #512.

    Drops the internal ``folder_id`` field — the frontend doesn't need
    it and the legacy RunSummary type doesn't declare it.
    """
    from dataclasses import asdict  # noqa: PLC0415

    out: list[dict] = []
    for r in runs:
        rich = asdict(r)
        rich.pop("folder_id", None)
        cur_display, cur_ord = phase_meta.get(r.current_phase or "", (None, None))
        rich["current_phase_display"] = cur_display
        rich["current_phase_ordinal"] = cur_ord
        done_display, done_ord = phase_meta.get(r.latest_phase_done or "", (None, None))
        rich["latest_phase_done_display"] = done_display
        rich["latest_phase_done_ordinal"] = done_ord
        rich["current_step_display"] = skill_phase_index.get(r.current_step or "")
        # Normalise last_actor_at to ISO string (yaml may parse it as
        # datetime). Matches serialize_opp_snapshot's handling.
        raw_ts = rich.get("last_actor_at")
        if isinstance(raw_ts, dt.datetime):
            rich["last_actor_at"] = raw_ts.isoformat().replace("+00:00", "Z")
        out.append(rich)
    return out


def _run_execution_for(workspace, slug: str, run_id: str) -> dict | None:
    """The canopy execution state for one run, or None if it never went to canopy.

    Never raises: the runs list is the opp workbench's primary read and must not
    fail because canopy is having a bad minute.
    """
    from apps.sessions.models import Session

    session = (
        Session.objects.filter(workspace=workspace, opp_slug=slug, opp_run_id=run_id)
        .exclude(canopy_session_id="")
        .order_by("-created_at")
        .first()
    )
    if session is None:
        return None
    try:
        from apps.canopy.run_state import execution_state

        return execution_state(session)
    except Exception:  # noqa: BLE001
        return None


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
    from dataclasses import asdict
    phase_meta = _phase_display_index()
    skill_phase_index = _skill_display_index()
    for r in runs:
        # Dump the FULL RunSummary dataclass so the frontend gets
        # current_phase / phases_done / phases_total / last_actor_at /
        # lifecycle_status / latest_phase_done etc.
        rich = asdict(r)
        # Drop the internal folder_id — frontend doesn't need it and the
        # legacy RunSummary type doesn't declare it.
        rich.pop("folder_id", None)
        # Enrich phase / step references with the plugin's display name +
        # ordinal so the OppCardRunsStrip chip can render "P3" instead of
        # "—" and tooltips can show capitalized phase labels.
        cur_display, cur_ord = phase_meta.get(r.current_phase or "", (None, None))
        rich["current_phase_display"] = cur_display
        rich["current_phase_ordinal"] = cur_ord
        done_display, done_ord = phase_meta.get(r.latest_phase_done or "", (None, None))
        rich["latest_phase_done_display"] = done_display
        rich["latest_phase_done_ordinal"] = done_ord
        rich["current_step_display"] = skill_phase_index.get(r.current_step or "")
        # Add the lighter v2-style fields too (some consumers still use them).
        raw = r.last_actor_at
        started_at: dt.datetime
        if raw and isinstance(raw, str):
            try:
                started_at = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                started_at = _EPOCH
        elif isinstance(raw, dt.datetime):
            started_at = raw
        else:
            started_at = _EPOCH
        rich["label"] = r.run_id
        rich["started_at"] = started_at
        rich["finished_at"] = None
        rich["is_active"] = (r.lifecycle_status != "complete")
        rich["scorecard"] = None
        # Execution state (spec 2026-07-26, item 6). A run whose canopy turn no
        # runner can claim must not render as "queued" — that is exactly the
        # "looks like it is working" failure this exists to remove. None when the
        # run was never dispatched to canopy (legacy/local execution).
        # Read-only (`execution_state`, not `reconcile_session`): a list read
        # must not write.
        rich["execution"] = _run_execution_for(workspace, slug, r.run_id)
        out.append(rich)
    return out


# ---------------------------------------------------------------------------
# Task 2.1.7 — GET /w/{workspace_slug}/opps/{slug}/runs
# ---------------------------------------------------------------------------


@router.get(
    "/{slug}/runs",
    response={200: dict},
    summary="List runs for opp",
    openapi_extra={"x-mcp-expose": True},
)
def list_runs(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    offset: int = 0,
    limit: int = 50,
) -> HttpResponse:
    """Return the full RunSummary shape (current_phase + phases_done +
    last_actor_at + lifecycle_status + ...) the frontend renders for
    each row in the opp card's expanded RUNS panel. Bypasses OppRunOut's
    thin schema — the Phase 1 v2 shape was over-simplified."""
    workspace = resolve_workspace_for_member(request, workspace_slug)
    runs = list_opp_runs_for_workspace(workspace, slug)
    items = list(runs[offset:offset + limit])
    return JsonResponse({
        "items": items,
        "total": len(runs),
        "offset": offset,
        "limit": limit,
    })


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
        edits=[e.model_dump() for e in body.edits] if body.edits else None,
        mode=body.mode,
    )
    from apps.opps.decisions_buffer import clear_edits
    clear_edits(slug, source_run_id or "")
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
# Decision overrides — POST /w/{workspace_slug}/opps/{slug}/decision-overrides
# (issue #673 PR 2, spec docs/specs/2026-07-24-decision-review-save-design.md)
# ---------------------------------------------------------------------------


def save_decision_overrides_and_return(workspace, slug: str, body) -> dict:
    """Persist the source run's buffered decision edits to
    ``<opp>/inputs/decision-overrides.yaml``. No run is created.

    The body carries no edits — the Redis buffer is the authoritative
    set. The monkeypatch target in contract tests is this module-level
    function.
    """
    from apps.opps import access
    from apps.opps.decision_overrides import save_decision_overrides
    from apps.opps.drive_cache import CachedDriveClient
    from apps.opps.drive_client import get_drive_client
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise ProblemError(404, "ACE root folder not found", type_=TYPE_NOT_FOUND)
    try:
        inner = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise ProblemError(
            404, "Drive not configured", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc
    # bypass=True: reads go straight to Drive (we're about to write based
    # on them, so a 30s-stale listing risks clobbering a concurrent save),
    # while writes still invalidate the shared drive cache so the
    # read-side saved_overrides overlay sees the new file immediately.
    drive = CachedDriveClient(inner, bypass=True)
    return save_decision_overrides(
        drive=drive,
        ace_root_folder_id=ace_folder_id,
        opp_slug=slug,
        source_run_id=body.source_run_id,
    )


@router.post(
    "/{slug}/decision-overrides",
    response={200: dict},
    summary="Save buffered decision edits to Drive (inputs/decision-overrides.yaml)",
)
def save_decision_overrides_endpoint(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    body: DecisionOverridesSaveIn,
) -> HttpResponse:
    from apps.opps.decision_overrides import DecisionOverridesError

    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        result = save_decision_overrides_and_return(workspace, slug, body)
    except DecisionOverridesError as exc:
        if exc.code in ("opp-not-found", "run-not-found"):
            raise ProblemError(
                404, str(exc), type_=TYPE_NOT_FOUND, detail=exc.code,
            ) from exc
        raise ProblemError(
            409, str(exc), type_=TYPE_CONFLICT, detail=exc.code,
        ) from exc
    return JsonResponse(result)


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
    """Write a gate decision to run_state.yaml in Drive.

    Reads the current run_state.yaml, updates the gates: map, writes it back.
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

    # Find active run folder — look for runs/<latest> or flat run_state.yaml.
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
# Seeded run — POST /w/{workspace_slug}/opps/{slug}/actions/seeded-run
# ---------------------------------------------------------------------------


class NovaAuthInvalid(Exception):
    """Nova auth can't produce a working token — a seeded run including the
    Nova-dependent phase would halt at Phase 3 (ace-web#636)."""


# The phase whose skills need a live Nova MCP bearer.
NOVA_PHASE = "commcare-setup"


def nova_preflight(run_phases: list[int], phases: list[str]) -> None:
    """Raise NovaAuthInvalid when the run includes the Nova-dependent phase
    but NEITHER Nova auth path yields a working bearer (ace-web#636).

    Subprocess sessions authenticate via the user-scope PAT override
    (preferred) or the OAuth-blob fallback, so the gate accepts either.
    Skips silently when the plugin registry doesn't declare the phase (unit
    tests, degraded plugin install) — the preflight must never block a run
    the halt wouldn't have hit. The monkeypatch target in tests is this
    module-level function.
    """
    from apps.common import nova_auth_flow

    if NOVA_PHASE not in phases:
        return
    if (phases.index(NOVA_PHASE) + 1) not in run_phases:
        return
    if not nova_auth_flow.validate_any_token():
        raise NovaAuthInvalid(
            "Nova auth is not valid on either path (PAT override or OAuth "
            "blob) — the run would halt at Phase 3. Fix the rendered .env's "
            "NOVA_API_KEY or reconnect via /auth/nova/initiate/ (see "
            "docs/learnings/nova-mcp-oauth.md § Recovery)."
        )


def seed_run_for_opp(workspace, slug: str, user, body: SeededRunIn) -> dict:
    """Fork the golden run into a fresh, pre-shaped run, then create a CLI
    session whose first USER turn is a **plain resume** command.

    Run shape is **structural**, not flag-driven (ace#672). We fork the golden
    into a new run whose ``run_state.yaml`` already encodes the shape — seed
    prefix (phases below ``min(only)``) ``done``/``verdict: seeded``, the listed
    ordinals ``pending``, every other phase from the fork point onward
    ``skipped`` — and the user turn is the literal ``/ace:run <slug>/<new_run_id>``
    resume. The CLI backend's resume path runs the ``pending`` phases in order,
    steps over ``skipped``, and ends when none remain, so "only 3,4,6 then stop"
    needs no flag interpretation (the headless runner ignored the old
    ``--seed-from``/``--only`` flags — that's the bug this replaces).

    The run is loop-blind; the ``/ace:iterate`` client observes its run_state.
    The golden run is validated to exist by the fork (missing → 404).

    Returns ``{session_slug, assistant_message_id, run_id}`` — ``run_id`` is the
    new forked run the action minted. The route spawns the headless turn driver
    against ``assistant_message_id`` to actually execute the run (no WebSocket
    client needed). Raises FileNotFoundError when the opp or golden run can't be
    resolved, ValueError for a bad ``only`` allowlist. The monkeypatch target in
    contract tests is this module-level function.
    """
    from django.db import transaction
    from django.utils import timezone

    from apps.opps import access
    from apps.opps.drive_client import get_drive_client
    from apps.opps.opp_forker import ForkOppError, fork_opp
    from apps.opps.skills import all_phases
    from apps.service_accounts.exceptions import ServiceAccountNotFound
    from apps.sessions.models import Message, Session

    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise FileNotFoundError("ACE root folder not configured")

    try:
        drive = get_drive_client(workspace=workspace)
    except ServiceAccountNotFound as exc:
        raise FileNotFoundError(f"Drive not configured: {exc}") from exc

    # Resolve the target ordinals and the phase to fork at (= the lowest one).
    run_phases = sorted({int(p) for p in body.only.split(",")})
    phases = all_phases()
    min_ordinal = run_phases[0]
    if min_ordinal < 1 or min_ordinal > len(phases):
        raise ValueError(
            f"--only ordinal {min_ordinal} out of range 1..{len(phases)}"
        )
    fork_at_phase = phases[min_ordinal - 1]

    # Preflight: refuse to mint a run that will halt at Phase 3 because
    # Nova auth is dead (ace-web#636) — a month of seeded runs died that
    # way before anyone noticed. Only gates when the Nova-dependent phase
    # is actually selected.
    nova_preflight(run_phases, phases)

    # Fork the golden into a fresh run, shaped for a structural resume. No
    # session here — we drive our own headless seeded-run session below.
    try:
        fork = fork_opp(
            drive=drive,
            ace_root_folder_id=ace_folder_id,
            owner=user,
            source_slug=slug,
            fork_at_phase=fork_at_phase,
            source_run_id=body.golden_run_id,
            workspace=workspace,
            mode="keep-all",
            run_phases=run_phases,
            create_session=False,
        )
    except ForkOppError as exc:
        if exc.code in ("source-not-found", "no-runs", "source-run-not-found"):
            raise FileNotFoundError(str(exc)) from exc
        raise ValueError(str(exc)) from exc

    new_run_id = fork.new_run_id
    # Plain resume — the orchestrator reads the shaped run_state.yaml. Only flag
    # is --no-evals (default on for seeded/test runs): the per-step evals don't
    # gate the run, so skipping them saves ~7 min/run of LLM grading nobody
    # reads mid-test. Pass skip_evals=false to force inline grading.
    command = f"/ace:run {slug}/{new_run_id}"
    if body.skip_evals:
        command += " --no-evals"

    with transaction.atomic():
        session = Session.create_with_owner(
            owner=user,
            title=f"seeded-run: {slug}/{new_run_id} (--only {body.only})",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
            opp_run_id=new_run_id,
            workspace=workspace,
        )
        # The command goes in as a completed USER turn (turn_driver loads the
        # last user text to feed the backend), with an assistant placeholder
        # the headless driver fills in. Mirrors drafts.commit_active_draft.
        Message.objects.create(
            session=session,
            turn_index=0,
            role="user",
            sender_user=user,
            content={"text": command},
            plaintext=command,
            status="complete",
            completed_at=timezone.now(),
        )
        assistant_msg = Message.objects.create(
            session=session,
            turn_index=1,
            role="assistant",
            content={"text": ""},
            plaintext="",
            status="pending",
        )
    return {
        "session_slug": session.slug,
        "assistant_message_id": assistant_msg.id,
        "run_id": new_run_id,
    }


@router.post(
    "/{slug}/actions/seeded-run",
    summary="Launch a first-class seeded run (headless)",
    openapi_extra={"x-mcp-expose": True},
)
def seeded_run(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    body: SeededRunIn,
) -> HttpResponse:
    """Fork the golden into a fresh, pre-shaped run and start a plain resume —
    by launching ``manage.py drive_turn`` as a detached process that drives the
    turn through the SAME turn-driver + channel-layer broadcast path as a human
    typing into the workbench chat. Run shape is structural (ace#672): the
    forked run's ``run_state.yaml`` already encodes seed-prefix/target/skipped,
    so the seeded turn is a plain ``/ace:run <slug>/<run_id>`` resume, not a
    ``--seed-from``/``--only`` flag command. The session is a normal, openable,
    live session; the run is decoupled from this request's event loop (which is
    why an in-request ``create_task`` didn't work — ace-web#585). Exposed as an
    MCP tool (``x-mcp-expose``). Returns 202 (the run executes asynchronously).
    """
    from apps.canopy.run_dispatch import start_turn

    workspace = resolve_workspace_for_member(request, workspace_slug)
    try:
        result = seed_run_for_opp(workspace, slug, request.user, body)
    except NovaAuthInvalid as exc:
        raise ProblemError(
            409,
            "Nova authentication invalid",
            type_=TYPE_CONFLICT,
            detail=str(exc),
            extras={
                "code": "nova_auth_invalid",
                "reconnect_url": reverse("auth:nova_initiate"),
            },
        ) from exc
    except FileNotFoundError as exc:
        raise ProblemError(
            404, "Opp or golden run not found", type_=TYPE_NOT_FOUND, detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise ProblemError(
            404, str(exc), type_=TYPE_NOT_FOUND,
        ) from exc
    # Execute the turn. With CANOPY_RUN_EXECUTION on this enqueues a
    # session-targeted canopy Turn; with it off it spawns the legacy detached
    # `manage.py drive_turn` process (ace-web#585). Either way the run is
    # decoupled from this request's event loop.
    start_turn(result["assistant_message_id"])
    payload = SeededRunOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload, status=202)


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


# ---------------------------------------------------------------------------
# Public per-run summary — restored from legacy DRF (deleted in Phase 5)
# Mounted under /api/opps/public/ at the top level (see apps/api/api.py).
# ---------------------------------------------------------------------------


public_summary_router = Router(auth=None, tags=["opps-public"])


@public_summary_router.get(
    "/public/{workspace}/{slug}/runs/{run_id}/summary",
    response={200: dict},
    summary="Public per-run summary (no auth, stakeholder-facing)",
)
def public_opp_summary(
    request: HttpRequest,
    workspace: Annotated[str, Path()],
    slug: Annotated[str, Path()],
    run_id: Annotated[str, Path()],
) -> HttpResponse:
    """Stakeholder-facing per-run summary. AllowAny because share links
    are meant to circulate. Workspace + slug + run_id all in the URL —
    no leak-prevention 404 differentiation here, the URL is the secret.

    Cached 60 seconds in the Django cache to absorb refresh storms.
    """
    from django.core.cache import cache as _cache

    from apps.opps.drive_cache import CachedDriveClient
    from apps.opps.drive_client import get_drive_client
    from apps.opps.summary import build_summary_payload
    from apps.service_accounts.exceptions import ServiceAccountNotFound
    from apps.workspaces.models import Workspace

    cache_key = f"opp-summary:v1:{workspace}:{slug}:{run_id}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return JsonResponse(cached)

    try:
        ws = Workspace.objects.get(slug=workspace)
    except Workspace.DoesNotExist as exc:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND) from exc
    if not ws.drive_root_folder_id:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)

    try:
        client = CachedDriveClient(
            get_drive_client(workspace=ws),
            bypass=request.GET.get("force") == "1",
        )
    except ServiceAccountNotFound as exc:
        raise ProblemError(500, "Drive not configured", detail=str(exc)) from exc

    payload = build_summary_payload(
        client, workspace=ws, opp_slug=slug, run_id=run_id,
    )
    if payload is None:
        raise ProblemError(404, "Not found", type_=TYPE_NOT_FOUND)

    _cache.set(cache_key, payload, timeout=60)
    return JsonResponse(payload)


# ---------------------------------------------------------------------------
# Cross-opp compare — restored from legacy DRF (deleted in Phase 5).
# Frontend OppComparePage at /w/<ws>/opps/compare/<a>/<b> calls this.
# Distinct from the within-opp /opps/{slug}/compare which compares
# multiple RUNS of the same opp.
# ---------------------------------------------------------------------------


@router.get(
    "/cross-compare/{slug_a}/{slug_b}",
    response={200: dict},
    summary="Side-by-side comparison of two opps in the same workspace",
)
def cross_opp_compare(
    request: HttpRequest,
    workspace_slug: Annotated[str, Path()],
    slug_a: Annotated[str, Path()],
    slug_b: Annotated[str, Path()],
) -> HttpResponse:
    """Returns both OppSnapshots + a small summary with eval-score delta.
    Used by the cross-opp compare page (frontend OppComparePage)."""
    from apps.opps import access
    from apps.opps.drive_cache import CachedDriveClient
    from apps.opps.drive_client import get_drive_client
    from apps.opps.serializers import serialize_opp_snapshot
    from apps.opps.sync import load_opp, load_opp_card_by_slug
    from apps.service_accounts.exceptions import ServiceAccountNotFound

    if slug_a == slug_b:
        raise ProblemError(
            400, "Cannot compare an opp to itself", type_=TYPE_VALIDATION,
        )

    workspace = resolve_workspace_for_member(request, workspace_slug)
    ace_folder_id = access.resolve_ace_root_folder_id(workspace)
    if ace_folder_id is None:
        raise ProblemError(404, "ACE root folder not found", type_=TYPE_NOT_FOUND)

    try:
        client = CachedDriveClient(get_drive_client(workspace=workspace), bypass=False)
    except ServiceAccountNotFound as exc:
        raise ProblemError(500, "Drive not configured", detail=str(exc)) from exc

    try:
        snap_a = load_opp(client, ace_folder_id=ace_folder_id, slug=slug_a)
    except FileNotFoundError as exc:
        raise ProblemError(404, f"No opp named {slug_a!r}", type_=TYPE_NOT_FOUND) from exc
    try:
        snap_b = load_opp(client, ace_folder_id=ace_folder_id, slug=slug_b)
    except FileNotFoundError as exc:
        raise ProblemError(404, f"No opp named {slug_b!r}", type_=TYPE_NOT_FOUND) from exc

    access.overlay_workspace_display_name(snap_a.opp, slug_a, workspace=workspace)
    access.overlay_workspace_display_name(snap_b.opp, slug_b, workspace=workspace)

    score_a = score_b = None
    passed_a = passed_b = None
    try:
        card_a = load_opp_card_by_slug(client, ace_folder_id=ace_folder_id, slug=slug_a)
        score_a, passed_a = card_a.eval_score, card_a.eval_passed
    except Exception as exc:  # noqa: BLE001
        log.warning("cross_opp_compare: failed to load card for %r: %s", slug_a, exc)
    try:
        card_b = load_opp_card_by_slug(client, ace_folder_id=ace_folder_id, slug=slug_b)
        score_b, passed_b = card_b.eval_score, card_b.eval_passed
    except Exception as exc:  # noqa: BLE001
        log.warning("cross_opp_compare: failed to load card for %r: %s", slug_b, exc)

    score_delta = (
        score_b - score_a if score_a is not None and score_b is not None else None
    )

    return JsonResponse({
        "a": serialize_opp_snapshot(snap_a),
        "b": serialize_opp_snapshot(snap_b),
        "summary": {
            "score_a": score_a,
            "passed_a": passed_a,
            "score_b": score_b,
            "passed_b": passed_b,
            "score_delta": score_delta,
        },
    })
