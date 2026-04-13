"""URL routes for the ACE System Overview."""
from django.urls import path

from . import views

urlpatterns = [
    path("overview", views.overview, name="system-overview"),
    path("skills/<str:name>", views.skill_detail, name="system-skill-detail"),
    path("agents/<str:name>", views.agent_detail, name="system-agent-detail"),
    path("version", views.version, name="system-version"),
]
