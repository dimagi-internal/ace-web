"""ASGI entry point with Channels routing.

HTTP traffic is split at the top level:
- ``/api/mcp`` → FastMCP server (Starlette ASGI app, exposes opted-in v2
  endpoints as MCP tools for AI-agent consumption)
- everything else → Django (via Channels ProtocolTypeRouter, which also
  handles WebSocket upgrades)

The split is done with a Starlette ``Mount`` + ``Router`` wrapping the
Channels application.  Django URL conf is NOT used for the MCP mount because
``mcp.http_app()`` returns a Starlette ASGI application, not a Django view.
"""
import os

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application
from starlette.routing import Mount, Router

# Defaults to production because uvicorn/daphne are the production entry
# points. Local dev overrides this via DJANGO_SETTINGS_MODULE in
# docker-compose or the shell.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")

django_asgi_app = get_asgi_application()

from apps.api_v2.mcp_server import make_asgi_app  # noqa: E402
from apps.common.channels_auth import AceSessionAuthMiddleware  # noqa: E402
from apps.opps.routing import websocket_urlpatterns as opps_ws_urlpatterns  # noqa: E402
from apps.sessions.routing import websocket_urlpatterns as sessions_ws_urlpatterns  # noqa: E402

websocket_urlpatterns = sessions_ws_urlpatterns + opps_ws_urlpatterns

_channels_app = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AceSessionAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    }
)

# FastMCP ASGI app — mounted at /api/mcp.
# ``make_asgi_app()`` calls ``FastMCP.from_openapi`` once at startup and
# returns a Starlette app; the internal path is ``/mcp`` because Starlette's
# Mount strips the ``/api/mcp`` prefix before passing the request through.
_mcp_app = make_asgi_app()

application = Router(
    routes=[
        Mount("/api/mcp", app=_mcp_app),
        # Catch-all: everything else → Channels / Django
        Mount("/", app=_channels_app),
    ],
    lifespan=_mcp_app.lifespan,
)
