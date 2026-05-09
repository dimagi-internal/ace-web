"""Local development settings."""
from .base import *  # noqa: F401, F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Phase 3 dev-only test hooks. Enable the Playwright E2E hooks.
# These are ALSO gated on DEBUG=True, which is True in this module.
ACE_ALLOW_TEST_LOGIN = True
# Default True so Playwright runs deterministically against the echo backend.
# Set ACE_USE_FAKE_CLI_BACKEND=false in your env / compose override to chat
# against real Claude using the uploaded CLI credentials.
ACE_USE_FAKE_CLI_BACKEND = env.bool("ACE_USE_FAKE_CLI_BACKEND", default=True)
