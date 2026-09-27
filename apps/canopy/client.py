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


def _host_config():
    """The canopy SDK's view of ace-web as a host (``CANOPY_HOST``, derived from
    the flat ``CANOPY_*`` settings in ``config/canopy_host.py``)."""
    from canopy_sdk.contract import ContractError
    from canopy_sdk.django import conf
    from canopy_sdk.host import HostNotConfigured

    if not settings.CANOPY_SIGNING_KEY or not settings.CANOPY_APP_NAME:
        raise CanopyError(503, "CANOPY_SIGNING_KEY and CANOPY_APP_NAME must be set")
    try:
        config = conf.get_host_config()
    except HostNotConfigured as exc:
        raise CanopyError(503, str(exc)) from exc
    except ContractError as exc:  # a key that is not Ed25519/P-256 PEM
        raise CanopyError(503, f"CANOPY_SIGNING_KEY is unusable: {exc.code}") from exc
    if not config.assertions_enabled:
        raise CanopyError(503, "CANOPY_BASE_URL and CANOPY_APP_NAME must be set")
    return config


def _identity(email: str) -> tuple[str, dict]:
    """ace-web's own id for the person (their lower-cased email) and the claims
    it vouches for. ace-web signs people in only through OAuth that verified
    this address, and canopy resolves a verified email to an EXISTING account
    only, at a domain ace-web's site is allowed to resolve."""
    from .grant import subject_for

    subject = subject_for(email)
    return subject, {"email": subject, "email_verified": True}


def _assertion(email: str) -> str:
    """A short-lived statement, signed by ace-web, that `email` is the person on
    ace-web right now — the canopy SDK's visitor assertion (host grant contract
    §0): ``iss`` = our site name, ``sub`` = the person, ``aud`` = canopy, 60s,
    single-use ``jti``, ``kid`` = our key's RFC 7638 thumbprint.

    canopy verifies it against ace-web's PUBLIC key (Connected sites) and answers
    with either their existing canopy account or a contact. It holds nothing
    that could sign one, and it never creates an account.
    """
    from canopy_sdk.host import sign_visitor_assertion

    subject, claims = _identity(email)
    return sign_visitor_assertion(_host_config(), subject, **claims)


def arrival(email: str, *, scopes=()) -> dict:
    """The body ace-web POSTs to canopy's arrival endpoint.

    With ``scopes`` (a page's, from ``grant.scopes_for_page``) and the host grant
    on, it also carries an ID-JAG naming the same person for our MCP. Without
    either it is exactly the request it always was: an assertion plus
    ``agent_slug``, which names the canopy TENANT this token is for — a site's
    name is unique only within a canopy workspace (canopy-web #960), so without
    it canopy refuses (409 ambiguous_issuer) the day a second workspace
    registers an ``ace-web``. A failed ID-JAG never fails the arrival.
    """
    from canopy_sdk.host import arrival_payload

    subject, claims = _identity(email)
    return arrival_payload(_host_config(), subject, scopes=scopes,
                           agent_slug=settings.CANOPY_AGENT_SLUG, **claims)


def active_kid() -> str:
    """The ``kid`` our assertions and ID-JAGs carry: the RFC 7638 thumbprint of
    the live key's public half, derived from the key (never configured beside
    it, which would be a second thing to keep in step)."""
    return _host_config().kid


def published_jwks() -> list[dict]:
    """Every key canopy should currently accept from us: the one we sign with,
    plus any retired public halves still inside their rollover window
    (``CANOPY_RETIRED_PUBLIC_KEYS``).

    Without the retired half, switching signer refuses every assertion already
    in flight and every one canopy checks against a cache it has not refreshed.
    The same keys verify our ID-JAGs.
    """
    from .grant import host_config

    config = host_config()
    return config.jwks()["keys"] if config else []


def visitor_token(email: str, *, scopes=()) -> dict:
    """A canopy token for the person whose command ace-web is carrying out —
    `kind` "user" when they have a canopy account (arriving as themselves),
    "contact" otherwise. Both are first-class.

    Posted with ace-web's own client rather than the SDK's ``mint_contact_token``,
    which returns only ``token`` + ``expires_at``: ace-web routes every later
    call by ``kind``.
    """
    from canopy_sdk import contract

    resp = _post(contract.ARRIVAL_PATH, arrival(email, scopes=scopes), bearer="")
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
        root = "/api/contact/turns" if self.is_contact else "/api/harness/turns"
        path = f"{root}/unclaimable"
        return _get(path, bearer=self.token)

    def transcript_path(self, turn_id: str) -> str:
        root = "/api/contact/turns" if self.is_contact else "/api/harness/turns"
        return f"{root}/{turn_id}/transcript"


def act_as(email: str) -> Principal:
    """The person `email` is, in canopy — their account, or their contact."""
    vouched = visitor_token(email)
    return Principal(token=vouched["token"], kind=vouched["kind"])
