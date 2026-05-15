from django.urls import path

from . import views_auth

app_name = "slack_auth"

urlpatterns = [
    path("link/", views_auth.link_page, name="link"),
]
