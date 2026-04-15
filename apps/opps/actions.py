"""Translate web actions (Run, Rerun, Approve, Reject) into chat messages
injected into the opp's working session.

Phrasing is centralized here so frontend buttons can change without
touching the prompt wording."""
from __future__ import annotations

from dataclasses import dataclass

from apps.sessions.models import Message, Session


class ActionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class ActionPayload:
    skill: str
    reason: str | None = None


def _next_turn_index(session: Session) -> int:
    last = session.messages.order_by("-turn_index").first()
    return (last.turn_index + 1) if last else 0


def _phrase(action: str, slug: str, payload: ActionPayload) -> str:
    if action == "run":
        return f"Run /ace:step {payload.skill} for {slug}."
    if action == "rerun":
        return f"Rerun /ace:step {payload.skill} for {slug}."
    if action == "approve":
        return f"Approve the gate for {payload.skill} in {slug}."
    if action == "reject":
        return (
            f"Reject the gate for {payload.skill} in {slug}. "
            f"Reason: {payload.reason}"
        )
    raise ActionError("unknown-action", f"unknown action {action!r}")


def inject_action(
    *, session: Session, action: str, slug: str, payload: ActionPayload, user
) -> Message:
    if action == "reject" and not payload.reason:
        raise ActionError("reason-required", "reject requires a reason")
    if not payload.skill:
        raise ActionError("skill-required", "action requires a skill name")
    text = _phrase(action, slug, payload)
    return Message.objects.create(
        session=session,
        turn_index=_next_turn_index(session),
        role="user",
        sender_user=user,
        content={"type": "text", "source": "opps-action", "action": action},
        plaintext=text,
        status="complete",
    )
