"""ASGI entry point with Channels routing."""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

# Defaults to production because uvicorn/daphne are the production entry
# points. Local dev overrides this via DJANGO_SETTINGS_MODULE in
# docker-compose or the shell.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django_asgi_app = get_asgi_application()

from apps.common.channels_auth import AceSessionAuthMiddleware  # noqa: E402
from apps.opps.routing import websocket_urlpatterns as opps_ws_urlpatterns  # noqa: E402
from apps.sessions.routing import websocket_urlpatterns as sessions_ws_urlpatterns  # noqa: E402

websocket_urlpatterns = sessions_ws_urlpatterns + opps_ws_urlpatterns

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    }
)
