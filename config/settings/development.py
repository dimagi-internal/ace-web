"""Local development settings."""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["*"]

# Phase 3 dev-only test hooks. Enable the Playwright E2E hooks.
# These are ALSO gated on DEBUG=True, which is True in this module.
ACE_ALLOW_TEST_LOGIN = True
ACE_USE_FAKE_CLI_BACKEND = True
