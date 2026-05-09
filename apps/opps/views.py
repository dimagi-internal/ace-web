"""REST API views for the ACE opportunity Workbench."""
import logging

from django.conf import settings
from django.db import models, transaction
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps import drive_changes, snapshot_cache
from apps.opps.actions import ActionError, ActionPayload, inject_action
from apps.opps.drive_cache import CachedDriveClient
from apps.opps.drive_client import get_drive_client
from apps.opps.models import OppWorkspace
from apps.opps.opp_creator import SLUG_RE, CreateOppError, create_opp
from apps.opps.seed import build_chat_seed
from apps.opps.serializers import (
    normalize_score_pct,
    serialize_opp_snapshot,
    serialize_scorecard,
    serialize_step_snapshot,
)
from apps.opps.summary import build_summary_payload
from apps.opps.sync import (
    delete_opp_folder,
    list_opp_runs,
    load_opp,
    load_opp_card,
    load_opp_card_by_slug,
    load_scorecard,
)
from apps.opps.touched_tracker import TouchedFileTracker
from apps.service_accounts.exceptions import ServiceAccountNotFound
from apps.sessions.models import Message, Session
from apps.system.reader import (
    phase_display_names as _phase_display_names,
)
from apps.system.reader import (
    skill_display_names as _skill_display_names,
)
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import is_member, user_workspaces

log = logging.getLogger(__name__)


def _skill_display_name_lookup() -> dict[str, str]:
    """``{skill_slug: display_name}`` for the current ``ACE_PLUGIN_PATH``.

    Thin wrapper that resolves the path from settings and defers to the
    reader's process-cached ``skill_display_names``. Use this from hot
    paths in views; same data available via the reader for non-view code.
    """
    from django.conf import settings as _s

    return _skill_display_names(getattr(_s, "ACE_PLUGIN_PATH", "") or "")


def _phase_display_name_lookup() -> dict[str, str]:
    """``{phase_name: display_name}`` — settings-resolving wrapper around
    ``apps.system.reader.phase_display_names``."""
    from django.conf import settings as _s

    return _phase_display_names(getattr(_s, "ACE_PLUGIN_PATH", "") or "")


@api_view(["GET"])
@permission_classes([AllowAny])  # Scaffold-only; later views gate Drive access via _require_drive.
def health(request):
    """Scaffold sanity check. Used by tests in Task 1."""
    return Response(success_response({"status": "ok", "module": "opps"}))


def _resolve_ace_root_folder_id(workspace) -> str | None:
    """Return the Drive folder id of the workspace's ACE root folder.

    Each Workspace pins its own `drive_root_folder_id` (post-2026-04-27
    multi-tenancy). Returns None when no workspace is provided —
    callers treat that as "no workspace context" and return an empty
    list / 404 as appropriate.
    """
    if workspace is None:
        return None
    return workspace.drive_root_folder_id or None


def _resolve_workspace(request):
    """Return (workspace, error_response). Reads workspace identity from
    (in priority order): URL kwarg `workspace_slug`, request header
    `X-ACE-Workspace`, or — as a backward-compat fallback for the
    legacy `/api/opps/` paths — the user's first workspace.

    Membership is enforced; non-members get a 404 (not 403) so workspace
    existence isn't leaked.
    """
    if not request.user.is_authenticated:
        return None, Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )

    slug = request.headers.get("X-ACE-Workspace") or None

    if slug:
        try:
            ws = Workspace.objects.get(slug=slug)
        except Workspace.DoesNotExist:
            return None, Response(
                error_response("workspace not found", code="not-found"),
                status=404,
            )
        if not is_member(request.user, ws):
            return None, Response(
                error_response("workspace not found", code="not-found"),
                status=404,
            )
        return ws, None

    # Legacy fallback: bare /api/opps/ paths default to the user's most-recent
    # workspace. Phase B retires this once the frontend always provides
    # `workspace_slug` in the URL.
    ws = user_workspaces(request.user).first()
    if ws is None:
        return None, Response(
            error_response(
                "no workspace — create or join one first",
                code="no-workspace",
            ),
            status=403,
        )
    return ws, None


def _require_drive(request):
    """Return (workspace, drive_client, error_response). On error, the first
    two are None.

    The returned client is wrapped in :class:`CachedDriveClient` so repeated
    list/content reads within the cache TTL hit Redis instead of Drive.
    Pass ``?force=1`` on the request to bypass the cache for a hard refresh
    (writes still populate the cache so subsequent reads get the fresh data).
    """
    ws, err = _resolve_workspace(request)
    if err is not None:
        return None, None, err
    try:
        inner = get_drive_client(workspace=ws)
    except ServiceAccountNotFound as exc:
        return ws, None, Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )
    bypass = request.GET.get("force") == "1"
    return ws, CachedDriveClient(inner, bypass=bypass), None


def _overlay_workspace_display_name(manifest, slug: str, workspace=None) -> None:
    """Layer OppWorkspace DB metadata (display_name + tags) onto the
    Drive-derived manifest in place.

    Since 2026-04-20, display_name lives only on the OppWorkspace DB row —
    no longer in a Drive state.yaml (that ownership moved to the ACE plugin
    per docs/plans/2026-04-20-drop-multi-run-simplify.md). Tags are also
    DB-only (free-form grouping across sibling opps). Views that render
    opp metadata layer both over the Drive snapshot at the boundary so the
    sync module stays pure.

    The `workspace` arg scopes the lookup to the active Workspace —
    multiple Workspaces can have an opp with the same slug, so a global
    .get(slug=...) is no longer well-defined.
    """
    try:
        q = OppWorkspace.objects.only("display_name", "tags")
        if workspace is not None:
            q = q.filter(workspace=workspace)
        opp_ws = q.get(slug=slug)
    except OppWorkspace.DoesNotExist:
        return
    if opp_ws.display_name and opp_ws.display_name != slug:
        manifest.display_name = opp_ws.display_name
    manifest.tags = list(opp_ws.tags or [])


