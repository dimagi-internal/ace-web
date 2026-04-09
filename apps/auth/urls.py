from django.conf import settings
from django.urls import path

from . import oauth_views

app_name = "auth"

urlpatterns = [
    path("login/", oauth_views.login_page, name="login"),
    path("initiate/", oauth_views.oauth_initiate, name="initiate"),
    path("callback/", oauth_views.oauth_callback, name="callback"),
    path("logout/", oauth_views.oauth_logout, name="logout"),
]

# Dev-only test-login endpoint. The URL is only registered when BOTH
# ACE_ALLOW_TEST_LOGIN and DEBUG are True. In production.py / connectlabs.py
# DEBUG is False, so this append never runs and the route does not exist.
# See apps/auth/test_login_views.py for the rationale.
if getattr(settings, "ACE_ALLOW_TEST_LOGIN", False) and settings.DEBUG:
    from . import test_login_views

    urlpatterns.append(
        path("test-login/", test_login_views.test_login, name="test_login")
    )
