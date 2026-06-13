"""Dev-only test-login view for Playwright E2E tests.

Gated by `settings.ACE_ALLOW_TEST_LOGIN and settings.DEBUG`. The URL
that maps to this view is only registered when both flags are True
(see apps/auth/urls.py), so in production there is literally no route
to hit.

This view creates or fetches a User by email and logs them in via
django.contrib.auth.login, setting the standard Django session cookie.
Playwright tests drive this endpoint at the start of each test to get
an authenticated session without going through Connect OAuth.

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

    # Enforce allowed email domains — same semantics as the real OAuth flow.
    # Empty list = allow any email (workspace membership is the real gate).
    allowed_domains = getattr(settings, "ACE_ALLOWED_EMAIL_DOMAINS", []) or []
    if allowed_domains:
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

    # Dev-only auto-onboarding: get every test-login user into a workable
    # state so they don't have to walk the /welcome wizard every time the
    # local DB gets blown away. Only runs in DEBUG+ACE_ALLOW_TEST_LOGIN
    # (already gated above). Failures are non-fatal — the wizard remains
    # available as the fallback.
    try:
        _ensure_dev_workspace_membership(user)
    except Exception:  # noqa: BLE001
        logger.warning("dev workspace bootstrap failed", exc_info=True)

    # Set the Django session cookie. login() writes to request.session
    # and django.contrib.sessions' middleware will emit the Set-Cookie
    # header on the response.
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    return JsonResponse({"user_id": user.pk, "email": user.email})


def _ensure_dev_workspace_membership(user) -> None:
    """Idempotently put the user in a workspace for local-dev iteration.

    Runs after every test-login. Three cases:

    1. **A workspace already exists** (someone else logged in earlier and
       set one up, or the seed migration created one) → add this user as
       Editor to every existing workspace. Lets multiple test users
       share the same dev state.
    2. **No workspace yet AND ``ACE_DRIVE_ROOT_FOLDER_ID`` is set** →
       create a "Dimagi Team" workspace tied to that folder, with this
       user as Owner. Mirrors the prod seed.
    3. **No workspace yet AND no Drive folder configured** → no-op. The
       user goes through the /welcome wizard normally.

    The whole helper is dev-only; production never reaches it because
    test_login is gated on DEBUG and the URL isn't registered.
    """
    # Lazy imports — these apps load after settings have populated.
    from apps.workspaces.models import Workspace, WorkspaceMembership

    existing = list(Workspace.objects.all())
    if existing:
        for ws in existing:
            WorkspaceMembership.objects.get_or_create(
                workspace=ws,
                user=user,
                defaults={"role": "editor"},
            )
        return

    folder_id = getattr(settings, "ACE_DRIVE_ROOT_FOLDER_ID", "") or ""
    if not folder_id:
        # Nothing to anchor a workspace on. The /welcome wizard prompts
        # for a folder ID + verifies SA access, which is the right path
        # for someone genuinely setting up new infra.
        return

    ws = Workspace.objects.create(
        slug="dimagi-team",
        display_name="Dimagi Team",
        drive_root_folder_id=folder_id,
        created_by=user,
    )
    WorkspaceMembership.objects.create(
        workspace=ws, user=user, role="owner",
    )
    logger.info(
        "dev bootstrap: created workspace %s anchored to Drive folder %s",
        ws.slug, folder_id,
    )