def _snapshot_etag(snap, *, pairs=None) -> str:
    """Compute the ETag for an OppSnapshot.

    Always hashes the serialized JSON payload so the ETag is stable
    across the cold-load and cached-hit paths. The ``pairs`` argument
    is accepted for forward-compat with any caller that supplies it, but
    is not used — json-body hashing is simpler and produces a
    consistent ETag regardless of which Drive modified_time values the
    client happened to see.
    """
    import hashlib
    import json
    body = json.dumps(serialize_opp_snapshot(snap), sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def _opp_list_impl(request):
    """Plain function form of the opp-list handler. Called directly by
    opp_collection (GET) to avoid double-wrapping with @api_view.

    Supports ``?tags=X,Y`` to filter to opps whose OppWorkspace.tags
    contains ALL of the listed tags (intersection — matches the "narrow
    down to iterations of the same idea" UX).
    """
    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(success_response([]))

    # Parse ?tags=X,Y — comma-separated, whitespace trimmed, empty tags
    # dropped. No tags param → no filter applied.
    raw_tags = request.GET.get("tags", "") or ""
    required_tags = {t.strip() for t in raw_tags.split(",") if t.strip()}

    # Resolve display-name lookups once per request, not per opp. Even with
    # the reader cache these dict comprehensions are wasteful in a hot loop,
    # and the prior implementation called load_system_overview per iteration.
    display_lookup = _skill_display_name_lookup()
    phase_lookup = _phase_display_name_lookup()

    # The root listing is the one Drive call that can wipe out the whole
    # response — every per-opp failure already falls back to a placeholder
    # card inside the loop, but a 5xx on the root list bubbles up as a
    # Django 500. The Drive client retries 5xx/429 internally; if we still
    # land here, surface a graceful error envelope instead of crashing.
    try:
        root_children = client.list_files(ace_folder_id)
    except Exception as exc:
        log.warning(
            "opp_list: root Drive listing failed for folder %s: %s",
            ace_folder_id, exc, exc_info=True,
        )
        return Response(
            error_response(
                "couldn't reach Google Drive — try again in a moment",
                code="drive-unavailable",
            ),
            status=503,
        )

    changed = drive_changes.observe(ws, client)
    if changed:
        snapshot_cache.invalidate(changed)

    cards: list[dict] = []
    for child in root_children:
        if child.mime_type != "application/vnd.google-apps.folder":
            continue
        opp_children = client.list_files(child.id)

        # Minimum signal that this folder is an opp. We accept five shapes:
        #   - idea.md at root (flat layout, the canonical pre-2026-05-02 shape)
        #   - state.yaml at root (legacy flat opps from before the
        #     2026-05-03 rename to run_state.yaml)
        #   - run_state.yaml at root (would only happen if a single-run
        #     opp was migrated in place — supported for completeness)
        #   - opp.yaml at root (multi-run layout — current ACE plugin)
        #   - runs/ subfolder (multi-run layout, in case opp.yaml is missing)
        # Without one of these, the folder is not an opp (e.g. the
        # "Program Design Docs (PDDs)" sibling folder under ACE/).
        names = {f.name for f in opp_children}
        if not (
            "idea.md" in names
            or "state.yaml" in names
            or "run_state.yaml" in names
            or "opp.yaml" in names
            or "runs" in names
        ):
            continue

        # Fast path: cached OppCard.
        card = None
        if not request.GET.get("force") == "1":
            card = snapshot_cache.get_card(ws.pk, child.name)

        if card is None:
            try:
                # Use a bypass=True client on the cold-load path to defeat
                # the underlying Drive TTL cache: changed-file content
                # mustn't be served from a stale per-call entry that was
                # written before the snapshot cache was invalidated.
                inner = client._inner if isinstance(client, CachedDriveClient) else client
                cold_client = CachedDriveClient(inner, bypass=True)
                with TouchedFileTracker() as tracker:
                    card = load_opp_card(cold_client, opp_folder=child, opp_children=opp_children)
                _overlay_workspace_display_name(card.opp, child.name, workspace=ws)
                snapshot_cache.set_card(
                    workspace_id=ws.pk,
                    slug=child.name,
                    card=card,
                    file_ids=tracker.file_ids,
                )
            except Exception as exc:
                # A malformed state.yaml or a Drive blip on one opp shouldn't
                # erase the whole list — but it shouldn't vanish silently
                # either. Log loudly and surface a placeholder card so the UI
                # can show "couldn't load" instead of pretending the opp
                # doesn't exist.
                log.warning(
                    "opp_list: failed to load card for %r: %s",
                    child.name, exc, exc_info=True,
                )
                cards.append({
                    "slug": child.name,
                    "display_name": child.name,
                    "labels": [],
                    "tags": [],
                    "created_at": None,
                    "created_by": None,
                    "current_run_id": None,
                    "current_phase": None,
                    "current_phase_display": None,
                    "current_step": None,
                    "current_step_display": None,
                    "status": "error",
                    "pending_gates": [],
                    "pending_gates_display": [],
                    "eval_score": None,
                    "eval_score_pct": None,
                    "eval_passed": None,
                    "last_activity_at": None,
                    "run_count": 1,
                    "error": {"message": str(exc) or exc.__class__.__name__},
                })
                continue
        else:
            _overlay_workspace_display_name(card.opp, child.name, workspace=ws)

        if required_tags and not required_tags.issubset(set(card.opp.tags)):
            continue

        pending_slugs = list(card.pending_gate_skills)
        cards.append({
            "slug": card.opp.slug,
            "display_name": card.opp.display_name,
            "labels": card.opp.labels,
            "tags": list(card.opp.tags),
            "created_at": card.opp.created_at,
            "created_by": card.opp.created_by,
            "current_run_id": card.opp.current_run_id,
            "current_phase": card.current_phase,
            "current_phase_display": (
                phase_lookup.get(card.current_phase)
                if card.current_phase
                else None
            ),
            "current_step": card.current_step,
            "current_step_display": (
                display_lookup.get(card.current_step)
                if card.current_step
                else None
            ),
            "status": card.status,
            "pending_gates": pending_slugs,
            "pending_gates_display": [
                display_lookup.get(s, s) for s in pending_slugs
            ],
            "eval_score": card.eval_score,
            "eval_score_pct": normalize_score_pct(card.eval_score),
            "eval_passed": card.eval_passed,
            "last_activity_at": card.last_activity_at,
            "run_count": card.run_count,
        })

    import hashlib
    import json
    body = json.dumps(cards, sort_keys=True, default=str)
    list_etag = f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
    if request.headers.get("If-None-Match") == list_etag:
        return HttpResponse(status=304, headers={"ETag": list_etag})
    resp = Response(success_response(cards))
    resp["ETag"] = list_etag
    return resp


def opp_create(request):
    """POST /api/opps/ — create a new opp. Called via opp_collection;
    not a standalone @api_view (the wrapping lives on opp_collection)."""
    # Authentication check (cheap) before any JSON parsing or Drive I/O.
    if not request.user.is_authenticated:
        return Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )
    # Use DRF's pre-parsed request.data — calling json.loads(request.body)
    # after DRF has already consumed the stream raises RawPostDataException
    # on the ASGI path (observed on labs).
    payload = request.data if isinstance(request.data, dict) else {}

    # Fast-fail on slug format before hitting Drive.
    slug = payload.get("slug", "")
    if not SLUG_RE.match(slug):
        return Response(
            error_response(f"invalid slug {slug!r}", code="invalid-slug"),
            status=400,
        )

    ws, client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        result = create_opp(
            drive=client,
            ace_root_folder_id=ace_folder_id,
            owner=request.user,
            slug=slug,
            display_name=payload.get("display_name", ""),
            idea=payload.get("idea", ""),
            mode=payload.get("mode", "review"),
            pdd=payload.get("pdd", ""),
            workspace=ws,
        )
    except CreateOppError as exc:
        status = 409 if exc.code == "slug-taken" else 400
        return Response(error_response(str(exc), code=exc.code), status=status)

    return Response(
        success_response({
            "slug": result.slug,
            "working_session_slug": result.working_session.slug,
        }),
        status=201,
    )


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def opp_collection(request):
    """Dispatches GET to the list reader and POST to the create handler."""
    if request.method == "POST":
        return opp_create(request)
    return _opp_list_impl(request)


