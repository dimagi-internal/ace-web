"""Pydantic v2 schemas for the service_accounts surface.

**Personal tokens** (``PersonalToken`` in ``apps.auth.models``).
The management views live at ``apps/auth/token_views.py``; they are
grouped here (not in ``apps.auth.schemas``) because the plan treats
personal tokens as the user-facing credential API that parallels the
service account credential layer.

Field-name note:
   The DRF view uses ``"label"`` for the token name field.  The v2
   public API uses ``"name"`` (aligns with the plan's schema names).
   Phase 2 views must map ``token.label -> name`` when populating
   ``PersonalTokenOut``.

(The aspirational "share token" schemas that used to live here —
``ShareTokenCreateIn`` and a re-export of ``apps.sessions.schemas.
ShareTokenOut`` — were removed with the session-sharing feature they were
staged for; see the PR that retired apps/sessions' ShareToken model.)
"""
from __future__ import annotations

import datetime as dt

from apps.common.schemas import StrictModel

# ── Personal token schemas ───────────────────────────────────────────────────


class PersonalTokenOut(StrictModel):
    """Token metadata — returned in list and create responses.

    The raw token value is NEVER included here; it appears only in
    ``PersonalTokenCreatedOut`` (the POST 201 response), once.
    """

    id: int
    name: str               # maps to PersonalToken.label in the ORM
    created_at: dt.datetime
    last_used_at: dt.datetime | None = None


class PersonalTokenCreateIn(StrictModel):
    """POST /api/auth/tokens — create a new personal token."""

    name: str               # maps to PersonalToken.label in the ORM


class PersonalTokenCreatedOut(PersonalTokenOut):
    """201 response for a newly created token.

    ``raw_token`` is the plaintext bearer value — shown ONCE; the server
    stores only the SHA-256 hash and cannot recover the raw value after
    this response.
    """

    raw_token: str


__all__ = [
    "PersonalTokenCreateIn",
    "PersonalTokenCreatedOut",
    "PersonalTokenOut",
]
