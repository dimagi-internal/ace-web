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
import contextlib
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

from apps.api.mcp_server import build_http_app  # noqa: E402
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

# FastMCP Streamable-HTTP ASGI app — mounted at /api/mcp.
# ``build_http_app()`` returns ``mcp.http_app(path="/", transport="streamable-http")``:
# a Starlette app whose lifespan runs the Streamable-HTTP session manager.
# The MCP endpoint lives at the Mount root (``/api/mcp/``) because the internal
# path is ``/`` and Starlette's Mount strips the prefix before passing through.
#
# Tool calls execute IN-PROCESS through Django via httpx.ASGITransport (see
# apps/api/mcp_server.py) — there is no network self-loopback.
#
# Path-prefix subtlety: ace-web runs behind nginx with FORCE_SCRIPT_NAME=/ace
# on connect-labs. Django strips the /ace prefix internally via its
# script-name handling, but the Starlette ``Router`` here runs BEFORE Django
# — so the incoming path is ``/ace/api/mcp/...`` in prod and ``/api/mcp/...``
# locally. Read the prefix from the env (same source as Django settings)
# and prepend it to the Mount path so both environments resolve correctly.
_SCRIPT_NAME = os.environ.get("FORCE_SCRIPT_NAME", "").rstrip("/")
_mcp_app = build_http_app()


@contextlib.asynccontextmanager
async def _composed_lifespan(app):
    """Compose the MCP server lifespan with the Slack worker.

    1. MCP lifespan — runs the Streamable-HTTP session manager; required for
       Streamable-HTTP session management. Yields when the MCP server is ready.
    2. Slack worker — runs in the background until app shutdown.

    Set DJANGO_SLACK_DISABLE_WORKER=1 to suppress the worker (e.g. in ASGI
    smoke tests or management commands that mount the app without Redis).
    """
    import asyncio

    from apps.slack.dispatcher import run_worker_forever

    slack_task: asyncio.Task | None = None
    if os.environ.get("DJANGO_SLACK_DISABLE_WORKER") != "1":
        slack_task = asyncio.create_task(run_worker_forever())

    async with _mcp_app.lifespan(app):
        try:
            yield
        finally:
            if slack_task is not None:
                slack_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await slack_task


application = Router(
    routes=[
        Mount(f"{_SCRIPT_NAME}/api/mcp", app=_mcp_app),
        # Catch-all: everything else → Channels / Django
        Mount("/", app=_channels_app),
    ],
    lifespan=_composed_lifespan,
)
