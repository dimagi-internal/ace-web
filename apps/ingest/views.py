"""Upload endpoint for JSONL session files."""
import logging
import re
import tempfile
from pathlib import Path

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.ingest.cost_aggregator import aggregate
from apps.sessions.models import IngestUpload, Message, Session

from .parser import parse_session_file

log = logging.getLogger(__name__)

# Permissive run-id alphabet — covers `r1`, `run-001`, `2026-04-06-002`,
# `20260502-1830`. Rejects whitespace, slashes, and any other surprise
# input that would silently misattribute a transcript. Same alphabet is
# applied to opp_slug and opp_step_skill for symmetry.
_OPP_FIELD_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


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

    for field_name, value in (
        ("opp_slug", opp_slug),
        ("opp_run_id", opp_run_id),
        ("opp_step_skill", opp_step_skill),
    ):
        if value and not _OPP_FIELD_RE.match(value):
            return Response(
                error_response(
                    message=(
                        f"{field_name} must match [A-Za-z0-9_.-]{{1,64}} "
                        f"(got {value!r})"
                    ),
                    code="validation_error",
                ),
                status=422,
            )

    # Optional workspace resolution via Drive folder id (added in the
    # multi-tenancy Phase A). The plugin's upload-transcript skill is
    # being updated to pass this; uploads from older plugin versions
    # will arrive without it and become orphan uploads attached only
    # to the uploading user.
    ace_root_folder_id = (request.data.get("ace_root_folder_id") or "").strip()
    workspace = None
    if ace_root_folder_id:
        from apps.common.access import gate_membership
        from apps.workspaces.models import Workspace
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
        # The caller already supplied the drive_root_folder_id, so existence
        # is not a secret — surface 403 ("not a member") rather than
        # 404 ("not found") on membership failure.
        err = gate_membership(request.user, workspace, hidden_existence=False)
        if err is not None:
            return err

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        for chunk in file.chunks():
            tmp.write(chunk)
        tmp_path = Path(tmp.name)

    try:
        parsed, cost_events = parse_session_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    try:
        breakdown = aggregate(cost_events)
    except Exception:
        log.exception("cost aggregator failed for upload %s", file.name)
        breakdown = {}

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

    # Content-hash dedup — fires when cli_session_id is empty (e.g. a
    # malformed transcript with no session-id envelope) so re-uploads
    # of identical bytes still 409 instead of producing duplicate rows.
    if parsed.content_sha256 and IngestUpload.objects.filter(
        content_sha256=parsed.content_sha256
    ).exists():
        return Response(
            error_response(
                message="Transcript with identical content already uploaded",
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
        cost_breakdown=breakdown,
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
        content_sha256=parsed.content_sha256 or "",
        workspace=workspace,
    )

    log.info(
        "ingest upload: user=%s file=%s session=%s "
        "form opp_slug=%r opp_run_id=%r opp_step_skill=%r ace_root_folder_id=%r "
        "stored opp_slug=%r opp_run_id=%r opp_step_skill=%r workspace=%s "
        "cli_session_id=%r content_sha256=%s",
        request.user.pk, file.name, session.slug,
        opp_slug, opp_run_id, opp_step_skill, ace_root_folder_id,
        session.opp_slug, session.opp_run_id, session.opp_step_skill,
        workspace.slug if workspace else None,
        parsed.cli_session_id or "",
        (parsed.content_sha256 or "")[:16],
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
