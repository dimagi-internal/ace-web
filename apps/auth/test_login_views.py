"""Dev-only test-login view for Playwright E2E tests.

Gated by `settings.ACE_ALLOW_TEST_LOGIN and settings.DEBUG`. The URL
that maps to this view is only registered when both flags are True
(see apps/auth/urls.py), so in production there is literally no route
to hit.

This view creates or fetches a User by email and logs them in via
django.contrib.auth.login, setting the standard Django session cookie.
Playwright tests drive this endpoint at the start of each test to get
an authenticated session without going through CommCare Connect OAuth.

SECURITY:
- Defaults in base.py are False.
- Only development.py sets them True.
- The URL registration in apps/auth/urls.py ALSO requires DEBUG=True.
- production.py and connectlabs.py set DEBUG=False, so even if
  ACE_ALLOW_TEST_LOGIN were accidentally True (it isn't) the URL would
  not register.
- The view re-checks both flags at request time as a runtime backstop.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.auth.models import User

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["POST"])
def test_login(request: HttpRequest) -> HttpResponse:
    """Log in a test user without OAuth. Dev-only.

    POST body (JSON): {"email": "alice@dimagi.com", "display_name": "Alice"}
    Response: 200 with {"user_id": int, "email": str}
    """
    # Runtime backstop - even if the URL somehow gets registered in a
    # non-dev environment, refuse to proceed.
    if not (settings.ACE_ALLOW_TEST_LOGIN and settings.DEBUG):
        logger.warning(
            "test_login called with ACE_ALLOW_TEST_LOGIN=%s DEBUG=%s - refusing",
            settings.ACE_ALLOW_TEST_LOGIN,
            settings.DEBUG,
        )
        return JsonResponse(
            {"error": "test login is disabled"}, status=404
        )

    import json

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    email = (body.get("email") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip() or email

    if not email:
        return JsonResponse({"error": "email is required"}, status=400)

    # Enforce allowed email domains — same domains as the real OAuth flow.
    allowed_domains = getattr(settings, "ACE_ALLOWED_EMAIL_DOMAINS", ["dimagi.com"])
    _, _, email_domain = email.rpartition("@")
    if email_domain not in allowed_domains:
        allowed_str = ", ".join(f"@{d}" for d in allowed_domains)
        return JsonResponse(
            {"error": f"email must be from: {allowed_str}"},
            status=400,
        )

    user, _created = User.objects.get_or_create(
        email=email,
        defaults={"display_name": display_name},
    )

    # Set the Django session cookie. login() writes to request.session
    # and django.contrib.sessions' middleware will emit the Set-Cookie
    # header on the response.
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    return JsonResponse({"user_id": user.pk, "email": user.email})
