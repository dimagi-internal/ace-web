"""Chat-session-bridging views for the opps Workbench.

These endpoints create or query ace-web ``Session`` rows linked to
opps/runs/steps:

- ``POST /api/opps/<slug>/runs/<run_id>/steps/<skill>/discuss``
  Seeds a new chat session with the step's context (Discuss in chat).
- ``GET  /api/opps/<slug>/runs/<run_id>/steps/<skill>/chats``
  Lists prior step- and opp-scoped chats for the panel.
- ``GET  /api/opps/<slug>/working-session``
  Returns (or lazily creates) the opp's persistent working session.

Split out from views.py because session-bridging is the natural seam
where the read-only Drive view (apps.opps) hands off to the chat
backend (apps.sessions). Keeping it in its own module makes the
cross-app coupling explicit.
"""
from __future__ import annotations

from django.db import transaction
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response
from apps.opps import access
from apps.opps.models import OppWorkspace
from apps.opps.seed import build_chat_seed
from apps.opps.sync import load_opp
from apps.sessions.models import Message, Session


def _skill_display_name_lookup() -> dict[str, str]:
    """``{skill_slug: display_name}`` for the current ``ACE_PLUGIN_PATH``."""
    from django.conf import settings as _s

    from apps.system.reader import skill_display_names

    return skill_display_names(getattr(_s, "ACE_PLUGIN_PATH", "") or "")


def _skill_md_relative_path(skill: str) -> str:
    """Return the path of a skill's SKILL.md relative to the ace plugin repo root.

    The ACE plugin lays skills out as ``skills/<skill-name>/SKILL.md``.
    """
    return f"skills/{skill}/SKILL.md"


@api_view(["POST"])
@permission_classes([AllowAny])
def discuss(request, slug: str, run_id: str, skill: str):
    """Create a new ace-web chat Session linked to this opp/run/step."""
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
    ws, client, err = access.require_drive(request)
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
    ws, err = access.resolve_workspace(request)
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
