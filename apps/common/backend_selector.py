"""Single source of truth for chat backend selection.

Both ``turn_driver.drive_assistant_turn`` and
``auto_title.generate_title_for_session`` call ``get_chat_backend()`` to
pick between CLIBackend, ApiBackend, and FakeCLIBackend.

Selection is re-evaluated on every call — a CLI auth that completes after
process startup takes effect immediately (without this, the first pre-auth
call would pin ApiBackend for the life of the container). The underlying
backend *instances* are memoized so per-backend state (e.g. CLIBackend's
CircuitBreaker) survives across calls.

The "is the CLI usable?" check is the same function used by
``/api/auth/cli/status`` (``auth_flow.cli_is_ready``), so the banner and
the actual send path can never disagree.
"""
from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_cli_instance = None
_api_instance = None
_fake_instance = None


def _cli():
    global _cli_instance
    if _cli_instance is None:
        from .cli_backend import CLIBackend

        _cli_instance = CLIBackend()
    return _cli_instance


def _api():
    global _api_instance
    if _api_instance is None:
        from .api_backend import ApiBackend

        _api_instance = ApiBackend()
    return _api_instance


def _fake():
    global _fake_instance
    if _fake_instance is None:
        from .fake_cli_backend import FakeCLIBackend

        _fake_instance = FakeCLIBackend()
    return _fake_instance


def get_chat_backend(user=None):
    """Return the chat backend to use for the current call.

    ``user`` is the session owner whose credentials we should try first —
    same user passed to ``validate_stored_token`` by ``/api/auth/cli/status``
    so the status banner and the actual send path stay in sync. Pass
    ``user=None`` for legacy callers that don't have session context
    (startup checks, etc.); those only see the global fallback.

    Priority:
      1. ``FakeCLIBackend`` when ``ACE_USE_FAKE_CLI_BACKEND`` is True (E2E tests).
      2. ``CLIBackend`` when ``cli_is_ready(user=user)`` passes
         (this user's personal blob OR the global fallback validates).
      3. ``ApiBackend`` when ``ANTHROPIC_API_KEY`` is set.
      4. ``CLIBackend`` as a dead-end so the user sees a clear CLI error.
    """
    if getattr(settings, "ACE_USE_FAKE_CLI_BACKEND", False):
        return _fake()

    from .auth_flow import cli_is_ready

    if cli_is_ready(user=user):
        logger.debug(
            "chat backend = CLIBackend (cli_is_ready=True, user=%s)",
            getattr(user, "pk", None),
        )
        return _cli()

    api_key = getattr(settings, "ANTHROPIC_API_KEY", "") or ""
    if api_key:
        logger.info(
            "chat backend = ApiBackend (CLI not ready for user=%s, using API key)",
            getattr(user, "pk", None),
        )
        return _api()

    logger.warning(
        "chat backend = CLIBackend (no CLI token, no API key — chat will fail)"
    )
    return _cli()


def reset_instance_cache():
    """Clear memoized backend instances. Used by tests."""
    global _cli_instance, _api_instance, _fake_instance
    _cli_instance = None
    _api_instance = None
    _fake_instance = None
