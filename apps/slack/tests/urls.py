"""Minimal URL conf for slack view tests — avoids loading the full Ninja API."""
from django.urls import include, path

urlpatterns = [
    path("api/slack/", include("apps.slack.urls")),
]
