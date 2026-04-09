"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import drive_auth_views, views

urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_list, name="opps-list"),
    path("<slug:slug>", views.workbench, name="opps-workbench"),
    path("<slug:slug>/compare", views.opp_compare, name="opps-compare"),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>",
        views.step_detail,
        name="opps-step-detail",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/artifacts/<str:artifact_name>",
        views.artifact_body,
        name="opps-artifact-body",
    ),
]

auth_urlpatterns = [
    path("auth/drive/start", drive_auth_views.start, name="drive-auth-start"),
    path("auth/drive/callback", drive_auth_views.callback, name="drive-auth-callback"),
]
