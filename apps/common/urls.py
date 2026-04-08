from django.urls import path

from . import auth_views, views

urlpatterns = [
    path("health", views.health_check, name="health"),
    path("auth/cli/status", auth_views.cli_auth_status, name="cli_auth_status"),
    path("auth/cli/start", auth_views.cli_auth_start, name="cli_auth_start"),
    path("auth/cli/complete", auth_views.cli_auth_complete, name="cli_auth_complete"),
    path("auth/cli/poll", auth_views.cli_auth_poll, name="cli_auth_poll"),
    path("auth/cli/cancel", auth_views.cli_auth_cancel, name="cli_auth_cancel"),
]
