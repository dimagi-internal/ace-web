"""Session-cookie auth for Django Ninja routes.

Matches DRF's SessionAuthentication: trust `request.user` from Django's
auth middleware. Raises `ProblemError(401, "Authentication required")`
when no user is attached.

CSRF: Ninja enforces CSRF on unsafe methods by default when using
session auth. The v2 NinjaAPI is constructed with `csrf=True` in
api.py once this auth class is wired in.
"""
from __future__ import annotations

from django.http import HttpRequest
from ninja.security import SessionAuth

from .errors import TYPE_AUTH, ProblemError


class DjangoSessionAuth(SessionAuth):
    """Session auth that raises problem+json instead of returning None."""

    def authenticate(self, request: HttpRequest, key: str | None) -> object | None:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise ProblemError(
                401,
                "Authentication required",
                type_=TYPE_AUTH,
                detail="This endpoint requires an authenticated session.",
            )
        return user


session_auth = DjangoSessionAuth()