def delete_opp(request, slug: str):
    """Handle DELETE. Called from workbench() when request.method == 'DELETE'.
    Not decorated with @api_view — workbench() carries the decorator."""
    ws, client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        delete_opp_folder(client, ace_folder_id=ace_folder_id, slug=slug)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )

    with transaction.atomic():
        # Cascade-delete linked Sessions. Match by opp_slug AND
        # (workspace=ws OR workspace IS NULL) — the latter captures
        # legacy sessions that pre-date the workspace FK and weren't
        # backfilled because they were created without an opp tie.
        Session.objects.filter(opp_slug=slug).filter(
            models.Q(workspace=ws) | models.Q(workspace__isnull=True)
        ).delete()
        OppWorkspace.objects.filter(workspace=ws, slug=slug).delete()

    return Response(status=204)


def patch_opp(request, slug: str):
    """PATCH /api/opps/<slug> — update mutable OppWorkspace fields.

    Currently supports: `tags` (replaces the full list). Lazily
    materializes an OppWorkspace row if the opp folder exists on Drive
    but no DB row does — same shape as opp_working_session does.
    """
    if not request.user.is_authenticated:
        return Response(
            error_response("auth required", code="auth-required"), status=401
        )
    ws, err = _resolve_workspace(request)
    if err is not None:
        return err
    body = request.data if isinstance(request.data, dict) else {}

    # Validate tags: list of short strings, each cleaned up (strip + drop blanks).
    raw_tags = body.get("tags")
    if raw_tags is None or not isinstance(raw_tags, list):
        return Response(
            error_response("tags must be a list of strings", code="invalid-tags"),
            status=400,
        )
    cleaned: list[str] = []
    for t in raw_tags:
        if not isinstance(t, str):
            return Response(
                error_response("tags must be a list of strings", code="invalid-tags"),
                status=400,
            )
        stripped = t.strip()
        if stripped and len(stripped) <= 64 and stripped not in cleaned:
            cleaned.append(stripped)

    workspace, _ = OppWorkspace.objects.get_or_create(
        workspace=ws,
        slug=slug,
        defaults={"display_name": slug, "created_by": request.user},
    )
    workspace.tags = cleaned
    workspace.save(update_fields=["tags", "updated_at"])

    return Response(success_response({"slug": slug, "tags": cleaned}))


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AllowAny])  # Drive availability enforced via _require_drive
def workbench(request, slug: str):
    if request.method == "DELETE":
        return delete_opp(request, slug)
    if request.method == "PATCH":
        return patch_opp(request, slug)

    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    run_id = request.GET.get("run_id") or None
    force = request.GET.get("force") == "1"

    # Validate cache against Drive Changes API, serve cached if valid.
    changed = drive_changes.observe(ws, client)
    if changed:
        snapshot_cache.invalidate(changed)

    if not force:
        cached = snapshot_cache.get(workspace_id=ws.pk, slug=slug, run_id=run_id)
        if cached is not None:
            _overlay_workspace_display_name(cached.opp, slug, workspace=ws)
            etag = _snapshot_etag(cached)
            if request.headers.get("If-None-Match") == etag:
                return HttpResponse(status=304, headers={"ETag": etag})
            resp = Response(success_response(serialize_opp_snapshot(cached)))
            resp["ETag"] = etag
            return resp

    # Cold-load path: bypass the drive-level TTL cache so we always read
    # fresh content after a cache miss or force=1. The CachedDriveClient
    # wrapping was done in _require_drive with bypass keyed to ?force; here
    # we need bypass=True unconditionally so changed-file content isn't
    # served from a stale TTL entry. We reconstruct from the inner client.
    inner = client._inner if isinstance(client, CachedDriveClient) else client
    bypass_client = CachedDriveClient(inner, bypass=True)

    try:
        with TouchedFileTracker() as tracker:
            snap = load_opp(bypass_client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )
    _overlay_workspace_display_name(snap.opp, slug, workspace=ws)
    snapshot_cache.set(
        workspace_id=ws.pk, slug=slug, run_id=run_id,
        snap=snap, file_ids=tracker.file_ids,
    )
    etag = _snapshot_etag(snap)
    resp = Response(success_response(serialize_opp_snapshot(snap)))
    resp["ETag"] = etag
    return resp


