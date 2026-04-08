"""WebSocket routing for sessions. Populated in Plan 1C."""
from django.urls import re_path

websocket_urlpatterns: list = [
    # re_path(r"ws/session/(?P<slug>[\w-]+)/$", SessionConsumer.as_asgi()),
]
