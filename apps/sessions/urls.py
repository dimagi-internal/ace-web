from django.urls import path

from . import streaming, views

urlpatterns = [
    path("sessions", views.session_collection, name="session_collection"),
    path("sessions/<slug:slug>", views.session_detail, name="session_detail"),
    path("sessions/<slug:slug>/messages", views.send_message, name="send_message"),
    path("messages/<int:message_id>/stream", streaming.stream_assistant_message, name="message_stream"),
]