@api_view(["GET"])
@permission_classes([AllowAny])
def runs_list(request, slug: str):
    """GET /api/opps/<slug>/runs — list runs for an opp, newest-first.

    Powers the frontend RunSelector dropdown. Returns an empty list (not 404)
    when the opp exists but has no ``runs/`` subfolder (legacy flat layout).
    """
    ws, client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )
    runs = list_opp_runs(client, ace_root_folder_id=ace_folder_id, opp_slug=slug)
    return Response(success_response([
        {
            "run_id": r.run_id,
            "folder_id": r.folder_id,
            "current_phase": r.current_phase,
            "current_step": r.current_step,
            "mode": r.mode,
            "last_actor": r.last_actor,
            "last_actor_at": r.last_actor_at,
        } for r in runs
    ]))


@api_view(["GET"])
@permission_classes([AllowAny])
def multi_run_summary(request, slug: str):
    """GET /api/opps/<slug>/multi-run-summary — per-run aggregates.

    Powers the cross-run views (Phase, Heatmap, Diff). Loads up to the
    most recent N runs (default 8) and returns:

      - per_run: list of {run_id, started_at, status, mean_score,
                          phase_scores: {phase: mean}, skill_scores:
                          {skill: score}, gate_pending_count, ...}
      - skill_index: ordered list of {skill_name, display_name, phase,
                          phase_display, ordinal, has_judge}

    First load is expensive (one full ``load_opp`` per run, ~5s each
    cold); the Drive cache makes subsequent requests sub-second. The
    response is also cached for OPPS_DRIVE_CACHE_SECONDS so consecutive
    page loads of the cross-run views land in single-digit ms even
    when the per-snapshot cache misses.
    """
    from django.core.cache import cache as _cache

    ws, client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        limit = int(request.GET.get("limit", "8"))
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(limit, 20))
    force = request.GET.get("force") == "1"

    cache_key = f"opp-multi-run-summary:v1:{ws.slug}:{slug}:{limit}"
    if not force:
        hit = _cache.get(cache_key)
        if hit is not None:
            return Response(success_response(hit))

    runs = list_opp_runs(client, ace_root_folder_id=ace_folder_id, opp_slug=slug)
    if not runs:
        return Response(success_response({"per_run": [], "skill_index": []}))
    runs = runs[:limit]

    from apps.opps.skills import SKILL_REGISTRY
    from apps.system.reader import load_system_overview

    overview = load_system_overview(getattr(settings, "ACE_PLUGIN_PATH", "") or "")
    phase_lookup = {p["name"]: p for p in (overview.get("phases") or [])}
    skill_phase_lookup = {
        s["name"]: s.get("phase") for s in (overview.get("skills") or [])
    }
    skill_display_lookup = {
        s["name"]: s.get("display_name") for s in (overview.get("skills") or [])
    }
    skill_has_judge = {
        s["name"]: bool(s.get("has_judge")) for s in (overview.get("skills") or [])
    }

    skill_index = []
    for s in SKILL_REGISTRY:
        phase = skill_phase_lookup.get(s.name) or s.phase
        phase_meta = phase_lookup.get(phase) or {}
        skill_index.append({
            "skill_name": s.name,
            "display_name": skill_display_lookup.get(s.name) or s.name,
            "phase": phase,
            "phase_display": phase_meta.get("display_name") or phase,
            "phase_ordinal": phase_meta.get("ordinal") or 0,
            "ordinal": s.ordinal,
            "has_judge": skill_has_judge.get(s.name, False),
        })

    per_run = []
    for r in runs:
        try:
            snap = load_opp(
                client, ace_root_folder_id=ace_folder_id,
                opp_slug=slug, run_id=r.run_id,
            )
        except FileNotFoundError:
            continue
        run = snap.current_run
        skill_scores: dict[str, float | None] = {}
        skill_passed: dict[str, bool | None] = {}
        skill_status: dict[str, str] = {}
        gate_pending = 0
        complete_count = 0
        scored_values: list[float] = []
        phase_scored: dict[str, list[float]] = {}
        phase_complete: dict[str, int] = {}
        phase_total: dict[str, int] = {}

        for step in run.steps:
            phase = skill_phase_lookup.get(step.step.skill_name) or step.step.phase
            phase_total[phase] = phase_total.get(phase, 0) + 1
            j = step.judge
            score_pct = None
            if j is not None and j.score is not None:
                # Match serializer normalization (0-100).
                score_pct = (
                    j.score if j.score > 10 else j.score * 10.0
                )
                scored_values.append(score_pct)
                phase_scored.setdefault(phase, []).append(score_pct)
            skill_scores[step.step.skill_name] = score_pct
            skill_passed[step.step.skill_name] = j.passed if j else None
            skill_status[step.step.skill_name] = step.step.status
            if step.step.status == "complete":
                complete_count += 1
                phase_complete[phase] = phase_complete.get(phase, 0) + 1
            if step.step.status == "gate-pending":
                gate_pending += 1

        mean_score = (
            sum(scored_values) / len(scored_values) if scored_values else None
        )
        phase_scores: dict[str, dict] = {}
        for phase in phase_total:
            scored = phase_scored.get(phase) or []
            phase_scores[phase] = {
                "mean_score": (sum(scored) / len(scored)) if scored else None,
                "complete": phase_complete.get(phase, 0),
                "total": phase_total[phase],
            }

        per_run.append({
            "run_id": r.run_id,
            "mode": r.mode,
            "started_at": run.started_at,
            "last_actor_at": r.last_actor_at,
            "current_phase": r.current_phase,
            "current_step": r.current_step,
            "mean_score": mean_score,
            "complete_count": complete_count,
            "total_count": len(run.steps),
            "gate_pending_count": gate_pending,
            "phase_scores": phase_scores,
            "skill_scores": skill_scores,
            "skill_passed": skill_passed,
            "skill_status": skill_status,
        })

    payload = {"per_run": per_run, "skill_index": skill_index}
    _cache.set(
        cache_key, payload,
        timeout=getattr(settings, "OPPS_DRIVE_CACHE_SECONDS", 30),
    )
    return Response(success_response(payload))


