"""Token-gated login for automated tools (walkthroughs, CI).

Unlike the dev-only test_login_views.py (gated by DEBUG=True), this
endpoint is gated by a pre-shared secret stored in ACE_E2E_AUTH_TOKEN.
It's intended for labs environments where automated tools need to
authenticate without going through CommCare Connect OAuth.

SECURITY:
- Disabled by default (ACE_E2E_AUTH_TOKEN defaults to empty string).
- The URL is only registered when ACE_E2E_AUTH_TOKEN is non-empty
  (see apps/auth/urls.py).
- The view re-checks the token at request time as a runtime backstop.
- Email is restricted to settings.ACE_ALLOWED_EMAIL_DOMAINS.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.contrib.auth import login
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from apps.auth.models import User

logger = logging.getLogger(__name__)


def _is_allowed_domain(email: str) -> bool:
    """Check if the email domain is in ACE_ALLOWED_EMAIL_DOMAINS.

    Empty list = allow any (workspace membership is the real gate).
    """
    domains = getattr(settings, "ACE_ALLOWED_EMAIL_DOMAINS", []) or []
    if not domains:
        return True
    _, _, domain = email.rpartition("@")
    return domain.lower() in domains


@csrf_exempt
@require_http_methods(["POST"])
def e2e_login(request: HttpRequest) -> HttpResponse:
    """Log in a user via pre-shared token. For automated tools.

    POST body (JSON): {"email": "ace@dimagi-ai.com", "token": "<secret>"}
    Response: 200 with {"user_id": int, "email": str}
    """
    expected_token = getattr(settings, "ACE_E2E_AUTH_TOKEN", "")
    if not expected_token:
        return JsonResponse({"error": "e2e login is disabled"}, status=404)

    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON"}, status=400)

    token = (body.get("token") or "").strip()
    if not token or token != expected_token:
        logger.warning("e2e_login: invalid token attempt")
        return JsonResponse({"error": "invalid token"}, status=403)

    email = (body.get("email") or "").strip().lower()
    display_name = (body.get("display_name") or "").strip() or email

    if not email:
        return JsonResponse({"error": "email is required"}, status=400)

    if not _is_allowed_domain(email):
        allowed = ", ".join(
            f"@{d}" for d in getattr(settings, "ACE_ALLOWED_EMAIL_DOMAINS", [])
        )
        return JsonResponse(
            {"error": f"email must be from: {allowed}"},
            status=400,
        )

    user, _created = User.objects.get_or_create(
        email=email,
        defaults={"display_name": display_name},
    )

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    logger.info("e2e_login: authenticated %s", email)

    try:
        from apps.workspaces.auto_join import ensure_auto_join_memberships

        ensure_auto_join_memberships(user)
    except Exception as exc:  # noqa: BLE001 — never block login on auto-join
        logger.warning("auto_join failed for %s: %s", email, exc)

    return JsonResponse({"user_id": user.pk, "email": user.email})
