"""Session-cookie + Bearer-token auth for Django Ninja routes.

Matches DRF's SessionAuthentication + BearerTokenAuthentication:
trust ``request.user`` from Django's auth middleware (session), or
fall back to a ``Bearer <token>`` Authorization header (personal tokens).
Raises ``ProblemError(401, …)`` when neither credential is present/valid.

CSRF: ``SessionAuth`` (via ``APIKeyCookie``) defaults ``csrf=True``, so
unsafe methods (POST/PUT/PATCH/DELETE) from session-authenticated callers
are CSRF-checked automatically.  Bearer-authenticated callers skip CSRF
(stateless tokens are not susceptible to cross-site forgery).
"""
from __future__ import annotations

from django.http import HttpRequest
from ninja.security import SessionAuth

from .errors import TYPE_AUTH, ProblemError


class DjangoSessionAuth(SessionAuth):
    """Session auth that raises problem+json instead of returning None.

    Also accepts ``Authorization: Bearer <token>`` for personal-token
    callers (the ACE CLI and automated scripts).  Bearer tokens bypass
    CSRF because they are stateless credentials not tied to the browser
    cookie jar.
    """

    def authenticate(self, request: HttpRequest, key: str | None) -> object | None:
        # 1. Bearer-token path — checked first so the CLI tool doesn't need
        #    a session cookie.
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            raw = auth_header[len("Bearer "):]
            from django.utils import timezone

            from apps.auth.models import PersonalToken

            token = PersonalToken.lookup(raw)
            if token is None:
                raise ProblemError(
                    401,
                    "Invalid or revoked bearer token",
                    type_=TYPE_AUTH,
                )
            PersonalToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
            # Set request.user so view functions that reference it directly
            # (e.g. ``list_tokens(request.user)``) receive the resolved user.
            request.user = token.user  # type: ignore[assignment]
            return token.user

        # 2. Session-cookie path — standard Django session.
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
