"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import drive_auth_views, views

urlpatterns = [
    path("health", views.health, name="opps-health"),
]

auth_urlpatterns = [
    path("auth/drive/start", drive_auth_views.start, name="drive-auth-start"),
    path("auth/drive/callback", drive_auth_views.callback, name="drive-auth-callback"),
]
