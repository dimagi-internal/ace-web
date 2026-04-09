"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="opps-health"),
]
