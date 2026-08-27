"""Outbound calls to canopy-web.

The chat cutover needed two: token exchange (the app credential's single
power) and session create (so opp-linkage rules live server-side); everything
else on that path is browser → canopy directly.

Run execution (spec 2026-07-26) adds the server-side half of driving an ACE
run on canopy's harness — create the run's session, send the turn, read the
turn back, ask which queued turns nobody can claim, and stop a session's
in-flight turns. Those are server-to-server by nature: no browser is present
while a programmatic run executes.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from django.conf import settings


class CanopyError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(f"canopy {status}: {detail}")


def _post(path: str, payload: dict, *, bearer: str) -> dict:
    req = urllib.request.Request(
        f"{settings.CANOPY_BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise CanopyError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except urllib.error.URLError as exc:
        raise CanopyError(502, str(exc.reason)) from exc


def exchange_token(email: str, *, ttl: int = 3600) -> dict:
    return _post(
        "/api/auth/token-exchange",
        {"acting_as_email": email, "ttl_seconds": ttl},
        bearer=settings.CANOPY_APP_CREDENTIAL,
    )


def create_session(user_token: str, *, title: str, metadata: dict) -> dict:
    return _post(
        f"/api/w/{settings.CANOPY_WORKSPACE}/canopy-sessions/",
        {"agent_slug": settings.CANOPY_AGENT_SLUG, "title": title, "metadata": metadata},
        bearer=user_token,
    )


def _get(path: str, *, bearer: str):
    req = urllib.request.Request(
        f"{settings.CANOPY_BASE_URL}{path}",
        headers={"Authorization": f"Bearer {bearer}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise CanopyError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except urllib.error.URLError as exc:
        raise CanopyError(502, str(exc.reason)) from exc


def create_run_session(user_token: str, *, title: str, metadata: dict) -> dict:
    """Create the canopy Session an opp-run executes in.

    Separate from `create_session` (the browser chat path) on purpose: a run's
    metadata is stamped by the server-side dispatcher, and keeping the two
    callers apart stops one's metadata rules leaking into the other.
    """
    return _post(
        f"/api/w/{settings.CANOPY_WORKSPACE}/canopy-sessions/",
        {"agent_slug": settings.CANOPY_AGENT_SLUG, "title": title, "metadata": metadata},
        bearer=user_token,
    )


# The source ace-web's delegated runs enqueue as, in canopy's `Turn.origin`
# vocabulary (canopy-web spec 2026-07-27, source-aware runner routing). ace-web
# is THE producer of this value — canopy's session send defaults to
# `canopy_web_chat`, so without it a run is indistinguishable from a human
# typing in canopy's chat UI and a routing rule on `ace_web` never fires.
RUN_ORIGIN = "ace_web"


def send_message(user_token: str, session_id: str, *, text: str, client_id: str) -> dict:
    """Enqueue a session-targeted Turn. `client_id` makes a retried send collapse
    onto the SAME user Message + Turn (canopy send_message's idempotency nonce),
    which is what makes dispatch safe to retry.

    `origin` is unconditional rather than a parameter: every caller of this
    module is the server-side run dispatcher (the browser's chat talks to canopy
    directly, never through here), so there is no second kind of send that could
    legitimately want a different source.
    """
    return _post(
        f"/api/canopy-sessions/{session_id}/send",
        {"text": text, "client_id": client_id, "origin": RUN_ORIGIN},
        bearer=user_token,
    )


def get_turn(user_token: str, turn_id: str) -> dict:
    return _get(f"/api/harness/turns/{turn_id}", bearer=user_token)


def list_unclaimable(user_token: str) -> list:
    """Queued turns canopy says no runner can claim, after a 150s grace.
    `kind` is "config" (nothing declares this target) or "offline" (something
    does, none reachable). See run_state.py for why `kind` is advisory."""
    return _get("/api/harness/turns/unclaimable", bearer=user_token)


def stop_session(user_token: str, session_id: str) -> dict:
    """Cancel every non-terminal turn on a session. Used by resume: an ace-web
    resume declares the previous turn dead, and canopy must be told, or the
    stale turn keeps holding one_executing_turn_per_session."""
    return _post(f"/api/canopy-sessions/{session_id}/stop", {}, bearer=user_token)
