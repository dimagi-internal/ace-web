"""WebSocket routing for the opp workbench."""
from django.urls import re_path

from .consumers import OppConsumer

websocket_urlpatterns = [
    re_path(
        r"^ws/opps/(?P<slug>[^/]+)/runs/(?P<run_id>[^/]+)/$",
        OppConsumer.as_asgi(),
    ),
    re_path(
        r"^ws/opps/(?P<slug>[^/]+)/$",
        OppConsumer.as_asgi(),
    ),
]
