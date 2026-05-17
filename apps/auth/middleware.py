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

import logging
from typing import Callable

from django.http import HttpRequest, HttpResponse
from django.utils import timezone

logger = logging.getLogger(__name__)


class BearerTokenAuthMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        self._authenticate(request)
        return self.get_response(request)

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
