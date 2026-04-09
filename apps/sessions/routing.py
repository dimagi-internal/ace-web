"""WebSocket routing for sessions."""
from django.urls import path

from .consumers import SessionConsumer

websocket_urlpatterns = [
    path("ws/sessions/<slug:slug>/", SessionConsumer.as_asgi()),
]
