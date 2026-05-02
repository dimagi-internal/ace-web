"""Headers-helper for the bundled Nova MCP plugin.

Claude Code invokes this command at MCP-connect time (via the
``headersHelper`` field in the plugin's ``.mcp.json``) and merges the
JSON object on stdout into the request headers it sends to
``mcp.commcare.app``. We emit a fresh ``Authorization: Bearer <jwt>``
sourced from ``nova_auth_flow.get_fresh_token``, which transparently
refreshes the token if it's near expiry and persists the rotated blob
back to ``SystemConfig``.

Why a management command and not a small standalone script:
the script needs Django settings + DB access. ``manage.py nova_headers``
gets both for free; running it once per chat-turn (the cadence at
which ``claude -p`` opens a fresh MCP connection) makes the ~1s
startup cost a non-issue.

Output contract — exactly what Claude Code's loader expects:
  * exit 0
  * stdout: a single JSON object (no extra prose)
  * empty ``{}`` when Nova isn't connected, so the plugin loads but
    its MCP requests fail with the server's normal 401 instead of
    crashing the loader
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.common import nova_auth_flow


class Command(BaseCommand):
    help = "Emit JSON {Authorization: Bearer ...} for the Nova MCP plugin."

    def handle(self, *args, **options):
        try:
            token = nova_auth_flow.get_fresh_token()
        except Exception:
            # Never crash the MCP loader; Claude Code surfaces an empty
            # headers map as "no auth" and the server returns 401, which
            # is recoverable.
            token = None
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # ``ending=""`` keeps the output as exactly the JSON object —
        # Claude Code's headers parser does NOT tolerate a trailing newline.
        self.stdout.write(json.dumps(headers), ending="")
