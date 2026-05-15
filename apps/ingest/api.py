"""Django Ninja v2 router for the ingest surface."""
from __future__ import annotations

import logging
import re

from django.http import HttpRequest, HttpResponse
from ninja import File, Form, Router
from ninja.files import UploadedFile

from apps.api.auth import session_auth
from apps.api.errors import TYPE_CONFLICT, TYPE_NOT_FOUND, TYPE_VALIDATION, ProblemError

from .schemas import IngestUploadOut

log = logging.getLogger(__name__)

router = Router(auth=session_auth, tags=["ingest"])

_OPP_FIELD_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


# ---------------------------------------------------------------------------
# POST /ingest/upload — multipart upload
# ---------------------------------------------------------------------------


def process_ingest_upload(
    user,
    raw_bytes: bytes,
    filename: str,
    opp_slug: str,
    opp_run_id: str,
    opp_step_skill: str,
    workspace,
) -> dict:
    """Core upload logic — separated for testability.

    The monkeypatch target in contract tests is this module-level function.
    """
    import gzip
    import tempfile
    from pathlib import Path

    from apps.ingest.cost_aggregator import aggregate
    from apps.ingest.parser import parse_session_file
    from apps.sessions.models import IngestUpload, Message, Session

    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = Path(tmp.name)

    try:
        parsed, cost_events = parse_session_file(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    try:
        breakdown = aggregate(cost_events)
    except Exception:  # noqa: BLE001
        log.exception("cost aggregator failed for upload %s", filename)
        breakdown = {}

    if parsed.cli_session_id and IngestUpload.objects.filter(
        cli_session_id=parsed.cli_session_id
    ).exists():
        raise ProblemError(
            409,
            f"Session {parsed.cli_session_id} already uploaded",
            type_=TYPE_CONFLICT,
        )

    if parsed.content_sha256 and IngestUpload.objects.filter(
        content_sha256=parsed.content_sha256
    ).exists():
        raise ProblemError(
            409,
            "Transcript with identical content already uploaded",
            type_=TYPE_CONFLICT,
        )

    session = Session.create_with_owner(
        owner=user,
        source="upload",
        status="imported",
        cli_session_id=parsed.cli_session_id or "",
        title=f"Imported: {filename}",
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
        uploaded_by=user,
        source_path=filename,
        raw_bytes=parsed.raw_bytes,
        line_count=parsed.line_count,
        cli_session_id=parsed.cli_session_id or "",
        content_sha256=parsed.content_sha256 or "",
        workspace=workspace,
        raw_jsonl_gz=gzip.compress(raw_bytes),
    )

    return {
        "session_slug": session.slug,
        "messages_imported": len(messages),
        "cli_session_id": parsed.cli_session_id or None,
        "opp_slug": session.opp_slug or None,
        "opp_run_id": session.opp_run_id or None,
        "opp_step_skill": session.opp_step_skill or None,
        "cost_breakdown": breakdown or None,
    }


@router.post("/upload", response={201: IngestUploadOut}, summary="Upload a JSONL transcript")
def upload(
    request: HttpRequest,
    file: UploadedFile = File(...),  # noqa: B008
    opp_slug: str | None = Form(None),
    opp_run_id: str | None = Form(None),
    opp_step_skill: str | None = Form(None),
    ace_root_folder_id: str | None = Form(None),
    workspace_slug: str | None = Form(None),
) -> HttpResponse:
    from django.http import JsonResponse

    # Validate opp field format
    opp_slug = (opp_slug or "").strip()
    opp_run_id = (opp_run_id or "").strip()
    opp_step_skill = (opp_step_skill or "").strip()
    ace_root_folder_id = (ace_root_folder_id or "").strip()
    workspace_slug = (workspace_slug or "").strip()

    for field_name, value in (
        ("opp_slug", opp_slug),
        ("opp_run_id", opp_run_id),
        ("opp_step_skill", opp_step_skill),
    ):
        if value and not _OPP_FIELD_RE.match(value):
            raise ProblemError(
                422,
                f"{field_name} must match [A-Za-z0-9_.-]{{1,64}} (got {value!r})",
                type_=TYPE_VALIDATION,
            )

    # Workspace resolution
    workspace = None
    if ace_root_folder_id:
        from apps.workspaces.models import Workspace

        try:
            workspace = Workspace.objects.get(drive_root_folder_id=ace_root_folder_id)
        except Workspace.DoesNotExist as exc:
            raise ProblemError(
                404,
                "No workspace claims this drive_root_folder_id",
                type_=TYPE_NOT_FOUND,
            ) from exc
        from apps.workspaces.models import WorkspaceMembership

        if not WorkspaceMembership.objects.filter(
            workspace=workspace, user=request.user
        ).exists():
            raise ProblemError(403, "Forbidden", type_="https://ace-web.dimagi.com/problems/forbidden")
    elif workspace_slug:
        from apps.api.deps import resolve_workspace_for_member

        workspace = resolve_workspace_for_member(request, workspace_slug)

    raw_bytes = b"".join(file.chunks())
    result = process_ingest_upload(
        user=request.user,
        raw_bytes=raw_bytes,
        filename=file.name or "upload.jsonl",
        opp_slug=opp_slug,
        opp_run_id=opp_run_id,
        opp_step_skill=opp_step_skill,
        workspace=workspace,
    )
    payload = IngestUploadOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload, status=201)
