"""Mutating views for the opps Workbench.

Create / fork / delete / patch / artifact-write / action-inject. All call
through ``access.require_drive`` (which gates on workspace membership)
or ``access.resolve_workspace`` (auth-only). The list/get dispatchers
stay in ``views.py`` and call into the helpers here for write methods.
"""
from __future__ import annotations

from django.db import models, transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps import access, snapshot_cache
from apps.opps.actions import ActionError, ActionPayload, inject_action
from apps.opps.models import OppWorkspace
from apps.opps.opp_creator import SLUG_RE, CreateOppError, create_opp
from apps.opps.opp_forker import ForkOppError, fork_opp
from apps.opps.sync import (
    delete_opp_folder,
    delete_run_folder,
    load_opp,
)
from apps.sessions.models import Session


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


@api_view(["POST"])
@permission_classes([AllowAny])
def opp_fork(request, slug: str):
    """POST /api/opps/<slug>/fork — fork this opp into a new one at the
    given phase boundary.

    Body: ``{new_slug: <str>, fork_at_phase: <phase-name>}``

    Synchronous Drive-recursive copy; can take 30-60s on large opps.
    Frontend should show a loading state. Returns the new slug on
    success; the caller navigates to its workbench.
    """
    if not request.user.is_authenticated:
        return Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )
    payload = request.data if isinstance(request.data, dict) else {}
    new_slug = (payload.get("new_slug") or "").strip()
    fork_at_phase = (payload.get("fork_at_phase") or "").strip()
    if not new_slug:
        return Response(
            error_response("new_slug is required", code="invalid-slug"),
            status=400,
        )
    if not fork_at_phase:
        return Response(
            error_response(
                "fork_at_phase is required", code="invalid-phase",
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
        result = fork_opp(
            drive=client,
            ace_root_folder_id=ace_folder_id,
            owner=request.user,
            source_slug=slug,
            new_slug=new_slug,
            fork_at_phase=fork_at_phase,
            workspace=ws,
        )
    except ForkOppError as exc:
        status = (
            409 if exc.code == "slug-taken"
            else 404 if exc.code == "source-not-found"
            else 400
        )
        return Response(error_response(str(exc), code=exc.code), status=status)

    return Response(
        success_response({
            "slug": result.new_slug,
            "working_session_slug": result.working_session.slug,
        }),
        status=201,
    )


@api_view(["DELETE"])
@permission_classes([AllowAny])
def delete_run(request, slug: str, run_id: str):
    """DELETE /api/opps/<slug>/runs/<run_id> — trash a single run subfolder.

    Drive trash is 30-day recoverable. The opp folder itself stays
    intact; only the named run subfolder is moved to trash. Linked
    chat sessions are NOT cascade-deleted (a chat seeded from a step
    of this run is still useful as transcript history).

    Returns 204 on success, 404 if the run doesn't exist.
    """
    if not request.user.is_authenticated:
        return Response(
            error_response("authentication required", code="auth-required"),
            status=401,
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
        delete_run_folder(
            client, ace_folder_id=ace_folder_id, opp_slug=slug, run_id=run_id,
        )
    except FileNotFoundError as exc:
        return Response(
            error_response(str(exc), code="run-not-found"),
            status=404,
        )

    # Drop any cached snapshots/cards for this workspace — the
    # run-folder trash isn't always reflected in the Drive Changes
    # pageToken before the next list, and a stale snapshot would still
    # surface the deleted run in the strip / runs list.
    snapshot_cache.clear_workspace(ws.pk)

    return Response(status=204)


def delete_opp(request, slug: str):
    """Handle DELETE. Called from workbench() when request.method == 'DELETE'.
    Not decorated with @api_view — workbench() carries the decorator."""
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
    ws, err = access.resolve_workspace(request)
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


@api_view(["PUT"])
@permission_classes([AllowAny])
def opp_artifact_write(request, slug: str, run_id: str, skill: str, artifact_name: str):
    """PUT the body of an existing artifact back to Drive."""
    ws, client, err = access.require_drive(request)
    if err is not None:
        return err
    ace_folder_id = access.resolve_ace_root_folder_id(ws)
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
    ws, err = access.resolve_workspace(request)
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
