"""REST API views for the ACE opportunity Workbench."""
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps.actions import ActionError, ActionPayload, inject_action
from apps.opps.drive_client import (
    DriveClient,
    get_drive_client,
)
from apps.opps.fork import ForkError, fork_run
from apps.opps.models import OppWorkspace
from apps.opps.opp_creator import SLUG_RE, CreateOppError, create_opp
from apps.opps.parsers import parse_opp_yaml
from apps.opps.seed import build_chat_seed
from apps.opps.serializers import (
    serialize_opp_card,
    serialize_opp_snapshot,
    serialize_run_detail,
    serialize_step_snapshot,
)
from apps.opps.sync import delete_opp_folder, load_opp
from apps.service_accounts.exceptions import ServiceAccountNotFound
from apps.sessions.models import Message, Session


@api_view(["GET"])
@permission_classes([AllowAny])  # Scaffold-only; later views gate Drive access via _require_drive.
def health(request):
    """Scaffold sanity check. Used by tests in Task 1."""
    return Response(success_response({"status": "ok", "module": "opps"}))


def _resolve_ace_root_folder_id(client: DriveClient) -> str | None:
    """Return the Drive folder id of the shared ACE root folder.

    Reads from `settings.ACE_DRIVE_ROOT_FOLDER_ID`, which is pinned in
    environment config (defaulted to the shared ACE folder the team already
    uses). The `client` argument is currently unused but retained so a
    future name-based fallback can live alongside this id-pinned path
    (e.g. walking top-level folders via `client.list_files` when the
    pinned id is empty).

    Returns None when the setting is empty — callers treat that as
    "no ACE root configured" and return an empty list / 404 as appropriate.
    """
    folder_id = getattr(settings, "ACE_DRIVE_ROOT_FOLDER_ID", "") or ""
    return folder_id or None


def _require_drive(request):
    """Return (drive_client, error_response). error_response is None on success."""
    if not request.user.is_authenticated:
        return None, Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )
    try:
        return get_drive_client(), None
    except ServiceAccountNotFound as exc:
        return None, Response(
            error_response(str(exc), code="drive-not-configured"),
            status=500,
        )


def _opp_list_impl(request):
    """Plain function form of the opp-list handler. Called directly by
    opp_collection (GET) to avoid double-wrapping with @api_view."""
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(success_response([]))

    cards: list[dict] = []
    for child in client.list_files(ace_folder_id):
        if child.mime_type != "application/vnd.google-apps.folder":
            continue
        opp_children = client.list_files(child.id)

        # Structured layout: ACE/<slug>/opp.yaml
        opp_yaml = next((f for f in opp_children if f.name == "opp.yaml"), None)
        if opp_yaml is not None:
            try:
                body = client.get_content(opp_yaml.id, opp_yaml.mime_type).content
                manifest = parse_opp_yaml(body)
                cards.append(serialize_opp_card(manifest, current_run=None))
                continue
            except Exception:
                pass

        # Flat / web-created layouts: any of these at ACE/<slug>/ is enough
        # to identify this folder as an opp. load_opp handles both the old
        # (state.yaml + pdd.md) and new (idea.md + runs/) shapes. During the
        # IDD→PDD rename transition we accept either primary doc name.
        names = {f.name for f in opp_children}
        has_primary_doc = "pdd.md" in names or "idd.md" in names
        looks_like_opp = (
            "state.yaml" in names and has_primary_doc
        ) or (
            "idea.md" in names and any(
                f.name == "runs" and f.mime_type == "application/vnd.google-apps.folder"
                for f in opp_children
            )
        )
        if looks_like_opp:
            try:
                snap = load_opp(client, ace_folder_id=ace_folder_id, slug=child.name)
                cards.append(serialize_opp_card(snap.opp, snap.current_run))
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

    client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(client)
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
    client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(client)
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


@api_view(["GET", "DELETE"])
@permission_classes([AllowAny])  # Drive availability enforced via _require_drive
def workbench(request, slug: str):
    if request.method == "DELETE":
        return delete_opp(request, slug)

    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
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

    return Response(success_response(serialize_opp_snapshot(snap)))


@api_view(["GET"])
@permission_classes([AllowAny])
def step_detail(request, slug: str, run_id: str, skill: str):
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
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
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
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
def opp_compare(request, slug: str):
    client, err = _require_drive(request)
    if err is not None:
        return err

    from_id = request.GET.get("from", "")
    to_id = request.GET.get("to", "")
    if not from_id or not to_id:
        return Response(
            error_response(
                "compare requires `from` and `to` query params", code="missing-params"
            ),
            status=400,
        )

    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    try:
        snap_from = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=from_id)
        snap_to = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=to_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp or run for {slug!r}", code="opp-not-found"),
            status=404,
        )

    return Response(
        success_response(
            {
                "opp": {
                    "slug": snap_to.opp.slug,
                    "display_name": snap_to.opp.display_name,
                },
                "from_run": serialize_run_detail(snap_from.current_run),
                "to_run": serialize_run_detail(snap_to.current_run),
            }
        )
    )


def _skill_md_relative_path(skill: str) -> str:
    """Return the path of a skill's SKILL.md relative to the ace plugin repo root.

    The ACE plugin lays skills out as `skills/<skill-name>/SKILL.md`.
    """
    return f"skills/{skill}/SKILL.md"


@api_view(["POST"])
@permission_classes([AllowAny])
def discuss(request, slug: str, run_id: str, skill: str):
    """Create a new ace-web chat Session linked to this opp/run/step."""
    client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(client)
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
    """List prior ace-web chat sessions linked to this opp/run/step."""
    client, err = _require_drive(request)
    if err is not None:
        return err

    chats = Session.objects.filter(
        opp_slug=slug, opp_run_id=run_id, opp_step_skill=skill,
    ).order_by("-updated_at")[:20]

    return Response(success_response([
        {
            "slug": c.slug,
            "title": c.title or "(untitled)",
            "updated_at": c.updated_at.isoformat(),
            "owner_email": c.owner.email,
        }
        for c in chats
    ]))


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
    client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(client)
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


@api_view(["POST"])
@permission_classes([AllowAny])
def opp_fork(request, slug: str, run_id: str):
    """POST /api/opps/<slug>/runs/<run_id>/fork — create a new run."""
    client, err = _require_drive(request)
    if err is not None:
        return err
    ace_folder_id = _resolve_ace_root_folder_id(client)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    body = request.data if isinstance(request.data, dict) else {}

    try:
        result = fork_run(
            drive=client,
            ace_root_folder_id=ace_folder_id,
            slug=slug,
            from_run_id=run_id,
            from_skill=body.get("from_skill", ""),
            mode=body.get("mode", ""),
            feedback=body.get("feedback"),
            owner=request.user,
        )
    except ForkError as exc:
        status = 404 if exc.code in ("opp-not-found", "step-not-found") else 400
        return Response(error_response(str(exc), code=exc.code), status=status)

    return Response(
        success_response({
            "new_run_id": result.new_run_id,
            "working_session_slug": result.working_session.slug,
        }),
        status=201,
    )
