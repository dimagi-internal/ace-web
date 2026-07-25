"""Local development settings."""
from .base import *  # noqa: F401, F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Allow POSTs from the Vite dev server (port 5173) and the bundled-Django
# port 8001 in development. Without this, Django's CsrfViewMiddleware
# rejects requests with `Origin checking failed` because the Vite proxy
# preserves the browser's Origin header (localhost:5173).
CSRF_TRUSTED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8001",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8001",
]

# Phase 3 dev-only test hooks. Enable the Playwright E2E hooks.
# These are ALSO gated on DEBUG=True, which is True in this module.
ACE_ALLOW_TEST_LOGIN = True
# Default True so Playwright runs deterministically against the echo backend.
# Set ACE_USE_FAKE_CLI_BACKEND=false in your env / compose override to chat
# against real Claude using the uploaded CLI credentials.
ACE_USE_FAKE_CLI_BACKEND = env.bool("ACE_USE_FAKE_CLI_BACKEND", default=True)

# canopy-web hosted chat: point at a local canopy-web dev server by default.
# Still OFF (status.enabled False) until CANOPY_APP_CREDENTIAL is also set.
CANOPY_BASE_URL = env("CANOPY_BASE_URL", default="http://127.0.0.1:8000")
