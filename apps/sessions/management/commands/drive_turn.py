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

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Drive a single assistant turn (programmatic/headless run launch)."

    def add_arguments(self, parser):
        parser.add_argument("assistant_message_id", type=int)

    def handle(self, *args, **options):
        from apps.sessions.consumers import drive_and_broadcast

        asyncio.run(drive_and_broadcast(options["assistant_message_id"]))
