"""URL routes for the ACE opportunity Workbench."""
from django.urls import path

from . import views

# Opp "slug" is whatever the Drive folder is named — the `ace` CLI plugin
# creates folders with the user's literal display string, which can include
# spaces and uppercase (e.g. "Malaria RDT QA"). Use Django's `<str:>`
# converter (matches anything except `/`) rather than the strict `<slug:>`
# converter (`[-a-zA-Z0-9_]+`) so requests like
# `/api/opps/Malaria%20RDT%20QA/runs` route through instead of falling
# through to the SPA catch-all as a 404. The frontend always passes the
# slug through `encodeURIComponent`, and downstream code treats slug as a
# literal folder name (`_find_child_folder` does string-equality), so no
# slug-shape assumption exists past the URL layer.
urlpatterns = [
    path("health", views.health, name="opps-health"),
    path("", views.opp_collection, name="opps-collection"),
    path(
        "compare/<str:slug_a>/<str:slug_b>",
        views.opp_compare,
        name="opps-compare",
    ),
    path(
        "<str:slug>/working-session",
        views.opp_working_session,
        name="opps-working-session",
    ),
    path("<str:slug>/runs", views.runs_list, name="opps-runs-list"),
    path(
        "<str:slug>/multi-run-summary",
        views.multi_run_summary, name="opps-multi-run-summary",
    ),
    path("<str:slug>/cost-rollup", views.cost_rollup, name="opps-cost-rollup"),
    path("<str:slug>", views.workbench, name="opps-workbench"),
    path("<str:slug>/scorecard", views.scorecard, name="opps-scorecard"),
    path("<str:slug>/fork", views.opp_fork, name="opps-fork"),
    path(
        "<str:slug>/fork/status",
        views.opp_fork_status,
        name="opps-fork-status",
    ),
    path(
        "<str:slug>/runs/<str:run_id>",
        views.delete_run,
        name="opps-delete-run",
    ),
    path(
        "<str:slug>/runs/<str:run_id>/steps/<str:skill>",
        views.step_detail,
        name="opps-step-detail",
    ),
    path(
        "<str:slug>/runs/<str:run_id>/steps/<str:skill>/discuss",
        views.discuss,
        name="opps-discuss",
    ),
    path(
        "<str:slug>/runs/<str:run_id>/steps/<str:skill>/chats",
        views.step_chats,
        name="opps-step-chats",
    ),
    path(
        "<str:slug>/runs/<str:run_id>/steps/<str:skill>/artifacts/<str:artifact_name>",
        views.artifact_body,
        name="opps-artifact-body",
    ),
    path(
        "<str:slug>/runs/<str:run_id>/steps/<str:skill>"
        "/artifacts/<str:artifact_name>/write",
        views.opp_artifact_write,
        name="opps-artifact-write",
    ),
    path(
        "<str:slug>/runs/<str:run_id>/actions/<str:action>",
        views.opp_action, name="opps-action",
    ),
    # Public, unauthenticated per-run summary. Workspace slug stays strict
    # — workspaces are created via the onboarding wizard with slugify(),
    # so they're guaranteed slug-shaped.
    path(
        "public/<slug:workspace>/<str:slug>/runs/<str:run_id>/summary",
        views.public_opp_summary, name="opps-public-summary",
    ),
]
