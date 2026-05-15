from django.urls import path

from . import views

app_name = "slack"

urlpatterns = [
    path("commands", views.slash_commands, name="slash_commands"),
    path("interactions", views.interactions, name="interactions"),
    path("events", views.events, name="events"),
    path("install", views.install, name="install"),
    path("oauth/callback", views.oauth_callback, name="oauth_callback"),
]
