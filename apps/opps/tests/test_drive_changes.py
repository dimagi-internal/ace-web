"""Tests for apps.opps.drive_changes.observe()."""
from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.opps.drive_changes import observe
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient

pytestmark = pytest.mark.django_db


class _StubWorkspace:
    """Minimal stand-in — observe() reads .pk and .drive_root_folder_id."""
    def __init__(self, id: int, drive_root_folder_id: str):
        self.id = id
        self.pk = id  # observe() uses workspace.pk (Workspace uses slug as PK)
        self.drive_root_folder_id = drive_root_folder_id


@pytest.fixture(autouse=True)
def _flush_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client() -> FakeDriveClient:
    return FakeDriveClient.from_tree({
        "ACE": {
            "alpha": {"run_state.yaml": "step: a\n"},
            "beta": {"run_state.yaml": "step: a\n"},
        }
    })


@pytest.fixture
def workspace(client) -> _StubWorkspace:
    return _StubWorkspace(id=1, drive_root_folder_id=client.folder_id("ACE"))


def test_first_call_seeds_token_and_returns_empty(workspace, client):
    changed = observe(workspace, client)
    assert changed == set()


def test_second_call_after_no_mutation_returns_empty(workspace, client):
    observe(workspace, client)
    assert observe(workspace, client) == set()


def test_call_after_mutation_returns_changed_file_id(workspace, client):
    observe(workspace, client)  # seed
    state_id = client.file_id("ACE/alpha/run_state.yaml")
    client.update_file(state_id, "step: b\n", "application/x-yaml")

    changed = observe(workspace, client)
    assert state_id in changed


def test_each_change_reported_exactly_once(workspace, client):
    observe(workspace, client)
    state_id = client.file_id("ACE/alpha/run_state.yaml")
    client.update_file(state_id, "step: b\n", "application/x-yaml")

    first = observe(workspace, client)
    second = observe(workspace, client)
    assert state_id in first
    assert state_id not in second  # token advanced past it


def test_drive_api_failure_returns_empty(workspace, client, monkeypatch):
    """If list_changes raises, observe returns set() and logs WARNING."""
    observe(workspace, client)  # seed

    def _boom(*args, **kwargs):
        raise RuntimeError("network down")
    monkeypatch.setattr(client, "list_changes", _boom)

    assert observe(workspace, client) == set()


def test_410_expired_token_reseeds_and_returns_empty(workspace, client, monkeypatch):
    """A 410-style response triggers re-seed; caller sees empty set."""
    from apps.opps.drive_client import ChangesPage

    observe(workspace, client)
    calls: list[str] = []

    def _list_changes(token, *, drive_id=None):
        calls.append(token)
        return ChangesPage(set(), "", expired=True)

    def _start(drive_id=None):
        return "fresh-token"

    monkeypatch.setattr(client, "list_changes", _list_changes)
    monkeypatch.setattr(client, "get_changes_start_page_token", _start)

    assert observe(workspace, client) == set()
    # Subsequent observe should now use the fresh token, not the old one.
    assert observe(workspace, client) == set()
