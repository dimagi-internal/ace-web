from django.urls import path

from . import views, views_test_page

app_name = "slack"

urlpatterns = [
    path("commands", views.slash_commands, name="slash_commands"),
    path("interactions", views.interactions, name="interactions"),
    path("events", views.events, name="events"),
    path("install", views.install, name="install"),
    path("oauth/callback", views.oauth_callback, name="oauth_callback"),
    path("test/", views_test_page.test_index, name="test_index"),
    path("test/preview/<slug:slug>/", views_test_page.test_preview, name="test_preview"),
    path("test/post/<slug:slug>/", views_test_page.test_post, name="test_post"),
]
