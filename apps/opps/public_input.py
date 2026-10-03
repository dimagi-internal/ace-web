"""Input hygiene for the run summary's WRITE surfaces.

Since 2026-10-03 every write on the summary (change, confirm, comment)
needs a signed-in workspace MEMBER — ``apps.opps.api._member_reviewer``
refuses anyone else with 401/403, and the identity on every write is the
session's (``Reviewer.verified`` is always True there). Jonathan: "no
anonymous editing at all." What stays here is the hygiene every payload
needs before it is allowed near Drive:

* **control characters stripped** — they survive YAML round-trips and
  render as mojibake in the doc a human eventually reads;
* **HTML rejected, not stripped** — React escapes on render, but the text
  also lands in YAML that gets rendered into a Google Doc via markdown, so
  "the frontend escapes it" is not the whole story. Silently mangling a
  reviewer's words is worse than refusing them;
* **length capped before any Drive round-trip**, so an oversized body
  costs one 400 and not a read-modify-write of a Drive file.
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
    """Who made a change. ``verified`` is recorded on the row; the summary's
    write endpoints only ever produce verified reviewers (the session user),
    while the Workbench's buffered path builds its own."""

    email: str
    name: str
    verified: bool

    @property
    def display(self) -> str:
        return self.name or self.email or "Anonymous"


def session_identity_is_trustworthy(request) -> bool:
    """Can we ATTRIBUTE this write to the session's user?

    These endpoints are ``csrf_exempt`` at the router, so without this a
    third-party page could make a signed-in member's browser file a change
    under THEIR name. A member write that fails Django's normal CSRF check
    is therefore refused (403) by ``_member_reviewer``.
    """
    from django.middleware.csrf import CsrfViewMiddleware

    return CsrfViewMiddleware(lambda _r: None).process_view(
        request, None, (), {},
    ) is None


