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


class RunActorUnresolvable(Exception):
    """canopy resolves the run's owner to a CONTACT, which canopy confines to
    ask-only — a run started for them would be accepted and then never execute.

    Observed: spark-facilitator/20261001-2208 (canopy turn 2727e227). ace@ was
    resolved as a contact, the ACE session refused to run, ace-web still
    answered 202, and the run sat at Phase 3 `pending` forever.
    """

    def __init__(self, email: str):
        self.email = email
        super().__init__(
            f"canopy resolves {email} to a contact, not a user; canopy confines "
            "a contact to ask-only, so a run started for them would never "
            "execute. Give that identity a canopy user account (or start the "
            "run as a person who has one)."
        )


class RunActorUnverified(Exception):
    """canopy could not be asked who the run's owner is, so it is unknown
    whether the run could execute."""

    def __init__(self, email: str, detail: str):
        self.email, self.detail = email, detail
        super().__init__(f"could not resolve {email} in canopy: {detail}")


def preflight_run_actor(email: str) -> None:
    """Refuse BEFORE minting anything when a run for ``email`` cannot execute.

    For RUN-STARTING actions only (seeded-run). Ordinary workbench chat for a
    contact — an external reviewer asking questions — is a different path and
    is deliberately not gated: ask-only is exactly what a contact's chat is.

    No-op when run execution is off (the legacy subprocess path does not go
    through canopy). Raises ``RunActorUnresolvable`` for a contact and
    ``RunActorUnverified`` when canopy cannot be reached.
    """
    if not enabled():
        return
    try:
        principal = client.act_as(email)
    except client.CanopyError as exc:
        raise RunActorUnverified(email, f"{exc.status}: {exc.detail}") from exc
    if principal.is_contact:
        raise RunActorUnresolvable(email)


def enabled() -> bool:
    return bool(
        settings.CANOPY_RUN_EXECUTION
        and settings.CANOPY_BASE_URL
        and settings.CANOPY_SIGNING_KEY
    )


def actor_email(session) -> str:
    """The person this run is FOR — its owner, whose command ace-web is carrying
    out. canopy resolves them to their account or their contact; there is no
    fallback identity, because a run attributed to someone else is a run that
    lies about who asked. No owner, no run.

    This is the actor for work nobody clicked: the run's first turn (its owner
    started it), the post-deploy sweep continuing it, and the background reads
    (progress, transcripts). A turn a PERSON causes — a resume — names its own
    actor instead (``dispatch_turn(actor=...)``)."""
    email = (getattr(session.owner, "email", "") or "").strip()
    if not email:
        raise DispatchError("this run has no owner to act for")
    return email


def _norm(email: str) -> str:
    return (email or "").strip().lower()


def _turn_actor_email(session, actor) -> str:
    """Who THIS turn is dispatched as: ``actor`` when a person caused it, else
    the run's owner (``actor_email``)."""
    if actor is None:
        return actor_email(session)
    email = (getattr(actor, "email", "") or "").strip()
    if not email:
        raise DispatchError("the person resuming this run has no email to act as")
    return email


def _canopy_session_holder(session) -> str:
    """The principal ``session.canopy_session_id`` belongs to in canopy. Blank
    ``canopy_session_actor`` predates the column, when only owners dispatched."""
    return session.canopy_session_actor or actor_email(session)


def _run_metadata(session, requested_by: str = "") -> dict:
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
    requested_by = requested_by or getattr(session, "requested_by", "")
    if requested_by:
        # Who ASKED (attribution) — the owner, which canopy acts as, may be an
        # agent identity carrying a human's request; for a resume someone
        # clicked, it is the clicker.
        meta["requested_by"] = requested_by
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


