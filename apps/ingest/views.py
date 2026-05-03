"""Upload endpoint for JSONL session files."""
import tempfile
from pathlib import Path

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.sessions.models import IngestUpload, Message, Session

from .parser import parse_session_file


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def upload(request: Request) -> Response:
    file = request.FILES.get("file")
    if not file:
        return Response(
            error_response(message="file is required", code="validation_error"),
            status=400,
        )

    # Optional opp/run/step linkage. The ACE plugin's `upload-transcript`
    # skill passes these multipart fields so a transcript produced by
    # `/ace:run` shows up against the originating opp in the Workbench's
    # "linked chats" panel. Absent fields = orphan upload (still valid).
    opp_slug = (request.data.get("opp_slug") or "").strip()
    opp_run_id = (request.data.get("opp_run_id") or "").strip()
    opp_step_skill = (request.data.get("opp_step_skill") or "").strip()

    # Optional workspace resolution via Drive folder id (added in the
    # multi-tenancy Phase A). The plugin's upload-transcript skill is
    # being updated to pass this; uploads from older plugin versions
    # will arrive without it and become orphan uploads attached only
    # to the uploading user.
    ace_root_folder_id = (request.data.get("ace_root_folder_id") or "").strip()
    workspace = None
    if ace_root_folder_id:
        from apps.workspaces.models import Workspace
        from apps.workspaces.permissions import is_member
        try:
            workspace = Workspace.objects.get(drive_root_folder_id=ace_root_folder_id)
        except Workspace.DoesNotExist:
            return Response(
                error_response(
                    message="no workspace claims this drive_root_folder_id",
                    code="workspace-not-found",
                ),
                status=404,
            )
        if not is_member(request.user, workspace):
            return Response(
                error_response(
                    message="you are not a member of this workspace",
                    code="not-a-member",
                ),
                status=403,
            )

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        for chunk in file.chunks():
            tmp.write(chunk)
        tmp_path = Path(tmp.name)

    try:
        parsed, cost_events = parse_session_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    if parsed.cli_session_id and IngestUpload.objects.filter(
        cli_session_id=parsed.cli_session_id
    ).exists():
        return Response(
            error_response(
                message=f"Session {parsed.cli_session_id} already uploaded",
                code="duplicate",
            ),
            status=409,
        )

    session = Session.create_with_owner(
        owner=request.user,
        source="upload",
        status="imported",
        cli_session_id=parsed.cli_session_id or "",
        title=f"Imported: {file.name}",
        opp_slug=opp_slug,
        opp_run_id=opp_run_id,
        opp_step_skill=opp_step_skill,
        workspace=workspace,
    )

    messages = []
    for idx, turn in enumerate(parsed.turns, start=1):
        messages.append(
            Message(
                session=session,
                turn_index=idx,
                role=turn.role,
                content=turn.content,
                plaintext=turn.plaintext,
                status="complete",
            )
        )
    Message.objects.bulk_create(messages)

    IngestUpload.objects.create(
        session=session,
        uploaded_by=request.user,
        source_path=file.name,
        raw_bytes=parsed.raw_bytes,
        line_count=parsed.line_count,
        cli_session_id=parsed.cli_session_id or "",
        workspace=workspace,
    )

    return Response(
        success_response({
            "session_slug": session.slug,
            "message_count": len(messages),
            "cli_session_id": parsed.cli_session_id,
            "opp_slug": session.opp_slug or None,
            "opp_run_id": session.opp_run_id or None,
            "opp_step_skill": session.opp_step_skill or None,
        }),
        status=status.HTTP_201_CREATED,
    )
