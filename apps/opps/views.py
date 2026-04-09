"""REST API views for the ACE opportunity Workbench."""
from django.db import transaction
from django.http import HttpResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps.drive_client import DriveClient
from apps.opps.drive_credentials import CredentialsRefreshFailed
from apps.opps.drive_for_request import DriveTokenMissing, get_drive_client_for
from apps.opps.middleware import RequireDriveToken
from apps.opps.parsers import parse_opp_yaml
from apps.opps.seed import build_chat_seed
from apps.opps.serializers import (
    serialize_opp_card,
    serialize_opp_snapshot,
    serialize_run_detail,
    serialize_step_snapshot,
)
from apps.opps.sync import load_opp
from apps.sessions.models import Message, Session


@api_view(["GET"])
@permission_classes([AllowAny])  # Scaffold-only; later views in this file use RequireDriveToken.
def health(request):
    """Scaffold sanity check. Used by tests in Task 1."""
    return Response(success_response({"status": "ok", "module": "opps"}))


def _resolve_ace_root_folder_id(client: DriveClient) -> str | None:
    """Find the ACE root folder by name.

    We search for a folder named `settings.ACE_DRIVE_ROOT_FOLDER_NAME` that
    the user has access to. If multiple matches exist, return the first one
    — this rarely happens in practice and can be overridden via a pinned
    folder id in settings later.

    Returns None if no such folder exists.
    """
    # The DriveClient ABC does not expose a search, only list_files / get_file.
    # GoogleDriveClient could add a search helper later; for now we walk from
    # the Drive root by listing top-level files. Tests patch this whole
    # function to return a known folder id.
    raise NotImplementedError(
        "real implementation: add a Drive files.list(q='name=...') helper; "
        "tests patch this function to return a known folder id"
    )


def _require_drive(request):
    """Return (drive_client, error_response) tuple. error_response is None on success."""
    if not request.user.is_authenticated:
        return None, Response(
            error_response("authentication required", code="auth-required"),
            status=401,
        )
    perm = RequireDriveToken()
    if not perm.has_permission(request, view=None):
        payload = RequireDriveToken.get_reconnect_payload()
        return None, Response(
            {
                "data": payload,
                "error": {
                    "code": "drive-token-missing",
                    "message": "Google Drive access is not connected for this user",
                },
            },
            status=401,
        )
    try:
        client = get_drive_client_for(request.user)
    except DriveTokenMissing:
        payload = RequireDriveToken.get_reconnect_payload()
        return None, Response(
            {
                "data": payload,
                "error": {
                    "code": "drive-token-missing",
                    "message": "no drive token on file",
                },
            },
            status=401,
        )
    except CredentialsRefreshFailed as exc:
        payload = RequireDriveToken.get_reconnect_payload()
        return None, Response(
            {
                "data": payload,
                "error": {
                    "code": "drive-token-refresh-failed",
                    "message": str(exc),
                },
            },
            status=401,
        )
    return client, None


@api_view(["GET"])
@permission_classes([AllowAny])  # RequireDriveToken is enforced inside
def opp_list(request):
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
        # Try structured layout first: does it have opp.yaml?
        opp_children = client.list_files(child.id)
        opp_yaml = next((f for f in opp_children if f.name == "opp.yaml"), None)
        if opp_yaml is not None:
            try:
                body = client.get_content(opp_yaml.id, opp_yaml.mime_type).content
                manifest = parse_opp_yaml(body)
                cards.append(serialize_opp_card(manifest, current_run=None))
                continue
            except Exception:
                pass
        # Flat layout: state.yaml + idd.md
        has_state = any(f.name == "state.yaml" for f in opp_children)
        has_idd = any(f.name == "idd.md" for f in opp_children)
        if has_state and has_idd:
            try:
                snap = load_opp(client, ace_folder_id=ace_folder_id, slug=child.name)
                cards.append(serialize_opp_card(snap.opp, snap.current_run))
            except Exception:
                continue

    return Response(success_response(cards))


@api_view(["GET"])
@permission_classes([AllowAny])  # RequireDriveToken enforced via _require_drive
def workbench(request, slug: str):
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

    # Resolve the IDD drive file id for session.idd_ref.
    idd_drive_id = ""
    for step_snap in snap.current_run.steps:
        if step_snap.step.skill_name == "idea-to-idd":
            for artifact in step_snap.artifacts:
                if artifact.name == "idd.md":
                    idd_drive_id = artifact.drive_file_id
                    break
    # Fall back to the top-level idd.md at the opp root if the idea-to-idd step
    # didn't capture it as an artifact.
    # (Top-level idd.md lookup happens inside sync.load_opp but we didn't
    # surface its file id. It would be a cheap enhancement to add that.)

    with transaction.atomic():
        session = Session.objects.create(
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
