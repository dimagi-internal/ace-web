"""Resolve a slash-command argument into a triggered run.

Three input forms:
  - Bare slug (existing opp): "rural-health-tb-screening"
  - PDD link prefixed with https://docs.google.com/document/...
  - Idea form prefixed with "idea:..."

For idea/PDD inputs, delegates to apps.opps.opp_creator.create_opp which
creates the opp folder + a working Session + injects the kickoff message.
run_id is "run-001" (hardcoded by opp_creator).

For existing-slug input, mints a new run_id (YYYYMMDD-HHMM), creates a
Session bound to (slug, run_id), and injects `Run /ace:run <slug>/<run_id>.`
as a user chat message — the turn_driver picks this up and spawns the CLI.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from apps.sessions.models import Message, Session

logger = logging.getLogger(__name__)


class RunStartError(Exception):
    pass


def _is_pdd_link(text: str) -> bool:
    return text.startswith("https://docs.google.com/document/")


def _is_idea(text: str) -> bool:
    return text.startswith("idea:")


def _extract_idea(text: str) -> str:
    return text[len("idea:"):].lstrip()


def _mint_run_id() -> str:
    """Match the `YYYYMMDD-HHMM` pattern used by /ace:run + opp_forker.

    Collision-bumping is the slash-command's responsibility; we just
    propose a fresh one. If two Slack triggers race in the same minute,
    /ace:run will bump one to the next minute on its own.
    """
    return datetime.now(UTC).strftime("%Y%m%d-%H%M")


def _next_turn_index(session: Session) -> int:
    last = session.messages.order_by("-turn_index").first()
    return (last.turn_index + 1) if last else 0


def start_run_from_slack(*, slug_or_link: str, user, workspace) -> tuple[str, str]:
    """Returns (slug, run_id). Raises RunStartError on misuse.

    For idea/PDD inputs: delegates to opp_creator.create_opp which
    creates the opp folder + a working Session + injects the kickoff
    message. run_id is "run-001" (its hardcoded default).

    For existing-slug input: mints a new run_id, creates a Session
    bound to it, and injects `Run /ace:run <slug>/<run_id>.`.
    """
    if not slug_or_link:
        raise RunStartError("missing opp slug or PDD link")

    if _is_idea(slug_or_link) or _is_pdd_link(slug_or_link):
        from apps.opps.opp_creator import CreateOppError, create_opp
        idea_text = _extract_idea(slug_or_link) if _is_idea(slug_or_link) else ""
        pdd_text = ""
        # For a PDD link, we store the link as idea text (the real CLI will
        # fetch the PDD from Drive; we just need to seed the session).
        if _is_pdd_link(slug_or_link):
            idea_text = slug_or_link

        # Build a slug from the idea text (first 40 chars, lowercased, slugified).
        import re
        from datetime import datetime

        raw = re.sub(r"[^a-z0-9]+", "-", idea_text[:40].lower()).strip("-") or "new-opp"
        datestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
        slug = f"{raw}-{datestamp}"[:63]

        # We need a DriveClient to create the opp folder. In v1 the Slack
        # path reuses the workspace's Drive root. Import drive_client lazily.
        from django.conf import settings

        from apps.opps.drive_client import GoogleDriveClient

        drive = GoogleDriveClient(settings.ACE_DRIVE_SA_KEY_JSON)
        ace_folder_id = workspace.drive_root_folder_id

        try:
            result = create_opp(
                drive=drive,
                ace_root_folder_id=ace_folder_id,
                owner=user,
                slug=slug,
                display_name=slug,
                idea=idea_text or "Idea from Slack.",
                pdd=pdd_text,
                workspace=workspace,
            )
        except CreateOppError as e:
            raise RunStartError(str(e)) from e
        # create_opp seeds the session + kickoff message internally.
        return result.slug, "run-001"

    # Existing-slug path: verify opp exists, mint a new run_id.
    slug = slug_or_link.strip()

    # Check the opp exists in the OppWorkspace table (fastest check;
    # Drive verification happens when the CLI actually runs).
    from apps.opps.models import OppWorkspace

    opp_exists = OppWorkspace.objects.filter(
        slug=slug, workspace=workspace
    ).exists()
    if not opp_exists:
        raise RunStartError(f"no opp `{slug}` in workspace `{workspace.slug}`")

    run_id = _mint_run_id()
    session = Session.create_with_owner(
        owner=user,
        title=f"Slack run · {slug} · {run_id}",
        backend_kind="cli",
        status="active",
        source="web",
        opp_slug=slug,
        opp_run_id=run_id,
        workspace=workspace,
    )
    Message.objects.create(
        session=session,
        turn_index=_next_turn_index(session),
        role="user",
        sender_user=user,
        content={"type": "text", "source": "slack-trigger"},
        plaintext=f"Run /ace:run {slug}/{run_id}.",
        status="complete",
    )
    return slug, run_id
