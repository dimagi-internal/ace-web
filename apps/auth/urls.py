from django.conf import settings
from django.urls import path

from . import cli_authorize_views, nova_oauth_views, oauth_views

app_name = "auth"

urlpatterns = [
    path("login/", oauth_views.login_page, name="login"),
    path("initiate/", oauth_views.oauth_initiate, name="initiate"),
    path("callback/", oauth_views.oauth_callback, name="callback"),
    path("logout/", oauth_views.oauth_logout, name="logout"),
    path("me/", oauth_views.me, name="me"),
    path("nova/initiate/", nova_oauth_views.nova_oauth_initiate, name="nova_initiate"),
    path("nova/callback/", nova_oauth_views.nova_oauth_callback, name="nova_callback"),
    path("cli/authorize/", cli_authorize_views.cli_authorize, name="cli_authorize"),
]

# token_urlpatterns removed — personal-token CRUD now lives at
# /api/tokens/ via apps/service_accounts/api_v2.py.

# Dev-only test-login endpoint. The URL is only registered when BOTH
# ACE_ALLOW_TEST_LOGIN and DEBUG are True. In production.py / connectlabs.py
# DEBUG is False, so this append never runs and the route does not exist.
# See apps/auth/test_login_views.py for the rationale.
if getattr(settings, "ACE_ALLOW_TEST_LOGIN", False) and settings.DEBUG:
    from . import test_login_views

    urlpatterns.append(
        path("test-login/", test_login_views.test_login, name="test_login")
    )

# Token-gated e2e-login for automated tools (walkthroughs, CI).
# Only registered when ACE_E2E_AUTH_TOKEN is set (non-empty).
# See apps/auth/e2e_login_views.py for the security model.
if getattr(settings, "ACE_E2E_AUTH_TOKEN", ""):
    from . import e2e_login_views

    urlpatterns.append(
        path("e2e-login/", e2e_login_views.e2e_login, name="e2e_login")
    )
