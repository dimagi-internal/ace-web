"""RFC 7807 problem+json error model + helpers."""
from __future__ import annotations

from typing import Any

from ninja.errors import HttpError
from pydantic import BaseModel, Field


class Problem(BaseModel):
    """RFC 7807 application/problem+json body.

    `type` is a stable URI identifying the error class.
    `title` is human-readable, stable per `type`.
    `status` mirrors the HTTP status.
    `detail` is the per-occurrence message.
    `instance` is the request path (optional).
    """

    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    extras: dict[str, Any] | None = None


class ProblemError(HttpError):
    """Raise this anywhere in a v2 handler to short-circuit with a problem+json response."""

    def __init__(
        self,
        status: int,
        title: str,
        *,
        type_: str = "about:blank",
        detail: str | None = None,
        extras: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(status, title)
        self.problem_type = type_
        self.problem_title = title
        self.problem_detail = detail
        self.problem_extras = extras


# Common type URIs — extend as needed.
TYPE_VALIDATION = "https://ace-web.dimagi.com/problems/validation"
TYPE_AUTH = "https://ace-web.dimagi.com/problems/auth"
TYPE_FORBIDDEN = "https://ace-web.dimagi.com/problems/forbidden"
TYPE_NOT_FOUND = "https://ace-web.dimagi.com/problems/not-found"
TYPE_CONFLICT = "https://ace-web.dimagi.com/problems/conflict"
TYPE_RATE_LIMIT = "https://ace-web.dimagi.com/problems/rate-limit"
TYPE_UPSTREAM = "https://ace-web.dimagi.com/problems/upstream"
TYPE_INTERNAL = "https://ace-web.dimagi.com/problems/internal"
