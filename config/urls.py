from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.common.urls")),
    # SPA catch-all: any non-api/non-admin/non-static path serves the React index.html.
    # React Router handles client-side routing from there.
    re_path(
        r"^(?!api/|admin/|static/).*$",
        TemplateView.as_view(template_name="index.html"),
        name="spa",
    ),
]
