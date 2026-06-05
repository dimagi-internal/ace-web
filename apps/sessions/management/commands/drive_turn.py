"""Drive a single assistant turn to completion in a standalone process.

The seeded-run action (apps/opps/api.py) launches this as a detached process
so a programmatically-created run executes through the SAME turn-driver +
channel-layer broadcast path as a human typing into the workbench chat — and
decoupled from the web request's event loop (a fire-and-forget asyncio task
spawned inside a Django async request does not reliably run; see ace-web#585).
``claude -p`` then spawns cleanly as this process's own subprocess.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

from django.core.management.base import BaseCommand

logger = logging.getLogger("apps.sessions.drive_turn")


class Command(BaseCommand):
    help = "Drive a single assistant turn (programmatic/headless run launch)."

    def add_arguments(self, parser):
        parser.add_argument("assistant_message_id", type=int)

    def handle(self, *args, **options):
        from apps.sessions.consumers import drive_and_broadcast

        mid = options["assistant_message_id"]

        # DIAGNOSTIC (temporary): the headless driver dies `cancelled` ~55 min
        # in with no eviction/signal in the logs. Discriminate the cause —
        # an external signal vs an internal asyncio cancel — without changing
        # behavior. A SIGTERM/SIGHUP logger that re-raises the default keeps
        # the original outcome; the BaseException catch around asyncio.run
        # surfaces a KeyboardInterrupt (SIGINT → the only signal that yields a
        # graceful CancelledError under asyncio.run). See ace#<diagnostic>.
        def _log_and_default(signum, _frame):
            logger.warning(
                "drive_turn[msg=%s pid=%s] received signal %s (%s) — re-raising default",
                mid, os.getpid(), signum, signal.Signals(signum).name,
            )
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, _log_and_default)
            except (ValueError, OSError):
                pass

        logger.info("drive_turn[msg=%s pid=%s] starting", mid, os.getpid())
        try:
            asyncio.run(drive_and_broadcast(mid))
        except BaseException as exc:  # noqa: BLE001 — diagnostic: name the exit cause
            logger.warning(
                "drive_turn[msg=%s pid=%s] asyncio.run exited via %s: %s",
                mid, os.getpid(), type(exc).__name__, exc,
            )
            raise
        logger.info("drive_turn[msg=%s pid=%s] finished cleanly", mid, os.getpid())
