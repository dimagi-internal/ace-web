from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    # SPA catch-all: any non-api/non-admin/non-static/non-assets path serves
    # the React index.html. React Router handles client-side routing from
    # there. `/assets/` is excluded explicitly so that a misconfigured Vite
    # base path does not get masked by the catch-all serving HTML in place
    # of a missing .js or .css file — browsers fail silently on that MIME
    # mismatch and it produces a blank page.
    re_path(
        r"^(?!api/|admin/|static/|assets/).*$",
        TemplateView.as_view(template_name="index.html"),
        name="spa",
    ),
]