@api_view(["GET"])
@permission_classes([AllowAny])
def step_detail(request, slug: str, run_id: str, skill: str):
    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )
    _overlay_workspace_display_name(snap.opp, slug, workspace=ws)

    step_snap = next(
        (s for s in snap.current_run.steps if s.step.skill_name == skill), None
    )
    if step_snap is None:
        return Response(
            error_response(f"no step {skill!r} in run {run_id!r}", code="step-not-found"),
            status=404,
        )

    # Fetch the primary artifact body so the frontend can show it inline.
    # A single artifact failure shouldn't blank out the whole step view,
    # but it shouldn't be silent either — log so a Drive permission /
    # 503 / content-decode bug shows up in operator logs.
    primary_body = ""
    bodies: dict[str, str] = {}
    for artifact in step_snap.artifacts:
        try:
            content = client.get_content(artifact.drive_file_id, artifact.mime_type)
            bodies[artifact.path] = content.content
        except Exception as exc:
            log.warning(
                "step_detail: failed to read artifact %s for %s/%s: %s",
                artifact.path, slug, skill, exc, exc_info=True,
            )
            continue
    if step_snap.artifacts:
        primary_body = bodies.get(step_snap.artifacts[0].path, "")

    payload = serialize_step_snapshot(step_snap, bodies=bodies)
    payload["primary_body"] = primary_body[:20000]  # cap at ~200 lines
    return Response(success_response(payload))


@api_view(["GET"])
@permission_classes([AllowAny])
def artifact_body(request, slug: str, run_id: str, skill: str, artifact_name: str):
    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )
    _overlay_workspace_display_name(snap.opp, slug, workspace=ws)

    step_snap = next(
        (s for s in snap.current_run.steps if s.step.skill_name == skill), None
    )
    if step_snap is None:
        return Response(
            error_response(f"no step {skill!r}", code="step-not-found"), status=404
        )

    artifact = next(
        (a for a in step_snap.artifacts if a.name == artifact_name), None
    )
    if artifact is None:
        return Response(
            error_response(f"no artifact {artifact_name!r}", code="artifact-not-found"),
            status=404,
        )

    content = client.get_content(artifact.drive_file_id, artifact.mime_type)
    # Serve as HttpResponse (not DRF Response) to avoid wrapping a file body
    # in the envelope. The envelope is for JSON; this is raw content.
    return HttpResponse(content.content, content_type=artifact.mime_type or "text/plain")


