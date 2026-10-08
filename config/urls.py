from canopy_sdk.django.views import probe_endpoint as canopy_grant_probe_endpoint
from canopy_sdk.django.views import token_endpoint as canopy_grant_token_endpoint
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import include, path, re_path
from django.views.generic import TemplateView

from apps.api.api import api
from apps.api.views import redoc_docs, scalar_docs
from apps.auth.invite_views import invite_entry
from apps.canopy import grant as canopy_grant


def admin_login_redirect(request):
    from django.http import HttpResponseForbidden
    from django.shortcuts import redirect
    from django.urls import reverse

    if request.user.is_authenticated:
        # Signed in but not staff: bouncing to the login page would loop back here.
        return HttpResponseForbidden("The admin is for staff accounts.")
    return redirect(f"{reverse('auth:login')}?next={reverse('admin:index')}")

urlpatterns = [
    # The admin's own login form would be a fourth door that skips the
    # admission gate; send it through the one login page instead.
    path("admin/login/", admin_login_redirect, name="admin_login_redirect"),
    path("admin/", admin.site.urls),
    # The canopy host grant's token endpoint (RFC 7523 jwt-bearer +
    # private_key_jwt + DPoP), straight from the canopy SDK. Refuses every
    # grant while CANOPY_CLIENT_ID is unset. Bare Django view, ahead of Ninja.
    path("api/canopy/oauth/token", canopy_grant_token_endpoint, name="canopy_grant_token"),
    # canopy's live probe (apps/canopy/probe.py): a real ID-JAG for the one
    # dedicated probe principal, for canopy's client only (private_key_jwt +
    # DPoP, checked by the SDK; csrf_exempt, no login). 404 unless
    # CANOPY_PROBE_ENABLED, the grant is on, and the principal exists. Its
    # public URL is CANOPY_HOST["PROBE"]["ENDPOINT"] — keep the two in step.
    path("api/canopy/oauth/probe", canopy_grant_probe_endpoint, name="canopy_grant_probe"),
    path("api/", api.urls),
    path("api/slack/", include("apps.slack.urls")),
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
    path("auth/slack/", include("apps.slack.auth_urls")),
    # Invite links: anonymous visitors choose how to sign in (password, Google,
    # CommCare) on the server-rendered invite page; signed-in ones get the SPA.
    re_path(r"^invite/(?P<token>[^/]+)/?$", invite_entry, name="spa_invite"),
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
    # RFC 8414 / RFC 9728 discovery for the canopy host grant. These live at
    # the SITE ROOT (the well-known segment goes before the issuer's `/ace`
    # path), outside FORCE_SCRIPT_NAME — Django sees the path unchanged. 404
    # while the grant is off. Must precede the SPA catch-all.
    re_path(r"^\.well-known/oauth-authorization-server(?P<rest>/.*)?$",
            canopy_grant.authorization_server_metadata, name="canopy_grant_as_metadata"),
    re_path(r"^\.well-known/oauth-protected-resource(?P<rest>/.*)?$",
            canopy_grant.protected_resource_metadata, name="canopy_grant_pr_metadata"),
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
