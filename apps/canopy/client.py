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
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {bearer}"} if bearer else {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise CanopyError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except urllib.error.URLError as exc:
        raise CanopyError(502, str(exc.reason)) from exc


def _assertion(email: str) -> str:
    """A short-lived statement, signed by ace-web, that `email` is the person on
    ace-web right now — the canopy SDK's host contract (canopy-web
    docs/architecture/embedding-a-canopy-agent.md, step 3).

    canopy verifies it against ace-web's PUBLIC key (Connected sites) and answers
    with either their existing canopy account or a contact. It holds nothing
    that could sign one, and it never creates an account.
    """
    import datetime as dt
    import uuid

    import jwt

    if not settings.CANOPY_SIGNING_KEY or not settings.CANOPY_APP_NAME:
        raise CanopyError(503, "CANOPY_SIGNING_KEY and CANOPY_APP_NAME must be set")
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    email = (email or "").strip().lower()
    return jwt.encode(
        {
            "iss": settings.CANOPY_APP_NAME,        # this site's name in canopy
            "sub": email,                           # ace-web's own id for the person
            "aud": settings.CANOPY_ASSERTION_AUDIENCE or settings.CANOPY_BASE_URL.rstrip("/"),
            "iat": now,
            "exp": now + 60,                        # canopy caps assertions at 120s
            "jti": str(uuid.uuid4()),               # single use
            "email": email,
            # ace-web signs people in only through Google OAuth, which verified
            # this address. canopy resolves a verified email to an EXISTING account
            # only, at a domain ace-web's site is allowed to resolve.
            "email_verified": True,
        },
        settings.CANOPY_SIGNING_KEY,
        algorithm="EdDSA",
    )


def visitor_token(email: str) -> dict:
    """A canopy token for the person whose command ace-web is carrying out —
    `kind` "user" when they have a canopy account (arriving as themselves),
    "contact" otherwise. Both are first-class."""
    resp = _post("/api/auth/contact-token", {"assertion": _assertion(email)}, bearer="")
    resp.setdefault("kind", "contact")
    return resp


def create_contact_session(contact_token: str, *, title: str, metadata: dict) -> dict:
    """A contact's conversation. The same host link (`origin_key`, `opp_*`) a
    user's session carries — canopy applies one rule to both."""
    return _post(
        "/api/contact/sessions",
        {"agent_slug": settings.CANOPY_AGENT_SLUG, "title": title, "metadata": metadata},
        bearer=contact_token,
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


# --- acting as a person ---------------------------------------------------------------
# Everything ace-web does in canopy is done AS the person whose command it is
# executing: a chat they are typing into, a run they started, and the background
# work that finishes that run (restarting it after a deploy, checking progress,
# reading its transcript). canopy answers the signed assertion with that person's
# own account ("user") or, when they have none, their contact ("contact"). Both are
# first-class, so every call below routes to the surface that person reaches. There
# is no fallback identity: a run is never attributed to anyone but its owner.

class Principal:
    """One person, as canopy knows them, for the duration of a piece of work."""

    def __init__(self, *, token: str, kind: str):
        self.token, self.kind = token, kind

    @property
    def is_contact(self) -> bool:
        return self.kind == "contact"

    def create_session(self, *, title: str, metadata: dict) -> dict:
        if self.is_contact:
            return create_contact_session(self.token, title=title, metadata=metadata)
        return create_run_session(self.token, title=title, metadata=metadata)

    def send(self, session_id: str, *, text: str, client_id: str) -> dict:
        root = "/api/contact/sessions" if self.is_contact else "/api/canopy-sessions"
        return _post(f"{root}/{session_id}/send",
                     {"text": text, "client_id": client_id, "origin": RUN_ORIGIN},
                     bearer=self.token)

    def stop(self, session_id: str) -> dict:
        root = "/api/contact/sessions" if self.is_contact else "/api/canopy-sessions"
        return _post(f"{root}/{session_id}/stop", {}, bearer=self.token)

    def get_turn(self, turn_id: str) -> dict:
        root = "/api/contact/turns" if self.is_contact else "/api/harness/turns"
        return _get(f"{root}/{turn_id}", bearer=self.token)

    def list_unclaimable(self) -> list:
        path = "/api/contact/turns/unclaimable" if self.is_contact else "/api/harness/turns/unclaimable"
        return _get(path, bearer=self.token)

    def transcript_path(self, turn_id: str) -> str:
        root = "/api/contact/turns" if self.is_contact else "/api/harness/turns"
        return f"{root}/{turn_id}/transcript"


def act_as(email: str) -> Principal:
    """The person `email` is, in canopy — their account, or their contact."""
    vouched = visitor_token(email)
    return Principal(token=vouched["token"], kind=vouched["kind"])
