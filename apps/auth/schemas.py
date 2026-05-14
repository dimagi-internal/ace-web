"""Pydantic v2 schemas for the auth surface JSON endpoints.

Only the JSON-returning auth endpoints get schemas here.  Browser-redirect
endpoints (CommCare Connect OAuth initiate/callback, Nova OAuth
initiate/callback) stay as plain Django views and have no Pydantic schemas.

**Endpoints covered:**
- ``GET  /api/auth/cli/status``     → ``CliAuthStatusOut``
- ``POST /api/auth/cli/upload``     → ``CliAuthUploadOut``
- ``GET  /api/auth/nova/status``    → ``NovaAuthStatusOut``
- ``POST /auth/e2e-login/``         → ``E2ELoginIn`` / ``E2ELoginOut``
- ``GET  /api/auth/me``             → ``MeOut``  (v2 endpoint)
- ``POST /auth/test-login/``        → ``TestLoginIn``  (dev-only)

``WorkspaceRefOut`` is re-used from ``apps.common.schemas`` for the
workspace list embedded in ``MeOut``.
"""
from __future__ import annotations

from pydantic import ConfigDict

from apps.common.schemas import StrictModel, WorkspaceRefOut

# ── Current user (v2) ─────────────────────────────────────────────────────────


class MeOut(StrictModel):
    """GET /api/auth/me — minimal current-user info.

    ``workspaces`` lists every workspace the user is a member of,
    ordered by the workspace display name.  Useful for workspace
    selectors, nav headers, and determining default workspace slug.
    """

    id: int
    email: str
    display_name: str
    is_staff: bool = False
    workspaces: list[WorkspaceRefOut] = []


# ── CLI credential upload ─────────────────────────────────────────────────────


class CliAuthStatusOut(StrictModel):
    """GET /api/auth/cli/status — is the stored credential live?

    ``authenticated`` reflects whatever backend the chat path will pick
    (user blob first, then global).  ``user.has_blob`` / ``global.has_blob``
    indicate which scopes have a stored credential.
    """

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    authenticated: bool
    user: dict  # {has_blob: bool, token_prefix: str | None}
    global_: dict  # {has_blob: bool} — field rename: "global" is a keyword


class CliAuthUploadOut(StrictModel):
    """POST /api/auth/cli/upload — credential blob accepted response."""

    stored: bool
    authenticated: bool
    token_prefix: str
    scope: str  # "user" | "global"


class CliAuthPromoteOut(StrictModel):
    """POST /api/auth/cli/promote — promote user blob to global scope."""

    promoted: bool
    authenticated: bool
    token_prefix: str | None = None


class CliAuthExpectedShapeOut(StrictModel):
    """GET /api/auth/cli/expected-shape — schema introspection (public)."""

    shape: dict


# ── E2E login (automation) ────────────────────────────────────────────────────


class E2ELoginIn(StrictModel):
    """POST /auth/e2e-login/ body.

    Used by automated tools (walkthroughs, smoke tests, CI harnesses)
    to authenticate without going through CommCare Connect OAuth.
    ``token`` must match ``settings.ACE_E2E_AUTH_TOKEN``.
    """

    email: str
    token: str
    display_name: str = ""


class E2ELoginOut(StrictModel):
    """200 response from /auth/e2e-login/."""

    user_id: int
    email: str


# ── Nova OAuth status ─────────────────────────────────────────────────────────


class NovaAuthStatusOut(StrictModel):
    """GET /api/auth/nova/status — is the Nova MCP credential connected?

    ``can_manage`` is True for staff + automation accounts — they get
    the Connect/Disconnect controls in the UI.

    ``expires_at`` is an ISO-8601 string when present.  The blob may store
    either an ISO string or a unix-epoch integer; the view normalises to
    string before validation.
    """

    model_config = ConfigDict(
        extra="forbid",
        from_attributes=True,
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    connected: bool
    valid: bool
    expires_at: str | None = None  # ISO-8601 string (normalised from blob)
    scope: str | None = None
    can_manage: bool = False


# ── Dev-only test login ───────────────────────────────────────────────────────


class DevLoginIn(StrictModel):
    """POST /auth/test-login/ body.

    Available only when ``DEBUG=True``; never registered on production.
    Authenticates the named email directly, creating the user if needed.

    Named ``DevLoginIn`` (not ``TestLoginIn``) to avoid pytest's automatic
    collection of classes whose names start with ``Test``.
    """

    email: str
    display_name: str = ""
