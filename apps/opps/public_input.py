"""Input hygiene for the public run summary's WRITE surfaces.

The public per-run summary has no login and cannot get one — a partner
cannot self-serve an ace-web account, and requiring one is a barrier in
front of speculative work whose whole point is that engaging with it
should be cheap. So everything a partner writes from that page arrives
unauthenticated, and every one of those endpoints needs the same four
things before the payload is allowed anywhere near Drive:

* **control characters stripped** — they survive YAML round-trips and
  render as mojibake in the doc a human eventually reads;
* **HTML rejected, not stripped** — React escapes on render, but the text
  also lands in YAML that gets rendered into a Google Doc via markdown, so
  "the frontend escapes it" is not the whole story. Silently mangling a
  reviewer's words is worse than refusing them;
* **length capped before any Drive round-trip**, so an oversized body
  costs one 400 and not a read-modify-write of a Drive file;
* **an identity**, which is where the two surfaces differ and why this
  module owns `resolve_reviewer` rather than each endpoint doing it.

`resolve_reviewer` is the single answer to "who is writing this?":

* **Signed in ⇒ never anonymous.** The session (or Bearer PAT) identity
  wins outright and the body's self-reported name is ignored. Asking a
  signed-in member to type their name is both noise and an invitation to
  type someone else's.
* **Not signed in ⇒ a required self-reported name**, asked at submit and
  never as a gate before they can start typing.

The distinction is carried into the store as `verified`, so a reader can
always tell which kind of identity stands behind a change. That — plus
history and reversibility — is what makes an unauthenticated write
surface safe, in the same way it is what makes a Google Doc with
anyone-with-link editing safe. It is not permission.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Anything that looks like the start of an HTML/XML tag.
_HTML_RE = re.compile(r"<\s*[/!?]?\s*[A-Za-z]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")

MIN_NAME_CHARS = 2
MAX_NAME_CHARS = 80
MAX_EMAIL_CHARS = 254


class PublicInputRejected(Exception):
    """Caller-friendly validation failure. ``code`` maps to an HTTP status."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def collapse(value: str) -> str:
    return _CONTROL_RE.sub("", str(value or "")).strip()


def reject_html(value: str, field: str) -> str:
    if _HTML_RE.search(value):
        raise PublicInputRejected("invalid", f"{field} may not contain HTML.")
    return value


def clean_name(raw: str | None, *, missing_message: str | None = None) -> str:
    name = re.sub(r"\s+", " ", collapse(raw))
    if len(name) < MIN_NAME_CHARS:
        raise PublicInputRejected(
            "invalid",
            missing_message
            or "Tell us who you are — a change nobody can attribute can't be "
            "questioned or credited.",
        )
    if len(name) > MAX_NAME_CHARS:
        raise PublicInputRejected(
            "invalid", f"Name is longer than {MAX_NAME_CHARS} characters.",
        )
    return reject_html(name, "Name")


def clean_email(raw: str | None) -> str | None:
    email = collapse(raw)
    if not email:
        return None
    if len(email) > MAX_EMAIL_CHARS or not _EMAIL_RE.match(email):
        raise PublicInputRejected("invalid", "That doesn't look like an email address.")
    return email


def clean_text(
    raw: str | None,
    *,
    field: str,
    min_chars: int,
    max_chars: int,
    too_short: str,
) -> str:
    text = _CONTROL_RE.sub("", str(raw or "").replace("\r\n", "\n")).strip()
    if len(text) < min_chars:
        raise PublicInputRejected("invalid", too_short)
    if len(text) > max_chars:
        raise PublicInputRejected(
            "invalid", f"{field} is capped at {max_chars} characters.",
        )
    return reject_html(text, field)


@dataclass(frozen=True)
class Reviewer:
    """Who made a change, and whether we actually know that.

    ``verified`` is the only field that distinguishes a signed-in member
    from a partner who typed a name into a box. It is recorded, shown, and
    never used to decide whether the write is allowed — reviewer 2 changing
    reviewer 1's answer and Dimagi changing either is the same act.
    """

    email: str
    name: str
    verified: bool

    @property
    def display(self) -> str:
        return self.name or self.email or "Anonymous"


def session_identity_is_trustworthy(request) -> bool:
    """Can we ATTRIBUTE this write to the session's user?

    These endpoints are ``csrf_exempt`` (django-ninja's default) because
    they must accept a genuinely anonymous POST. That is fine for the
    write itself — anyone may edit — but it would let a third-party page
    make a signed-in member's browser file a change under THEIR name.
    Nothing is gained that an anonymous post couldn't already do except
    the attribution, and attribution is the whole safety mechanism here.

    So the session identity is claimed only when the request also passes
    Django's normal CSRF check. Failing that we fall back to the
    anonymous path (which then requires a typed name) rather than
    rejecting: degrading to "tell us who you are" keeps the surface
    usable, and rejecting would punish a member for a missing cookie.
    """
    from django.middleware.csrf import CsrfViewMiddleware

    return CsrfViewMiddleware(lambda _r: None).process_view(
        request, None, (), {},
    ) is None


def resolve_reviewer(
    user, *, reviewer: str | None, reviewer_email: str | None,
) -> Reviewer:
    """Session identity if there is one; else the self-reported name.

    A signed-in caller's typed name is deliberately discarded rather than
    merged: two names on one change is worse than one.
    """
    if user is not None and getattr(user, "is_authenticated", False):
        email = collapse(getattr(user, "email", "") or "")
        name = collapse(getattr(user, "display_name", "") or "") or email
        return Reviewer(email=email, name=name, verified=True)
    return Reviewer(
        email=clean_email(reviewer_email) or "",
        name=clean_name(reviewer),
        verified=False,
    )
