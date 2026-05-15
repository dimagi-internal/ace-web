from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from apps.api.api import api
from apps.api.views import redoc_docs, scalar_docs

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", api.urls),
    path("api/docs/", scalar_docs, name="api_docs_scalar"),
    path("api/redoc/", redoc_docs, name="api_docs_redoc"),
    # React pages under /auth/ that must be served by the SPA, not by
    # Django's auth views. These are listed explicitly because the SPA
    # catch-all excludes the auth/ prefix entirely.
    path(
        "auth/cli",
        login_required(TemplateView.as_view(template_name="index.html")),
        name="spa_auth_cli",
    ),
    path("auth/", include("apps.auth.urls")),
    # Public per-run opp summary page. SPA shell served WITHOUT
    # login_required so anonymous viewers can hit the page directly
    # (the React app then fetches /api/opps/public/... which is also
    # AllowAny). Must be registered before the SPA catch-all so this
    # specific pattern wins.
    re_path(
        r"^opps/(?P<workspace>[^/]+)/(?P<slug>[^/]+)/runs/(?P<run_id>[^/]+)/summary/?$",
        TemplateView.as_view(template_name="index.html"),
        name="public_opp_summary",
    ),
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
