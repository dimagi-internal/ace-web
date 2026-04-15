from django.urls import path

from . import auth_views, views

urlpatterns = [
    path("health", views.health_check, name="health"),
    path("auth/cli/status", auth_views.cli_auth_status, name="cli_auth_status"),
    path("auth/cli/token", auth_views.cli_auth_set_token, name="cli_auth_set_token"),
]
