"""IAP header authentication middleware.

Reads X-Goog-Authenticated-User-Email and X-Goog-Authenticated-User-ID
headers from GCP IAP and either finds or creates the corresponding User row.

In dev (when IAP_REQUIRED is False), accepts a fake header injected from
settings to enable local development without IAP.
"""
import logging
from typing import Callable

from django.conf import settings
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse, JsonResponse

from .models import User

logger = logging.getLogger(__name__)


class IAPHeaderAuthMiddleware:
    """Populate request.user from IAP headers, or fail closed if IAP is required."""

    # NOTE for Plan 1C / Task 6 (Channels): this middleware only runs on HTTP
    # requests via __call__. Django Channels' WebSocket handshakes go through
    # ASGI scope, NOT this middleware. Task 6 must add an equivalent
    # auth-from-IAP-headers helper for the WebSocket consumer scope, or
    # leverage django-channels-auth-token middleware. Without this, WebSocket
    # connections will not have an authenticated user.

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.path == "/api/health":
            # Health check is always public; Cloud Run probes need to hit it.
            return self.get_response(request)

        email, google_sub = self._extract_identity(request)
        if not email:
            if settings.IAP_REQUIRED:
                return JsonResponse(
                    {"data": None, "error": {"code": "unauthenticated", "message": "IAP headers missing"}},
                    status=401,
                )
            email = settings.IAP_DEV_FAKE_EMAIL
            google_sub = settings.IAP_DEV_FAKE_USER_ID

        user = self._get_or_create_user(email=email, google_sub=google_sub)
        request.user = user
        return self.get_response(request)

    def _extract_identity(self, request: HttpRequest) -> tuple[str | None, str | None]:
        raw_email = request.META.get(settings.IAP_HEADER_EMAIL, "")
        raw_sub = request.META.get(settings.IAP_HEADER_USER_ID, "")
        # IAP prefixes the value with "accounts.google.com:"
        email = raw_email.split(":", 1)[-1] if raw_email else None
        sub = raw_sub.split(":", 1)[-1] if raw_sub else None
        return (email or None), (sub or None)

    def _get_or_create_user(self, *, email: str, google_sub: str | None) -> User:
        try:
            user = User.objects.get(email=email)
            if google_sub and not user.google_sub:
                user.google_sub = google_sub
                user.save(update_fields=["google_sub"])
            return user
        except User.DoesNotExist:
            try:
                return User.objects.create_user(
                    email=email,
                    display_name=email.split("@")[0],
                    google_sub=google_sub,
                )
            except IntegrityError:
                # Concurrent request created the user first; fetch and return it.
                return User.objects.get(email=email)
