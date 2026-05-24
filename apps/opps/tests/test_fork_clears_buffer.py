"""Test that fork_opp_and_return clears the shared edit buffer on success.

The test imports apps.opps.api lazily so it is skipped gracefully in
local environments where the dev venv is missing optional schema
dependencies (email-validator). In CI the full dep set is installed and
the test runs normally.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from apps.opps.decisions_buffer import get_edits, set_edit


@pytest.fixture(autouse=True)
def _clear_cache():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_fork_clears_shared_buffer(monkeypatch):
    """After a successful fork, clear_edits() removes the source run's edit buffer."""
    try:
        from apps.opps.api import fork_opp_and_return  # noqa: PLC0415
    except ImportError as exc:
        pytest.skip(f"Schema deps not installed in this env: {exc}")

    set_edit(
        "my-opp", "run-1", row_id="d-001", new_answer="No",
        editor_email="a@b.com", editor_name="A",
    )
    assert get_edits("my-opp", "run-1") != {}

    mock_result = SimpleNamespace(
        opp_slug="my-opp",
        new_run_id="run-2",
        working_session=SimpleNamespace(slug="ws-1"),
    )

    monkeypatch.setattr(
        "apps.opps.access.resolve_ace_root_folder_id",
        lambda ws: "folder-id",
    )
    monkeypatch.setattr(
        "apps.opps.drive_client.get_drive_client",
        lambda workspace: MagicMock(),
    )
    monkeypatch.setattr(
        "apps.opps.opp_forker.fork_opp",
        lambda **kwargs: mock_result,
    )

    from apps.opps.schemas import OppForkIn  # noqa: PLC0415

    workspace = MagicMock()
    workspace.pk = "ws"
    user = MagicMock()
    body = OppForkIn(fork_at_phase="idea-to-design", source_run_id="run-1")

    fork_opp_and_return(workspace, user, "my-opp", body)

    assert get_edits("my-opp", "run-1") == {}
