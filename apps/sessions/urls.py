from django.urls import path

from . import views

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
]
