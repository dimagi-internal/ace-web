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

    def _list_changes(token):
        calls.append(token)
        return ChangesPage(set(), "", expired=True)

    def _start():
        return "fresh-token"

    monkeypatch.setattr(client, "list_changes", _list_changes)
    monkeypatch.setattr(client, "get_changes_start_page_token", _start)

    assert observe(workspace, client) == set()
    # Subsequent observe should now use the fresh token, not the old one.
    assert observe(workspace, client) == set()


def test_failed_seed_is_not_retried_on_every_call(workspace, client, monkeypatch):
    """A seed that fails backs off instead of costing every request a Drive call.

    Observed on labs 2026-09-19: the service account was not a member of the
    shared drive, so every single request re-tried the seed, 403'd, and logged.
    """
    attempts: list[int] = []

    def _boom():
        attempts.append(1)
        raise RuntimeError("teamDriveMembershipRequired")

    monkeypatch.setattr(client, "get_changes_start_page_token", _boom)

    assert observe(workspace, client) == set()
    assert observe(workspace, client) == set()
    assert observe(workspace, client) == set()
    assert len(attempts) == 1


def test_seed_retried_once_the_backoff_expires(workspace, client, monkeypatch):
    """The backoff is a pause, not a permanent give-up — fixing access recovers."""
    from apps.opps import drive_changes

    calls: list[int] = []
    real_start = client.get_changes_start_page_token

    def _fail_first():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("teamDriveMembershipRequired")
        return real_start()

    monkeypatch.setattr(client, "get_changes_start_page_token", _fail_first)

    assert observe(workspace, client) == set()
    cache.delete(drive_changes._seed_backoff_key(workspace.pk))  # backoff expires
    assert observe(workspace, client) == set()
    assert len(calls) == 2

    # Seeded now, so a later change is reported normally.
    state_id = client.file_id("ACE/alpha/run_state.yaml")
    client.update_file(state_id, "step: b\n", "application/x-yaml")
    assert state_id in observe(workspace, client)


def test_real_client_never_scopes_the_feed_to_a_shared_drive():
    """The changes feed must be the SA's whole corpus, never `driveId=`-scoped.

    A drive-scoped call needs shared-drive MEMBERSHIP. The SA is shared on
    the ACE folder only — deliberately, since membership would grant it the
    rest of the drive — so on labs every scoped seed 403'd
    (`teamDriveMembershipRequired`, 2026-09-16 → 09-29) and no Drive edit
    ever invalidated a cached snapshot. The unscoped feed reports the same
    shared-drive files without membership.
    """
    from unittest.mock import MagicMock

    from apps.opps.drive_client import GoogleDriveClient

    drive = GoogleDriveClient.__new__(GoogleDriveClient)
    drive._service = MagicMock()
    changes = drive._service.changes.return_value
    changes.getStartPageToken.return_value.execute.return_value = {"startPageToken": "7"}
    changes.list.return_value.execute.return_value = {
        "changes": [{"fileId": "f1"}], "newStartPageToken": "8",
    }

    assert drive.get_changes_start_page_token() == "7"
    page = drive.list_changes("7")

    assert page.changed_file_ids == {"f1"}
    assert page.next_page_token == "8"
    for call in (changes.getStartPageToken.call_args, changes.list.call_args):
        assert "driveId" not in call.kwargs
        assert call.kwargs["supportsAllDrives"] is True
    assert changes.list.call_args.kwargs["includeItemsFromAllDrives"] is True


def test_a_new_file_reports_its_parent_folder(workspace, client):
    """A cached snapshot tracks the folders it listed, never a file created
    after it — so a new file must surface through its parent, or a screenshot
    written into a new previews/ folder stays invisible (the blind spot in
    docs/learnings/drive-changes-api-parent-folder-blind-spot.md)."""
    observe(workspace, client)  # seed
    alpha = client.folder_id("ACE/alpha")
    previews = client.create_folder(alpha, "previews")
    changed = observe(workspace, client)
    assert previews in changed
    assert alpha in changed


def test_a_cached_snapshot_is_dropped_when_a_file_appears_in_a_folder_it_listed(
    workspace, client,
):
    from apps.opps import snapshot_cache

    alpha = client.folder_id("ACE/alpha")
    snapshot_cache.set(
        workspace_id="1", slug="alpha", run_id=None, snap={"any": "thing"}, file_ids={alpha},
    )
    observe(workspace, client)  # seed
    client.create_folder(alpha, "previews")
    snapshot_cache.invalidate(observe(workspace, client))
    assert snapshot_cache.get(workspace_id="1", slug="alpha", run_id=None) is None
