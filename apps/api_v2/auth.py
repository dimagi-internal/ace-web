"""Session-cookie auth for Django Ninja routes.

Matches DRF's SessionAuthentication: trust `request.user` from Django's
auth middleware. Raises `ProblemError(401, "Authentication required")`
when no user is attached.

CSRF: `SessionAuth` (via `APIKeyCookie`) defaults `csrf=True`, so
unsafe methods (POST/PUT/PATCH/DELETE) are CSRF-checked automatically.
django-ninja 1.6.x has no `csrf=` kwarg on `NinjaAPI()` itself — the
enforcement lives on the auth class.
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
