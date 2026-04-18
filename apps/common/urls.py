from django.urls import path

from . import auth_views, views

urlpatterns = [
    path("health", views.health_check, name="health"),
    path("auth/cli/status", auth_views.cli_auth_status, name="cli_auth_status"),
    path("auth/cli/upload", auth_views.cli_auth_upload, name="cli_auth_upload"),
    path(
        "auth/cli/expected-shape",
        auth_views.cli_auth_expected_shape,
        name="cli_auth_expected_shape",
    ),
]
