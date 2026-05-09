"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_collection, name="opps-collection"),
    path(
        "compare/<slug:slug_a>/<slug:slug_b>",
        views.opp_compare,
        name="opps-compare",
    ),
    path(
        "<slug:slug>/working-session",
        views.opp_working_session,
        name="opps-working-session",
    ),
    path("<slug:slug>/runs", views.runs_list, name="opps-runs-list"),
    path(
        "<slug:slug>/multi-run-summary",
        views.multi_run_summary, name="opps-multi-run-summary",
    ),
    path("<slug:slug>/cost-rollup", views.cost_rollup, name="opps-cost-rollup"),
    path("<slug:slug>", views.workbench, name="opps-workbench"),
    path("<slug:slug>/scorecard", views.scorecard, name="opps-scorecard"),
    path("<slug:slug>/fork", views.opp_fork, name="opps-fork"),
    path(
        "<slug:slug>/runs/<str:run_id>",
        views.delete_run,
        name="opps-delete-run",
    ),
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
        "<slug:slug>/runs/<str:run_id>/steps/<str:skill>"
        "/artifacts/<str:artifact_name>/write",
        views.opp_artifact_write,
        name="opps-artifact-write",
    ),
    path(
        "<slug:slug>/runs/<str:run_id>/actions/<str:action>",
        views.opp_action, name="opps-action",
    ),
    # Public, unauthenticated per-run summary. Workspace slug is in the
    # path because there's no auth context to resolve it from.
    path(
        "public/<slug:workspace>/<slug:slug>/runs/<str:run_id>/summary",
        views.public_opp_summary, name="opps-public-summary",
    ),
]
