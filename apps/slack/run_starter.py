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
as a completed user turn.

Both branches then create a PENDING ASSISTANT TURN and dispatch it through
``apps.canopy.run_dispatch.start_turn`` — the same seam
``apps.opps.api::seeded_run`` uses, so a Slack run inherits
``CANOPY_RUN_EXECUTION`` (off: the legacy detached ``manage.py drive_turn``
subprocess; on: a session-targeted canopy Turn).

Until 2026-07-26 neither branch did any of that. This module created the
user turn and returned; nothing read it. There are no signals, no Celery,
no custom ``Message.save()`` and the WebSocket consumer that once spawned
turns was deleted in 3a996df, so ``/ace run <slug>`` posted "Kicking off…"
and then did nothing, forever — and the post-deploy resume sweep could not
rescue it either, because ``Session.interrupted`` /
``Session.resumable_after_deploy`` both require an assistant row. The old
docstring's claim that "the turn_driver picks this up and spawns the CLI"
was never true at any commit; it was transcribed from a design doc. See
docs/plans/2026-07-26-run-convergence-ace-side.md.
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


def _dispatch_assistant_turn(session: Session) -> Message:
    """Create the pending assistant turn and execute it.

    This is the whole point of a triggered run, and it is what this module
    never did. The placeholder is load-bearing twice over: it is what
    ``run_dispatch`` executes, and it is what makes the run visible to the
    post-deploy resume sweep (``Session.interrupted`` /
    ``resumable_after_deploy`` both filter on ``messages__role="assistant"``).

    A dispatch failure is surfaced as ``RunStartError`` so Slack renders the
    real reason. Letting it escape as a bare exception instead would hit
    ``verbs_run``'s ``except Exception`` and be reported as the useless
    "Internal error starting run."
    """
    from apps.canopy.run_dispatch import DispatchError, start_turn

    assistant = Message.objects.create(
        session=session,
        turn_index=_next_turn_index(session),
        role="assistant",
        content={"text": ""},
        plaintext="",
        status="pending",
    )
    try:
        start_turn(assistant.id)
    except DispatchError as exc:
        # start_turn has already marked the assistant message errored with a
        # `canopy-dispatch:` detail, so the run is diagnosable in the DB too.
        logger.exception("dispatch failed for slack run session %s", session.slug)
        raise RunStartError(f"could not start the run: {exc.detail}") from exc
    return assistant


def start_run_from_slack(*, slug_or_link: str, user, workspace) -> tuple[str, str]:
    """Returns (slug, run_id). Raises RunStartError on misuse.

    For idea/PDD inputs: delegates to opp_creator.create_opp which
    creates the opp folder + a working Session + injects the kickoff
    message. run_id is "run-001" (its hardcoded default).

    For existing-slug input: mints a new run_id, creates a Session
    bound to it, and injects `Run /ace:run <slug>/<run_id>.`.

    Either way the run then gets a pending assistant turn, dispatched
    through ``apps.canopy.run_dispatch.start_turn``.
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
        #
        # NOT GoogleDriveClient(settings.ACE_DRIVE_SA_KEY_JSON): that passes a
        # raw JSON *string* where googleapiclient wants a credentials *object*,
        # which raises `AttributeError: 'str' object has no attribute
        # 'authorize'` — swallowed by verbs_run/verbs_new's bare except and
        # reported as "Internal error starting run", with nothing created. It
        # was the only hand-constructed GoogleDriveClient in the repo; every
        # other caller goes through the service-account registry.
        from apps.opps.drive_client import get_drive_client
        from apps.service_accounts.exceptions import ServiceAccountNotFound

        try:
            drive = get_drive_client(workspace=workspace)
        except ServiceAccountNotFound as exc:
            raise RunStartError(f"Drive is not configured: {exc}") from exc
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
        # create_opp seeds the session + kickoff USER message internally, but
        # no assistant turn and no execution — so, exactly like the slug branch
        # below, `/ace new` and `/ace run <pdd-link>` would have created an opp
        # and then sat there. Dispatch the kickoff.
        _dispatch_assistant_turn(result.working_session)
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
    _dispatch_assistant_turn(session)
    return slug, run_id
