"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_collection, name="opps-collection"),
    path(
        "<slug:slug>/working-session",
        views.opp_working_session,
        name="opps-working-session",
    ),
    path("<slug:slug>", views.workbench, name="opps-workbench"),
    path("<slug:slug>/compare", views.opp_compare, name="opps-compare"),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>",
        views.step_detail,
        name="opps-step-detail",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/discuss",
        views.discuss,
        name="opps-discuss",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/chats",
        views.step_chats,
        name="opps-step-chats",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>/artifacts/<str:artifact_name>",
        views.artifact_body,
        name="opps-artifact-body",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/actions/<str:action>",
        views.opp_action, name="opps-action",
    ),
]
