import logging

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

REAL = "sk-ant-oat01-" + "Z" * 50  # distinctive enough to spot in any log line


@pytest.mark.django_db
def test_upload_does_not_log_full_token(caplog, monkeypatch):
    """Capture all logs emitted during an upload and assert the full access token
    never appears as a substring. Only the 15-char prefix is allowed."""
    user = get_user_model().objects.create_user(email="log@dimagi.com")
    client = APIClient()
    client.force_authenticate(user=user)

    # Stub the live probe so we don't run claude in CI.
    from apps.common import auth_flow
    monkeypatch.setattr(
        auth_flow, "_check_token_via_cli", lambda blob_json=None, on_refresh=None: True
    )

    with caplog.at_level(logging.DEBUG):
        resp = client.post(
            "/api/auth/cli/upload",
            {"claudeAiOauth": {"accessToken": REAL, "refreshToken": "r"}},
            format="json",
        )
        assert resp.status_code == 200

    combined = "\n".join(rec.getMessage() for rec in caplog.records)
    assert REAL not in combined, f"Full token leaked in logs: {combined[-500:]}"
    # The token is sk-ant-oat01-ZZZ... — the suffix after the 15-char prefix is
    # 'Z' * 47. If anything beyond the documented prefix appears in logs, fail.
    assert REAL[15:] not in combined, "Suffix of token leaked — partial exposure"
