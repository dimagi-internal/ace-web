"""Enqueue an ACE run onto canopy's harness instead of spawning `claude -p`.

The drop-in replacement for `apps.sessions.turn_driver.start_turn_subprocess`
(spec: canopy-web docs/superpowers/specs/2026-07-26-run-execution-convergence-
design.md, item 4). Same call shape — one assistant-Message id — so the three
production call sites change by one line each.

Turns target the canopy SESSION, never the agent. `one_executing_turn_per_agent`
is a unique constraint on the agent for claimed/running turns, so `Turn(agent=ace)`
would serialize every ACE run in the fleet to one at a time;
`one_executing_turn_per_session` matches ace's real shape (one turn at a time
within a run, many runs at once). `Turn.target` resolves `chat_session.agent.slug`,
so ACE still displays as "ace" everywhere in canopy.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from . import client

log = logging.getLogger(__name__)


class DispatchError(Exception):
    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def enabled() -> bool:
    return bool(
        settings.CANOPY_RUN_EXECUTION
        and settings.CANOPY_BASE_URL
        and settings.CANOPY_APP_CREDENTIAL
    )


def _actor_email(session) -> str:
    """Whose canopy identity this run acts as. The owner, or the configured
    fallback — never a guess. canopy's token-exchange 403s an email outside the
    app credential's allowed_delegation_domains, and ace-web has no domain
    filter of its own, so a refusal here is a real and reachable case."""
    email = (getattr(session.owner, "email", "") or "").strip()
    if email:
        return email
    fallback = (settings.CANOPY_RUN_ACTOR_FALLBACK_EMAIL or "").strip()
    if fallback:
        return fallback
    raise DispatchError("no canopy actor: session owner has no email and no fallback is set")


def _run_metadata(session) -> dict:
    """The opaque bag canopy filters its session list on. `origin_key` mirrors
    apps/canopy/api.py's server-side derivation exactly — it is what scopes
    canopy's list to ONE ace workspace, so it must not drift."""
    meta = {"source": "ace-web"}
    if session.workspace_id:
        meta["origin_key"] = f"ace-web:{session.workspace.slug}"
    if session.opp_slug:
        meta["opp_slug"] = session.opp_slug
    if session.opp_run_id:
        meta["opp_run_id"] = session.opp_run_id
    if session.opp_step_skill:
        meta["opp_step_skill"] = session.opp_step_skill
    return meta


def _prompt_for(assistant_message) -> str:
    """The last completed user turn before this assistant placeholder — the same
    text `turn_driver._load_last_user_text` feeds the subprocess."""
    from apps.sessions.models import Message

    user_msg = (
        Message.objects.filter(
            session_id=assistant_message.session_id,
            role="user",
            turn_index__lt=assistant_message.turn_index,
        )
        .order_by("-turn_index")
        .first()
    )
    return user_msg.plaintext if user_msg else ""


def _fail(assistant_message, detail: str) -> None:
    """Never leave a run silently un-dispatched. `start_turn_subprocess` did
    exactly that on a Popen failure (fire-and-forget, no signal) and the message
    sat `pending` forever. The `canopy-dispatch:` prefix keeps a dispatch failure
    distinguishable from an execution failure — and, deliberately, does NOT start
    with "cancelled", so `Session.resumable_after_deploy` will not treat it as a
    deploy casualty and re-resume it in a loop."""
    from apps.sessions.models import Message

    Message.objects.filter(pk=assistant_message.pk).update(
        status="error", error_detail=f"canopy-dispatch: {detail}", completed_at=timezone.now(),
    )


def dispatch_turn(assistant_message_id: int) -> str:
    """Enqueue the canopy Turn that executes this assistant turn.

    Returns the canopy turn id, or "" when run execution is disabled (in which
    case the caller keeps its legacy subprocess path). Raises DispatchError on
    any failure, having first marked the assistant message errored.
    """
    if not enabled():
        return ""

    from apps.sessions.models import Message, Session

    assistant = (
        Message.objects.select_related("session", "session__owner", "session__workspace")
        .filter(pk=assistant_message_id)
        .first()
    )
    if assistant is None:
        raise DispatchError(f"assistant message {assistant_message_id} not found")
    session = assistant.session

    try:
        token = client.exchange_token(_actor_email(session), ttl=3600)["token"]

        canopy_session_id = session.canopy_session_id
        if canopy_session_id:
            # A resume declares the previous turn dead. Tell canopy, or the stale
            # turn keeps holding one_executing_turn_per_session and this send
            # queues behind a turn that will never finish.
            try:
                client.stop_session(token, canopy_session_id)
            except client.CanopyError:
                log.warning("canopy stop failed for session %s; continuing", canopy_session_id)
        else:
            created = client.create_run_session(
                token,
                title=session.title or f"ace-run: {session.opp_slug}/{session.opp_run_id}",
                metadata=_run_metadata(session),
            )
            canopy_session_id = str(created["id"])
            Session.objects.filter(pk=session.pk).update(canopy_session_id=canopy_session_id)

        sent = client.send_message(
            token,
            canopy_session_id,
            text=_prompt_for(assistant),
            client_id=f"acerun:{assistant.pk}",
        )
        turn_id = sent.get("turn_id")
        if not turn_id:
            raise DispatchError("canopy accepted the send but returned no turn_id")
    except DispatchError as exc:
        _fail(assistant, exc.detail)
        raise
    except client.CanopyError as exc:
        _fail(assistant, f"{exc.status}: {exc.detail}")
        raise DispatchError(f"canopy {exc.status}: {exc.detail}") from exc

    Message.objects.filter(pk=assistant.pk).update(canopy_turn_id=str(turn_id))
    return str(turn_id)
