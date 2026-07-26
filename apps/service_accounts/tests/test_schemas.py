"""Round-trip tests for apps.service_accounts.schemas."""
from __future__ import annotations

import datetime as dt

from apps.service_accounts.schemas import (
    PersonalTokenCreatedOut,
    PersonalTokenCreateIn,
    PersonalTokenOut,
)

_NOW = dt.datetime(2026, 5, 14, 10, 0, 0, tzinfo=dt.UTC)


def test_personal_token_out_round_trip():
    token = PersonalTokenOut(id=1, name="my-token", created_at=_NOW)
    d = token.model_dump()
    assert d["id"] == 1
    assert d["name"] == "my-token"
    assert d["last_used_at"] is None


def test_personal_token_created_out_includes_raw():
    token = PersonalTokenCreatedOut(
        id=2,
        name="cli-token",
        created_at=_NOW,
        raw_token="super-secret-raw-value",
    )
    assert token.raw_token == "super-secret-raw-value"
    # Inherits PersonalTokenOut fields
    assert token.id == 2


def test_personal_token_create_in_strips_whitespace():
    body = PersonalTokenCreateIn(name="  my label  ")
    assert body.name == "my label"
