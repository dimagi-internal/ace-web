"""REST API views for the ACE opportunity Workbench."""
import logging

from django.conf import settings
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps import access, drive_changes, snapshot_cache
from apps.opps.serializers import (
    normalize_score_pct,
    serialize_opp_snapshot,
    serialize_scorecard,
    serialize_step_snapshot,
)
from apps.opps.sync import (
    list_opp_runs,
    load_opp,
    load_opp_card,
    load_opp_card_by_slug,
    load_scorecard,
)
from apps.opps.touched_tracker import TouchedFileTracker
from apps.sessions.models import Session
from apps.system.reader import (
    load_system_overview,
)
from apps.system.reader import (
    phase_display_names as _phase_display_names,
)
from apps.system.reader import (
    skill_display_names as _skill_display_names,
)

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


def _opp_list_impl(request):
    """Plain function form of the opp-list handler. Called directly by
    opp_collection (GET) to avoid double-wrapping with @api_view.

    Supports ``?tags=X,Y`` to filter to opps whose OppWorkspace.tags
    contains ALL of the listed tags (intersection — matches the "narrow
    down to iterations of the same idea" UX).
    """
    ws, client, err = access.require_drive(request)
    if err is not None:
        return err

    ace_folder_id = access.resolve_ace_root_folder_id(ws)
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
                cold_client = snapshot_cache.cold_load_client(client)
                with TouchedFileTracker() as tracker:
                    # opp_children was listed above (outside the tracker) for
                    # the "is this an opp folder?" check; replay both the
                    # opp folder id and its children into the tracker so a
                    # change to either (e.g. the runs/ folder appearing for
                    # the first time, or state.yaml moving up to root)
                    # invalidates this OppCard.
                    tracker.record(child.id, child.modified_time)
                    for f in opp_children:
                        tracker.record(f.id, f.modified_time)
                    card = load_opp_card(cold_client, opp_folder=child, opp_children=opp_children)
                access.overlay_workspace_display_name(card.opp, child.name, workspace=ws)
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
                    "eval_score": None,
                    "eval_score_pct": None,
                    "eval_passed": None,
                    "last_activity_at": None,
                    "run_count": 1,
                    "error": {"message": str(exc) or exc.__class__.__name__},
                })
                continue
        else:
            access.overlay_workspace_display_name(card.opp, child.name, workspace=ws)

        if required_tags and not required_tags.issubset(set(card.opp.tags)):
            continue

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
    return snapshot_cache.etag_or_304(
        request, list_etag, lambda: Response(success_response(cards)),
    )


# ── Write endpoints ────────────────────────────────────────────────
# Moved to apps/opps/views_write.py.
from apps.opps.views_write import (  # noqa: E402,F401
    delete_opp,
    delete_run,
    opp_action,
    opp_artifact_write,
    opp_create,
    opp_fork,
    opp_fork_status,
    patch_opp,
)


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
def opp_collection(request):
    """Dispatches GET to the list reader and POST to the create handler."""
    if request.method == "POST":
        return opp_create(request)
    return _opp_list_impl(request)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AllowAny])  # Drive availability enforced via _require_drive
