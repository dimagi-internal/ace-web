"""What a run is actually doing, when its execution lives in canopy.

Item 6 of the run-execution convergence spec. With no session-capable cloud
runner online, `no_runner_configured` is the NORMAL state of a freshly
dispatched run — which is exactly why it is a run state and not an error.
Rendering it as "queued" (which is what OppRunsList does today for a run with
no phase yet) makes a run that will never start look like one about to.
"""

from __future__ import annotations

import logging

from django.conf import settings

from . import client

log = logging.getLogger(__name__)

NOT_DISPATCHED = "not_dispatched"
QUEUED = "queued"
NO_RUNNER_CONFIGURED = "no_runner_configured"
WAITING_FOR_RUNNER = "waiting_for_runner"
RUNNING = "running"
DISPATCH_FAILED = "dispatch_failed"
UNKNOWN = "unknown"

STATES = (
    NOT_DISPATCHED, QUEUED, NO_RUNNER_CONFIGURED, WAITING_FOR_RUNNER, RUNNING,
    "done", "failed", "cancelled", "lost", "missed", DISPATCH_FAILED, UNKNOWN,
)

# canopy Turn.status -> our state. `needs_human` folds into RUNNING: the turn is
# claimed and a runner still owns its lease, so it is not stalled on US.
_TURN_STATUS = {
    "queued": QUEUED,
    "claimed": RUNNING,
    "running": RUNNING,
    "needs_human": RUNNING,
    "done": "done",
    "failed": "failed",
    "cancelled": "cancelled",
    "lost": "lost",
    "missed": "missed",
}

DISPATCH_ERROR_PREFIX = "canopy-dispatch:"


def _latest_assistant(session):
    from apps.sessions.models import Message

    return (
        Message.objects.filter(session=session, role="assistant")
        .order_by("-turn_index")
        .first()
    )


def _out(state: str, *, detail: str = "", turn_id: str = "", session_id: str = "") -> dict:
    return {
        "state": state,
        "detail": detail,
        "canopy_turn_id": turn_id,
        "canopy_session_id": session_id,
    }


def execution_state(session) -> dict:
    """The run's execution state, read live from canopy.

    Read-only and side-effect free. Never returns RUNNING on uncertainty: an
    unreachable canopy is UNKNOWN, because "looks like it is working" is the
    exact failure this whole task exists to remove.
    """
    message = _latest_assistant(session)
    if message is None:
        return _out(NOT_DISPATCHED, session_id=session.canopy_session_id)

    if not message.canopy_turn_id:
        detail = message.error_detail or ""
        if message.status == "error" and detail.startswith(DISPATCH_ERROR_PREFIX):
            return _out(
                DISPATCH_FAILED,
                detail=detail[len(DISPATCH_ERROR_PREFIX):].strip(),
                session_id=session.canopy_session_id,
            )
        return _out(NOT_DISPATCHED, session_id=session.canopy_session_id)

    turn_id = message.canopy_turn_id
    try:
        token = client.exchange_token(
            (getattr(session.owner, "email", "") or settings.CANOPY_RUN_ACTOR_FALLBACK_EMAIL),
            ttl=300,
        )["token"]
        turn = client.get_turn(token, turn_id)
    except client.CanopyError as exc:
        log.warning("canopy unreachable reading turn %s: %s", turn_id, exc)
        return _out(UNKNOWN, detail=str(exc), turn_id=turn_id,
                    session_id=session.canopy_session_id)

    state = _TURN_STATUS.get(turn.get("status", ""), UNKNOWN)
    detail = turn.get("result_note", "") or ""

    if state == QUEUED:
        # Only a QUEUED turn can be unclaimable, and only then is the extra call
        # worth making. A turn younger than canopy's 150s UNCLAIMABLE_GRACE is
        # simply absent from the list — that grace is canopy's, and we do not
        # add a second one here.
        try:
            rows = client.list_unclaimable(token)
        except client.CanopyError:
            # An enrichment failure must not demote a turn we KNOW is queued.
            rows = []
        row = next((r for r in rows if str(r.get("turn_id")) == turn_id), None)
        if row is not None:
            # `kind` is ADVISORY. canopy computes "could any runner ever take
            # this?" from runners visible in the CALLING USER's tenant, and
            # ace's delegated user pairs none — so in practice this is always
            # "config". Both states render as "no runner available"; the
            # distinction is a hint, never a branch anything depends on.
            kind = row.get("kind", "config")
            state = WAITING_FOR_RUNNER if kind == "offline" else NO_RUNNER_CONFIGURED
            detail = row.get("reason", "") or detail

    return _out(state, detail=detail, turn_id=turn_id,
                session_id=session.canopy_session_id)
