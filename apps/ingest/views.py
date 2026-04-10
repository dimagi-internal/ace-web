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
from apps.sessions.models import IngestUpload, Message, Session, SessionParticipant

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

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        for chunk in file.chunks():
            tmp.write(chunk)
        tmp_path = Path(tmp.name)

    try:
        parsed = parse_session_file(tmp_path)
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

    session = Session.objects.create(
        owner=request.user,
        source="upload",
        status="imported",
        cli_session_id=parsed.cli_session_id or "",
        title=f"Imported: {file.name}",
    )
    SessionParticipant.objects.create(
        session=session, user=request.user, role="owner"
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
    )

    return Response(
        success_response({
            "session_slug": session.slug,
            "message_count": len(messages),
            "cli_session_id": parsed.cli_session_id,
        }),
        status=status.HTTP_201_CREATED,
    )
