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

    def _get_key(self, request: HttpRequest) -> str | None:
        # Bearer-token callers are stateless and not susceptible to CSRF;
        # short-circuit the parent's CSRF check so unsafe-method requests
        # (POST/PUT/PATCH/DELETE) authenticated only by a Bearer header
        # are not rejected before ``authenticate()`` ever runs.
        if request.META.get("HTTP_AUTHORIZATION", "").startswith("Bearer "):
            return None
        return super()._get_key(request)

    def authenticate(self, request: HttpRequest, key: str | None) -> object | None:
        # 0. A canopy-delegated MCP tool call (host grant). Set only inside the
        #    MCP server's DelegatedToolScope middleware, around the in-process
        #    request one allowed tool makes — never from anything a client
        #    sends — so it cannot be reached over HTTP.
        from apps.canopy.grant import current_delegation

        delegated = current_delegation()
        if delegated is not None:
            return self._authenticate_delegated(request, delegated)

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

    @staticmethod
    def _authenticate_delegated(request: HttpRequest, delegated) -> object:
        """Run AS the visitor the delegated token names, read-only.

        The scope → tool map already limited which route this is; GET-only is
        the second fence, so a scope added carelessly still cannot write. Then
        every existing per-user rule (workspace membership) applies as it would
        to the visitor themselves.
        """
        from django.contrib.auth import get_user_model

        if request.method not in ("GET", "HEAD"):
            raise ProblemError(403, "Delegated access is read-only", type_=TYPE_AUTH)
        user = get_user_model().objects.filter(
            email__iexact=delegated.subject, is_active=True).first()
        if user is None:
            raise ProblemError(401, "The delegated subject has no active account",
                               type_=TYPE_AUTH)
        request.user = user  # type: ignore[assignment]
        return user


session_auth = DjangoSessionAuth()
