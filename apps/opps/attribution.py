"""Who asked for a run — `requested_by` beside `initiated_by`.

`initiated_by` is the AUTHENTICATED actor: whoever's token made the call. It
stays truthful. When that actor is an agent identity (ACE's bot,
``ace@dimagi-ai.com``) acting for a human, the human is recorded separately as
``requested_by`` — attribution, not authentication.

Observed case: spark-facilitator/20261001-2208 (canopy turn 2727e227). Jonathan
asked his own Claude Code session for a seeded run; the session called the
action with ACE's bot token, so every record said ace@ started it and nothing
said Jonathan asked.

Rules (``resolve_requested_by``):

* human caller: defaults to their own email; naming anyone else is refused (a
  human cannot attribute a run to someone else).
* agent caller: the supplied value is honoured; absent ⇒ ``None`` — we record
  nothing rather than guess.
"""

from __future__ import annotations

from django.conf import settings


class RequestedByForbidden(ValueError):
    """A human caller named someone other than themselves as ``requested_by``."""


def _norm(email: str | None) -> str:
    return (email or "").strip().lower()


def is_agent_identity(user) -> bool:
    """True when ``user`` is an agent identity (``settings.ACE_AGENT_IDENTITIES``)."""
    email = _norm(getattr(user, "email", ""))
    if not email:
        return False
    return email in {_norm(e) for e in settings.ACE_AGENT_IDENTITIES}


def resolve_requested_by(user, supplied: str | None) -> str | None:
    """The human this call is acting for, per the module rules."""
    supplied_norm = _norm(supplied)
    if is_agent_identity(user):
        return supplied_norm or None
    own = _norm(getattr(user, "email", ""))
    if supplied_norm and supplied_norm != own:
        raise RequestedByForbidden(
            f"requested_by={supplied!r} is not you ({own or 'unknown'}); only an "
            "agent identity may start a run on someone else's behalf"
        )
    return own or None


def creator_label(state: dict | None) -> str | None:
    """How a run's creator is DISPLAYED, from its ``run_state.yaml``.

    An explicit ``created_by`` wins (legacy runs). Otherwise the human who
    asked, marked "via ACE" when an agent carried the request out, falling back
    to ``initiated_by``.
    """
    state = state if isinstance(state, dict) else {}
    if state.get("created_by"):
        return state["created_by"]
    requested = state.get("requested_by")
    initiated = state.get("initiated_by")
    if requested:
        if initiated and _norm(initiated) != _norm(requested):
            return f"{requested} (via ACE)"
        return requested
    return initiated
