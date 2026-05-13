from django.urls import path

from . import share_views, views

urlpatterns = [
    path("sessions", views.session_collection, name="session_collection"),
    path("sessions/<slug:slug>", views.session_detail, name="session_detail"),
    path(
        "sessions/<slug:slug>/messages",
        views.messages_list,
        name="messages_list",
    ),
    path(
        "sessions/<slug:slug>/participants",
        views.participant_collection,
        name="participant_collection",
    ),
    path(
        "sessions/<slug:slug>/turn-state",
        views.session_turn_state,
        name="session_turn_state",
    ),
    path(
        "sessions/<slug:slug>/cost-breakdown",
        views.session_cost_breakdown,
        name="session_cost_breakdown",
    ),
    path(
        "sessions/<slug:slug>/structure",
        views.session_structure,
        name="session_structure",
    ),
    path(
        "sessions/<slug:slug>/share",
        share_views.share_token_collection,
        name="share_token_collection",
    ),
    path(
        "sessions/<slug:slug>/share/<str:token>",
        share_views.share_token_revoke,
        name="share_token_revoke",
    ),
]
