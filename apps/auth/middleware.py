"""Bearer-token authentication middleware for Django page routes.

Django Ninja's auth classes only run on API routes. Django page views
(everything in ``config.urls`` that isn't ``/api/...``) rely on
``request.user`` set by the standard ``AuthenticationMiddleware`` from
a session cookie. That leaves Bearer-token callers — the probe,
scripted automation, anyone with a PAT — unable to load page routes.

This middleware closes the gap: if the incoming request carries an
``Authorization: Bearer <token>`` header and ``request.user`` isn't
already authenticated, look the PAT up and stamp the resolved user onto
the request. Page-level ``@login_required`` decorators then see a real
user, same as if a session cookie were present.

CSRF: Bearer-authenticated requests are stateless and not vulnerable to
cross-site forgery, but Django's ``CsrfViewMiddleware`` doesn't know
that — it only short-circuits on session cookies. The middleware sets
``request._dont_enforce_csrf_checks = True`` for Bearer-authed unsafe
methods, matching the same opt-out the Ninja auth class performs.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable

from django.db import OperationalError
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

logger = logging.getLogger(__name__)


def _db_unavailable_response() -> HttpResponse:
    """Retryable 503 (RFC 7807) for a transient DB-connection failure.

    A saturated shared RDS ("FATAL: remaining connection slots are reserved
    …") was surfacing as an unhandled 500 from the PersonalToken lookup below
    — hard-failing every authenticated request, including the whole ACE run
    driving through /api/mobile/*. OperationalError is transient, so map it to
    a 503 + Retry-After that the ace-mobile MCP's retry envelope (and any
    sane caller) can recover from instead of dying. See the run 20260603-2126
    incident.
    """
    resp = HttpResponse(
        json.dumps({
            "type": "https://ace-web.dimagi.com/problems/unavailable",
            "title": "Database temporarily unavailable",
            "status": 503,
            "detail": "db_unavailable",
        }),
        status=503,
        content_type="application/problem+json",
    )
    resp["Retry-After"] = "5"
    return resp


class BearerTokenAuthMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # The auth lookup is the FIRST DB hit on a Bearer-authed request, so a
        # DB-connection failure here is what 500s the automation path. Catch it
        # at the source and degrade to a retryable 503 (Django would otherwise
        # convert the middleware-raised exception to a 500 we can't intercept
        # downstream).
        try:
            self._authenticate(request)
        except OperationalError:
            logger.warning("DB unavailable during bearer auth; 503", exc_info=True)
            return _db_unavailable_response()
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse | None:
        """Catch DB-connection failures raised by VIEWS too (the __call__ catch
        only covers this middleware's own lookup). Returns 503 for transient DB
        outages; lets every other exception fall through to Django's handler."""
        if isinstance(exception, OperationalError):
            logger.warning("DB unavailable during request; 503", exc_info=True)
            return _db_unavailable_response()
        return None

    @staticmethod
    def _authenticate(request: HttpRequest) -> None:
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            return

        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Bearer "):
            return

        raw = header[len("Bearer "):].strip()
        if not raw:
            return

        from apps.auth.models import PersonalToken

        token = PersonalToken.lookup(raw)
        if token is None:
            return

        PersonalToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        request.user = token.user
        request._dont_enforce_csrf_checks = True