@api_view(["GET"])
@permission_classes([AllowAny])
def scorecard(request, slug: str):
    """Run-level opp-eval scorecard + trend for the Workbench header.

    Reads ``verdicts/opp-eval-*.yaml`` and ``scorecards/`` from the opp's
    Drive folder. Returns an all-empty payload (no 404) when opp-eval
    hasn't run yet — opp-eval is ad-hoc, not part of the default pipeline.
    """
    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        sc = load_scorecard(client, ace_folder_id=ace_folder_id, slug=slug)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )

    return Response(success_response(serialize_scorecard(sc)))


def _count_pending_gates(snap) -> int:
    """Count gates whose latest decision is 'pending' on a step snapshot."""
    return sum(
        1
        for s in snap.current_run.steps
        if s.gates and s.gates[-1].decision == "pending"
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def opp_compare(request, slug_a: str, slug_b: str):
    """Side-by-side comparison of two opps in the same workspace.

    Loads both OppSnapshots plus an opp-eval summary for each, and
    returns a small `summary` block with score / pending-gate deltas
    so the frontend can render the "did the new run improve?" banner
    without re-deriving anything.
    """
    if slug_a == slug_b:
        return Response(
            error_response(
                "cannot compare an opp to itself", code="same-opp",
            ),
            status=400,
        )

    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap_a = load_opp(client, ace_folder_id=ace_folder_id, slug=slug_a)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug_a!r}", code="opp-not-found"),
            status=404,
        )
    try:
        snap_b = load_opp(client, ace_folder_id=ace_folder_id, slug=slug_b)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug_b!r}", code="opp-not-found"),
            status=404,
        )

    _overlay_workspace_display_name(snap_a.opp, slug_a, workspace=ws)
    _overlay_workspace_display_name(snap_b.opp, slug_b, workspace=ws)

    # Pull eval scores via the card helper (cheap follow-up listing per opp).
    # Tolerate failure: a missing/malformed eval shouldn't 500 the compare view.
    try:
        card_a = load_opp_card_by_slug(client, ace_folder_id=ace_folder_id, slug=slug_a)
        score_a, passed_a = card_a.eval_score, card_a.eval_passed
    except Exception as exc:  # noqa: BLE001
        log.warning("compare: failed to load card for %r: %s", slug_a, exc)
        score_a, passed_a = None, None
    try:
        card_b = load_opp_card_by_slug(client, ace_folder_id=ace_folder_id, slug=slug_b)
        score_b, passed_b = card_b.eval_score, card_b.eval_passed
    except Exception as exc:  # noqa: BLE001
        log.warning("compare: failed to load card for %r: %s", slug_b, exc)
        score_b, passed_b = None, None

    pending_a = _count_pending_gates(snap_a)
    pending_b = _count_pending_gates(snap_b)

    score_delta = (
        score_b - score_a if score_a is not None and score_b is not None else None
    )

    return Response(success_response({
        "a": serialize_opp_snapshot(snap_a),
        "b": serialize_opp_snapshot(snap_b),
        "summary": {
            "score_a": score_a,
            "passed_a": passed_a,
            "score_b": score_b,
            "passed_b": passed_b,
            "score_delta": score_delta,
            "pending_gates_a": pending_a,
            "pending_gates_b": pending_b,
            "pending_gates_delta": pending_b - pending_a,
        },
    }))


def _skill_md_relative_path(skill: str) -> str:
    """Return the path of a skill's SKILL.md relative to the ace plugin repo root.

    The ACE plugin lays skills out as `skills/<skill-name>/SKILL.md`.
    """
    return f"skills/{skill}/SKILL.md"


