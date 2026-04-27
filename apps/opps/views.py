"""REST API views for the ACE opportunity Workbench."""
from django.db import transaction
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps.actions import ActionError, ActionPayload, inject_action
from apps.opps.drive_client import get_drive_client
from apps.opps.models import OppWorkspace
from apps.opps.opp_creator import SLUG_RE, CreateOppError, create_opp
from apps.opps.seed import build_chat_seed
from apps.opps.serializers import (
    serialize_opp_snapshot,
    serialize_scorecard,
    serialize_step_snapshot,
)
from apps.opps.sync import delete_opp_folder, load_opp, load_opp_card, load_scorecard
from apps.service_accounts.exceptions import ServiceAccountNotFound
from apps.sessions.models import Message, Session
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import is_member, user_workspaces


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

    slug = None
    if request.resolver_match is not None:
        slug = (request.resolver_match.kwargs or {}).get("workspace_slug")
    if not slug:
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
    """
    ws, err = _resolve_workspace(request)
    if err is not None:
        return None, None, err
    try:
        return ws, get_drive_client(workspace=ws), None
    except ServiceAccountNotFound as exc:
        return ws, None, Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )


def _overlay_workspace_display_name(manifest, slug: str) -> None:
    """Layer OppWorkspace DB metadata (display_name + tags) onto the
    Drive-derived manifest in place.

    Since 2026-04-20, display_name lives only on the OppWorkspace DB row —
    no longer in a Drive state.yaml (that ownership moved to the ACE plugin
    per docs/plans/2026-04-20-drop-multi-run-simplify.md). Tags are also
    DB-only (free-form grouping across sibling opps). Views that render
    opp metadata layer both over the Drive snapshot at the boundary so the
    sync module stays pure.
    """
    try:
        ws = OppWorkspace.objects.only("display_name", "tags").get(slug=slug)
    except OppWorkspace.DoesNotExist:
        return
    if ws.display_name and ws.display_name != slug:
        manifest.display_name = ws.display_name
    manifest.tags = list(ws.tags or [])


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

    cards: list[dict] = []
    for child in client.list_files(ace_folder_id):
        if child.mime_type != "application/vnd.google-apps.folder":
            continue
        opp_children = client.list_files(child.id)

        # Minimum signal that this folder is an opp: idea.md at the root
        # (canonical shape). state.yaml is also accepted for legacy opps
        # created before /ace:run owned state (no idea.md in that case).
        names = {f.name for f in opp_children}
        if "idea.md" not in names and "state.yaml" not in names:
            continue

        try:
            card = load_opp_card(client, opp_folder=child, opp_children=opp_children)
            _overlay_workspace_display_name(card.opp, child.name)
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
                "current_step": card.current_step,
                "status": card.status,
            })
        except Exception:
            continue

    return Response(success_response(cards))


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
        Session.objects.filter(opp_slug=slug).delete()
        OppWorkspace.objects.filter(slug=slug).delete()

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

    try:
        snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )
    _overlay_workspace_display_name(snap.opp, slug)

    return Response(success_response(serialize_opp_snapshot(snap)))


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
    _overlay_workspace_display_name(snap.opp, slug)

    step_snap = next(
        (s for s in snap.current_run.steps if s.step.skill_name == skill), None
    )
    if step_snap is None:
        return Response(
            error_response(f"no step {skill!r} in run {run_id!r}", code="step-not-found"),
            status=404,
        )

    # Fetch the primary artifact body so the frontend can show it inline.
    primary_body = ""
    bodies: dict[str, str] = {}
    for artifact in step_snap.artifacts:
        try:
            content = client.get_content(artifact.drive_file_id, artifact.mime_type)
            bodies[artifact.path] = content.content
        except Exception:
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
    _overlay_workspace_display_name(snap.opp, slug)

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
    _overlay_workspace_display_name(snap.opp, slug)

    try:
        seed_body = build_chat_seed(
            snap,
            skill=skill,
            drive_client=client,
            skill_md_path=_skill_md_relative_path(skill),
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

    step_chats_qs = (
        Session.objects
        .filter(opp_slug=slug, opp_run_id=run_id, opp_step_skill=skill)
        .order_by("-updated_at")[:20]
    )
    opp_chats_qs = (
        Session.objects
        .filter(opp_slug=slug)
        .exclude(opp_step_skill=skill, opp_run_id=run_id)
        .order_by("-updated_at")[:20]
    )

    def _row(c: Session, kind: str) -> dict:
        return {
            "slug": c.slug,
            "title": c.title or "(untitled)",
            "updated_at": c.updated_at.isoformat(),
            "owner_email": c.owner.email,
            "source": c.source,            # "web" | "upload"
            "kind": kind,                  # "step" | "opp"
            "step_skill": c.opp_step_skill or None,
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

    try:
        workspace = OppWorkspace.objects.get(slug=slug)
    except OppWorkspace.DoesNotExist:
        workspace = OppWorkspace.objects.create(
            slug=slug, display_name=slug, created_by=request.user,
        )

    if workspace.working_session is None or workspace.working_session.status != "active":
        session = Session.create_with_owner(
            owner=request.user,
            title=f"{workspace.display_name} — working session",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
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
    try:
        workspace = OppWorkspace.objects.get(slug=slug)
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
