from django.conf import settings
from django.urls import path

from . import (
    cli_authorize_views,
    google_views,
    invite_views,
    nova_oauth_views,
    oauth_views,
    password_views,
)

app_name = "auth"

urlpatterns = [
    path("login/", password_views.PasswordLoginView.as_view(), name="login"),
    # Google sign-in (OIDC code + PKCE); 404 until GOOGLE_OAUTH_CLIENT_ID/SECRET are set.
    path("google/initiate/", google_views.google_initiate, name="google_initiate"),
    path("google/callback/", google_views.google_callback, name="google_callback"),
    # Password lifecycle. Reset is behind ACE_PASSWORD_RESET_ENABLED.
    path("password/reset/", password_views.ResetRequestView.as_view(), name="password_reset"),
    path("password/reset/done/", password_views.ResetDoneView.as_view(),
         name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", password_views.ResetConfirmView.as_view(),
         name="password_reset_confirm"),
    path("password/reset/complete/", password_views.ResetCompleteView.as_view(),
         name="password_reset_complete"),
    path("password/", password_views.PasswordSetOrChangeView.as_view(), name="password_change"),
    path("account/", password_views.account, name="account"),
    # Public invite page: set a password, or use Google / CommCare.
    path("invite/<str:token>/", invite_views.invite_page, name="invite"),
    path("initiate/", oauth_views.oauth_initiate, name="initiate"),
    path("callback/", oauth_views.oauth_callback, name="callback"),
    path("logout/", oauth_views.oauth_logout, name="logout"),
    path("me/", oauth_views.me, name="me"),
    path("nova/initiate/", nova_oauth_views.nova_oauth_initiate, name="nova_initiate"),
    path("nova/callback/", nova_oauth_views.nova_oauth_callback, name="nova_callback"),
    path("cli/authorize/", cli_authorize_views.cli_authorize, name="cli_authorize"),
]

# token_urlpatterns removed — personal-token CRUD now lives at
# /api/tokens/ via apps/service_accounts/api.py.

# Dev-only test-login endpoint. The URL is only registered when BOTH
# ACE_ALLOW_TEST_LOGIN and DEBUG are True. In production.py / connectlabs.py
# DEBUG is False, so this append never runs and the route does not exist.
# See apps/auth/test_login_views.py for the rationale.
if getattr(settings, "ACE_ALLOW_TEST_LOGIN", False) and settings.DEBUG:
    from . import test_login_views

    urlpatterns.append(
        path("test-login/", test_login_views.test_login, name="test_login")
    )
