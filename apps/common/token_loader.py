"""Loads any persisted OAuth token into os.environ at app boot.

Wired up via apps/common/apps.py CommonConfig.ready(). Idempotent — calling
load_at_boot() multiple times is safe.
"""
from __future__ import annotations

import logging

from . import auth_flow

logger = logging.getLogger(__name__)


def load_at_boot() -> None:
    token = auth_flow.load_stored_token()
    if token:
        logger.info("Loaded stored Claude OAuth token from %s", auth_flow.TOKEN_FILE)
    else:
        logger.info(
            "No stored Claude OAuth token at %s — visit /auth/cli to connect",
            auth_flow.TOKEN_FILE,
        )