@api_view(["POST"])
@permission_classes([AllowAny])
def discuss(request, slug: str, run_id: str, skill: str):
    """Create a new ace-web chat Session linked to this opp/run/step."""
    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )
    _overlay_workspace_display_name(snap.opp, slug, workspace=ws)

    workbench_url = request.build_absolute_uri(
        f"/w/{ws.slug}/opps/{slug}/runs/{run_id}/steps/{skill}"
    )

    try:
        seed_body = build_chat_seed(
            snap,
            skill=skill,
            drive_client=client,
            skill_md_path=_skill_md_relative_path(skill),
            workbench_url=workbench_url,
        )
    except ValueError as exc:
        return Response(
            error_response(str(exc), code="step-not-found"), status=404
        )

    # Resolve the PDD drive file id for session.idd_ref (column name preserved
    # for data-migration reasons; the content it now points at is pdd.md).
    idd_drive_id = ""
    for step_snap in snap.current_run.steps:
        if step_snap.step.skill_name == "idea-to-pdd":
            for artifact in step_snap.artifacts:
                # Accept both during the IDD→PDD rename transition.
                if artifact.name in ("pdd.md", "idd.md"):
                    idd_drive_id = artifact.drive_file_id
                    break
    # Fall back to the top-level pdd.md at the opp root if the idea-to-pdd step
    # didn't capture it as an artifact.
    # (Top-level pdd.md lookup happens inside sync.load_opp but we didn't
    # surface its file id. It would be a cheap enhancement to add that.)

    with transaction.atomic():
        session = Session.create_with_owner(
            owner=request.user,
            title=f"{skill}: {slug}",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
            opp_run_id=run_id,
            opp_step_skill=skill,
            idd_ref=idd_drive_id,
            workspace=ws,
        )
        Message.objects.create(
            session=session,
            turn_index=0,
            role="system",
            sender_user=request.user,
            content={"type": "system", "source": "opps-discuss"},
            plaintext=seed_body,
            status="complete",
        )

    return Response(
        success_response({"session_slug": session.slug}),
        status=201,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def step_chats(request, slug: str, run_id: str, skill: str):
    """List prior ace-web chat sessions linked to this opp/run/step.

    Returns BOTH:
      - Step-specific sessions (full match on opp_slug + run_id + skill) —
        typically "Discuss in chat" seeds, with ``kind='step'``
      - Opp-wide sessions (opp_slug match, but no step_skill on the Session) —
        typically uploaded transcripts from ``/ace:run --ace-web-url`` and
        the opp's working session, with ``kind='opp'``

    Step-specific chats are listed first. Both buckets share the same
    response shape (a flat list) so existing frontend rendering keeps
    working — the ``kind`` field lets the UI render a small badge.
    """
    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    from apps.sessions.serializers import _truncate_preview
    from apps.sessions.views import _annotate_first_user_plaintext

    step_chats_qs = _annotate_first_user_plaintext(
        Session.objects
        .filter(opp_slug=slug, opp_run_id=run_id, opp_step_skill=skill)
        .order_by("-updated_at")
    )[:20]
    opp_chats_qs = _annotate_first_user_plaintext(
        Session.objects
        .filter(opp_slug=slug)
        .exclude(opp_step_skill=skill, opp_run_id=run_id)
        .order_by("-updated_at")
    )[:20]

    skill_display_lookup = _skill_display_name_lookup()

    def _row(c: Session, kind: str) -> dict:
        return {
            "slug": c.slug,
            "title": c.title or "(untitled)",
            "updated_at": c.updated_at.isoformat(),
            "owner_email": c.owner.email,
            "source": c.source,            # "web" | "upload"
            "kind": kind,                  # "step" | "opp"
            "step_skill": c.opp_step_skill or None,
            # Resolved display name for the step (e.g. "Idea to PDD" from
            # ``idea-to-pdd``). Falls back to the slug when not in the
            # plugin registry. Null only when step_skill is null.
            "step_skill_display": (
                skill_display_lookup.get(c.opp_step_skill, c.opp_step_skill)
                if c.opp_step_skill
                else None
            ),
            "preview": _truncate_preview(getattr(c, "first_user_plaintext", "") or ""),
        }

    payload = [_row(c, "step") for c in step_chats_qs]
    # Cap the combined list so a noisy opp doesn't make the panel unbounded.
    remaining = max(0, 20 - len(payload))
    payload += [_row(c, "opp") for c in opp_chats_qs[:remaining]]

    return Response(success_response(payload))


@api_view(["GET"])
@permission_classes([AllowAny])
def opp_working_session(request, slug: str):
    """Return (or create) the working session for an opp.

    - If the OppWorkspace has a working_session and it is active, return its slug.
    - Otherwise, create a new session linked to the opp, attach it, return slug.
    - If the OppWorkspace doesn't exist (Drive-only opp created pre-migration),
      create one lazily.
    """
    if not request.user.is_authenticated:
        return Response(
            error_response("auth required", code="auth-required"), status=401
        )
    ws, err = _resolve_workspace(request)
    if err is not None:
        return err

    try:
        workspace = OppWorkspace.objects.get(workspace=ws, slug=slug)
    except OppWorkspace.DoesNotExist:
        workspace = OppWorkspace.objects.create(
            slug=slug, display_name=slug, created_by=request.user,
            workspace=ws,
        )

    if workspace.working_session is None or workspace.working_session.status != "active":
        session = Session.create_with_owner(
            owner=request.user,
            title=f"{workspace.display_name} — working session",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
            workspace=ws,
        )
        workspace.working_session = session
        workspace.save(update_fields=["working_session", "updated_at"])

    return Response(success_response({
        "working_session_slug": workspace.working_session.slug,
    }))


@api_view(["PUT"])
@permission_classes([AllowAny])
def opp_artifact_write(request, slug: str, run_id: str, skill: str, artifact_name: str):
    """PUT the body of an existing artifact back to Drive."""
    ws, client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    body = request.data if isinstance(request.data, dict) else {}
    content = body.get("content")
    if content is None:
        return Response(
            error_response("content required", code="missing-content"), status=400
        )

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"), status=404
        )
    step_snap = next(
        (s for s in snap.current_run.steps if s.step.skill_name == skill), None
    )
    if step_snap is None:
        return Response(
            error_response(f"no step {skill!r}", code="step-not-found"), status=404
        )
    artifact = next(
        (a for a in step_snap.artifacts if a.name == artifact_name), None
    )
    if artifact is None:
        return Response(
            error_response(f"no artifact {artifact_name!r}", code="artifact-not-found"),
            status=404,
        )

    client.update_file(
        artifact.drive_file_id,
        content=content,
        mime_type=artifact.mime_type or "text/plain",
    )
    return Response(success_response({"ok": True}))