def dispatch_turn(assistant_message_id: int, *, actor=None) -> str:
    """Enqueue the canopy Turn that executes this assistant turn.

    ``actor`` is the person who CAUSED this turn (a resume someone clicked);
    canopy runs the turn with that person's own authority. ``None`` means no
    person did — the run's first turn, or the post-deploy sweep continuing a
    run its owner already started — and the turn runs as the owner.

    Why the actor never borrows the owner's canopy session: canopy makes a web
    session private to its creator, and a turn sent into a session that the
    agent's owner/admin started runs in that session's FULL profile
    (canopy-web ``session_writer``). Sending a member's resume into an
    ace@-owned session would therefore hand them ACE's whole authority — the
    gap this parameter closes. So a turn whose actor is not the holder of
    ``canopy_session_id`` gets a canopy session of its OWN, and the old one is
    stopped as its holder (cancelling a dead turn is not acting with its
    authority).

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
        email = _turn_actor_email(session, actor)
        person = client.act_as(email)

        canopy_session_id = session.canopy_session_id
        if canopy_session_id and _norm(_canopy_session_holder(session)) == _norm(email):
            # A resume declares the previous turn dead. Tell canopy, or the stale
            # turn keeps holding one_executing_turn_per_session and this send
            # queues behind a turn that will never finish.
            try:
                person.stop(canopy_session_id)
            except client.CanopyError:
                log.warning("canopy stop failed for session %s; continuing", canopy_session_id)
        else:
            if canopy_session_id:
                # Someone else holds the run's canopy session. Retire its dead
                # turn as THEM (a stop, never a send), then start this turn in
                # a session of the actor's own — see the docstring.
                _stop_as_holder(session, canopy_session_id)
            is_owner = _norm(email) == _norm(actor_email(session))
            base = session.title or f"ace-run: {session.opp_slug}/{session.opp_run_id}"
            created = person.create_session(
                title=base if is_owner else f"{base} — resumed by {email}",
                metadata=_run_metadata(session, requested_by="" if is_owner else email),
            )
            canopy_session_id = str(created["id"])
            Session.objects.filter(pk=session.pk).update(
                canopy_session_id=canopy_session_id,
                # Blank for the owner keeps the legacy reading ("the owner").
                canopy_session_actor="" if is_owner else email,
            )

        sent = person.send(
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
    # Something IS driving this run now — canopy is. The beat is written by the
    # subprocess on the legacy path and there is no subprocess here, so without
    # this the run is born with a NULL heartbeat and a non-terminal assistant
    # turn, which is exactly `Session.interrupted()`: dispatched and instantly
    # listed as dead. `run_state.reconcile_session` keeps it fresh from here on.
    Session.objects.filter(pk=session.pk).update(driver_heartbeat_at=timezone.now())
    return str(turn_id)


def _stop_as_holder(session, canopy_session_id: str) -> None:
    """Best-effort: cancel the turn left in ``canopy_session_id`` as the
    principal that holds it. A failure only means a dead turn lingers in a
    session nothing will send to again — it cannot block the new turn, which
    runs in a different session."""
    try:
        client.act_as(_canopy_session_holder(session)).stop(canopy_session_id)
    except (client.CanopyError, DispatchError) as exc:
        log.warning("canopy stop as holder failed for session %s: %s", canopy_session_id, exc)


def start_turn(assistant_message_id: int, *, actor=None) -> None:
    """The ONE entry point every run caller uses. Routes to canopy when run
    execution is on, and to the legacy in-process subprocess when it is not.

    ``actor``: the person who caused this turn, when one did (a resume they
    clicked) — see ``dispatch_turn``. Callers with no such person (a run's
    first turn, which its owner started; the post-deploy sweep) omit it and the
    turn runs as the run's owner. Ignored on the legacy subprocess path, which
    does not go through canopy.

    Imported through the module (not `from ... import start_turn_subprocess`)
    so the existing monkeypatches on
    `apps.sessions.turn_driver.start_turn_subprocess` keep working.
    """
    if enabled():
        dispatch_turn(assistant_message_id, actor=actor)
        return
    from apps.sessions import turn_driver

    turn_driver.start_turn_subprocess(assistant_message_id)
