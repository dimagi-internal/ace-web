from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from apps.auth.urls import token_urlpatterns
from apps.sessions.share_views import public_share_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    path("api/", include("apps.sessions.urls")),
    path("api/ingest/", include("apps.ingest.urls")),
    path("api/opps/", include("apps.opps.urls")),
    path("api/auth/", include((token_urlpatterns, "auth_tokens"))),
    path("api/share/<str:token>", public_share_view, name="public_share"),
    # React pages under /auth/ that must be served by the SPA, not by
    # Django's auth views. These are listed explicitly because the SPA
    # catch-all excludes the auth/ prefix entirely.
    path(
        "auth/cli",
        login_required(TemplateView.as_view(template_name="index.html")),
        name="spa_auth_cli",
    ),
    path("auth/", include("apps.auth.urls")),
    # SPA catch-all: any non-api/non-admin/non-auth/non-static/non-assets path serves
    # the React index.html. React Router handles client-side routing from there.
    # login_required ensures unauthenticated users are redirected to /auth/login/.
    # `/assets/` is excluded explicitly so that a misconfigured Vite base path does
    # not get masked by the catch-all serving HTML in place of a missing .js or .css
    # file — browsers fail silently on that MIME mismatch and it produces a blank page.
    re_path(
        r"^(?!api/|admin/|auth/|static/|assets/).*$",
        login_required(TemplateView.as_view(template_name="index.html")),
        name="spa",
    ),
]