@api_view(["POST"])
@permission_classes([AllowAny])
def opp_action(request, slug: str, run_id: str, action: str):
    if not request.user.is_authenticated:
        return Response(error_response("auth required", code="auth-required"), status=401)
    ws, err = _resolve_workspace(request)
    if err is not None:
        return err
    try:
        workspace = OppWorkspace.objects.get(workspace=ws, slug=slug)
    except OppWorkspace.DoesNotExist:
        return Response(error_response("opp not found", code="opp-not-found"), status=404)
    session = workspace.working_session
    if session is None or session.status != "active":
        return Response(
            error_response("no active working session", code="no-session"), status=409,
        )
    body = request.data if isinstance(request.data, dict) else {}
    payload = ActionPayload(skill=body.get("skill", ""), reason=body.get("reason"))
    try:
        message = inject_action(
            session=session, action=action, slug=slug, payload=payload,
            user=request.user,
        )
    except ActionError as exc:
        return Response(error_response(str(exc), code=exc.code), status=400)

    return Response(success_response({
        "message_id": message.id,
        "turn_index": message.turn_index,
    }))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cost_rollup(request, slug: str) -> Response:
    """Aggregate cost_breakdown across every workspace-scoped session
    whose opp_slug matches.

    Phases are summed by phase_name. Sessions with empty breakdowns
    (legacy uploads, aggregator failures) are counted but contribute
    nothing — the UI surfaces ``sessions_without_breakdown`` so the user
    can disclose under-counting.
    """
    workspace, err = _resolve_workspace(request)
    if err is not None:
        return err

    sessions = Session.objects.filter(workspace=workspace, opp_slug=slug).only(
        "slug", "cost_breakdown",
    )

    totals = {
        "wall_time_seconds": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_creation_tokens": 0, "cache_read_tokens": 0,
        "estimated_cost_usd": 0.0, "cost_is_partial": False,
    }
    by_phase: dict[str, dict] = {}
    session_count = 0
    sessions_without_breakdown = 0

    for session in sessions:
        session_count += 1
        breakdown = session.cost_breakdown or {}
        if not breakdown or "totals" not in breakdown:
            sessions_without_breakdown += 1
            continue

        bt = breakdown["totals"]
        totals["wall_time_seconds"] += bt.get("wall_time_seconds", 0)
        totals["input_tokens"] += bt.get("input_tokens", 0)
        totals["output_tokens"] += bt.get("output_tokens", 0)
        totals["cache_creation_tokens"] += bt.get("cache_creation_tokens", 0)
        totals["cache_read_tokens"] += bt.get("cache_read_tokens", 0)
        totals["estimated_cost_usd"] += bt.get("estimated_cost_usd", 0.0)
        if bt.get("cost_is_partial"):
            totals["cost_is_partial"] = True

        for phase in breakdown.get("phases", []):
            name = phase["phase_name"]
            row = by_phase.setdefault(name, {
                "phase_name": name,
                "phase_display": phase.get("phase_display", name),
                "phase_ordinal": phase.get("phase_ordinal", 999),
                "wall_time_seconds": 0,
                "estimated_cost_usd": 0.0,
                "cost_is_partial": False,
                "tokens": {"input_tokens": 0, "output_tokens": 0,
                           "cache_creation_tokens": 0, "cache_read_tokens": 0},
                "session_slugs": [],
            })
            row["wall_time_seconds"] += phase.get("wall_time_seconds", 0)
            row["estimated_cost_usd"] += phase.get("estimated_cost_usd", 0.0)
            if phase.get("cost_is_partial"):
                row["cost_is_partial"] = True
            for k in row["tokens"]:
                row["tokens"][k] += phase.get("tokens", {}).get(k, 0)
            if session.slug not in row["session_slugs"]:
                row["session_slugs"].append(session.slug)

    cache_total = (
        totals["cache_read_tokens"] + totals["cache_creation_tokens"] + totals["input_tokens"]
    )
    totals["cache_hit_ratio"] = (
        round(totals["cache_read_tokens"] / cache_total, 4) if cache_total else 0.0
    )
    totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 6)

    phases = sorted(by_phase.values(), key=lambda p: p["phase_ordinal"])
    for p in phases:
        p["estimated_cost_usd"] = round(p["estimated_cost_usd"], 6)

    return Response(success_response({
        "totals": totals,
        "phases": phases,
        "session_count": session_count,
        "sessions_without_breakdown": sessions_without_breakdown,
    }))


# ── Public per-run summary ──────────────────────────────────────────


_SUMMARY_CACHE_TTL_SECONDS = 60


@api_view(["GET"])
@permission_classes([AllowAny])
def public_opp_summary(
    request, workspace: str, slug: str, run_id: str,
) -> Response:
    """Public, unauthenticated per-run summary payload.

    See ``docs/specs/2026-05-04-opp-summary-page-design.md``. Resolves
    the workspace + opp + run from Drive, composes the JSON payload, and
    returns it. 404s on any miss with the same envelope so the API
    doesn't leak which segment was missing. Successful payloads are
    cached for ~60 seconds; 404s are not cached.
    """
    from django.core.cache import cache as _cache

    cache_key = f"opp-summary:v1:{workspace}:{slug}:{run_id}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return Response(success_response(cached))

    try:
        ws = Workspace.objects.get(slug=workspace)
    except Workspace.DoesNotExist:
        return Response(
            error_response("not found", code="not-found"),
            status=404,
        )

    if not ws.drive_root_folder_id:
        return Response(
            error_response("not found", code="not-found"),
            status=404,
        )

    try:
        client = CachedDriveClient(
            get_drive_client(workspace=ws),
            bypass=request.GET.get("force") == "1",
        )
    except ServiceAccountNotFound as exc:
        # Drive misconfiguration is a server problem, not a 404 —
        # surface it explicitly so it can be diagnosed.
        return Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )

    payload = build_summary_payload(
        client, workspace=ws, opp_slug=slug, run_id=run_id,
    )
    if payload is None:
        return Response(
            error_response("not found", code="not-found"),
            status=404,
        )

    _cache.set(cache_key, payload, timeout=_SUMMARY_CACHE_TTL_SECONDS)
    return Response(success_response(payload))