def workbench(request, slug: str):
    if request.method == "DELETE":
        return delete_opp(request, slug)
    if request.method == "PATCH":
        return patch_opp(request, slug)

    ws, client, err = access.require_drive(request)
    if err is not None:
        return err

    ace_folder_id = access.resolve_ace_root_folder_id(ws)
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
            access.overlay_workspace_display_name(cached.opp, slug, workspace=ws)
            etag = access.snapshot_etag(cached)
            return snapshot_cache.etag_or_304(
                request, etag,
                lambda: Response(success_response(serialize_opp_snapshot(cached))),
            )

    bypass_client = snapshot_cache.cold_load_client(client)

    try:
        with TouchedFileTracker() as tracker:
            snap = load_opp(bypass_client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )
    access.overlay_workspace_display_name(snap.opp, slug, workspace=ws)
    snapshot_cache.set(
        workspace_id=ws.pk, slug=slug, run_id=run_id,
        snap=snap, file_ids=tracker.file_ids,
    )
    # Cold-load always returns 200 with ETag, even if the request happened to
    # carry a matching If-None-Match — ?force=1 callers (or genuine cache
    # misses) want fresh content, not a 304.
    etag = access.snapshot_etag(snap)
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
    ws, client, err = access.require_drive(request)
    if err is not None:
        return err
    ace_folder_id = access.resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )
    runs = list_opp_runs(client, ace_root_folder_id=ace_folder_id, opp_slug=slug)
    # Surface display names + phase ordinal alongside the slugs so the
    # inline runs UI on /opps can render "P3 · Idea to PDD" without
    # re-fetching the system overview. Lookups are process-cached so this
    # is essentially free.
    skill_lookup = _skill_display_name_lookup()
    phase_lookup = _phase_display_name_lookup()
    overview = load_system_overview(getattr(settings, "ACE_PLUGIN_PATH", "") or "")
    phase_ordinals = {
        p["name"]: p["ordinal"]
        for p in (overview.get("phases") or [])
        if isinstance(p.get("ordinal"), int)
    }
    return Response(success_response([
        {
            "run_id": r.run_id,
            "folder_id": r.folder_id,
            "current_phase": r.current_phase,
            "current_phase_display": (
                phase_lookup.get(r.current_phase) if r.current_phase else None
            ),
            "current_phase_ordinal": (
                phase_ordinals.get(r.current_phase) if r.current_phase else None
            ),
            "current_step": r.current_step,
            "current_step_display": (
                skill_lookup.get(r.current_step) if r.current_step else None
            ),
            "mode": r.mode,
            "last_actor": r.last_actor,
            "last_actor_at": r.last_actor_at,
            "lifecycle_status": r.lifecycle_status,
            "phases_total": r.phases_total,
            "phases_done": r.phases_done,
            "latest_phase_done": r.latest_phase_done,
            "latest_phase_done_display": (
                phase_lookup.get(r.latest_phase_done)
                if r.latest_phase_done
                else None
            ),
            "latest_phase_done_ordinal": (
                phase_ordinals.get(r.latest_phase_done)
                if r.latest_phase_done
                else None
            ),
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
                          {skill: score}, ...}
      - skill_index: ordered list of {skill_name, display_name, phase,
                          phase_display, ordinal, has_judge}

    First load is expensive (one full ``load_opp`` per run, ~5s each
    cold); the Drive cache makes subsequent requests sub-second. The
    response is also cached for OPPS_DRIVE_CACHE_SECONDS so consecutive
    page loads of the cross-run views land in single-digit ms even
    when the per-snapshot cache misses.
    """
    from django.core.cache import cache as _cache

    ws, client, err = access.require_drive(request)
    if err is not None:
        return err
    ace_folder_id = access.resolve_ace_root_folder_id(ws)
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
    ws, client, err = access.require_drive(request)
    if err is not None:
        return err

    ace_folder_id = access.resolve_ace_root_folder_id(ws)
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
    access.overlay_workspace_display_name(snap.opp, slug, workspace=ws)

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
    ws, client, err = access.require_drive(request)
    if err is not None:
        return err

    ace_folder_id = access.resolve_ace_root_folder_id(ws)
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
    access.overlay_workspace_display_name(snap.opp, slug, workspace=ws)

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
    ws, client, err = access.require_drive(request)
    if err is not None:
        return err

    ace_folder_id = access.resolve_ace_root_folder_id(ws)
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


@api_view(["GET"])
@permission_classes([AllowAny])
def opp_compare(request, slug_a: str, slug_b: str):
    """Side-by-side comparison of two opps in the same workspace.

    Loads both OppSnapshots plus an opp-eval summary for each, and
    returns a small `summary` block with the score delta so the
    frontend can render the "did the new run improve?" banner without
    re-deriving anything.
    """
    if slug_a == slug_b:
        return Response(
            error_response(
                "cannot compare an opp to itself", code="same-opp",
            ),
            status=400,
        )

    ws, client, err = access.require_drive(request)
    if err is not None:
        return err

    ace_folder_id = access.resolve_ace_root_folder_id(ws)
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

    access.overlay_workspace_display_name(snap_a.opp, slug_a, workspace=ws)
    access.overlay_workspace_display_name(snap_b.opp, slug_b, workspace=ws)

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
        },
    }))


# ── Session-bridging endpoints ─────────────────────────────────────
# Moved to apps/opps/views_session.py.
from apps.opps.views_session import (  # noqa: E402,F401
    discuss,
    opp_working_session,
    step_chats,
)

# opp_artifact_write and opp_action moved to views_write.py (re-exported above).


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
    workspace, err = access.resolve_workspace(request)
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
# Moved to apps/opps/views_summary.py.
from apps.opps.views_summary import public_opp_summary  # noqa: E402,F401
