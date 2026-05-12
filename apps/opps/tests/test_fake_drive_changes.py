"""Tests for FakeDriveClient's changes-feed implementation."""
from __future__ import annotations

import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture
def client() -> FakeDriveClient:
    return FakeDriveClient.from_tree({
        "ACE": {
            "alpha": {
                "run_state.yaml": "current_step: a\n",
                "idea.md": "alpha idea",
            }
        }
    })


def test_start_token_is_stable_string(client):
    tok = client.get_changes_start_page_token()
    assert isinstance(tok, str)
    assert tok != ""


def test_list_changes_returns_empty_initially(client):
    tok = client.get_changes_start_page_token()
    page = client.list_changes(tok)
    assert page.changed_file_ids == set()
    assert page.next_page_token != ""
    assert page.expired is False


def test_list_changes_reports_mutations_after_token(client):
    tok = client.get_changes_start_page_token()
    state_id = client.file_id("ACE/alpha/run_state.yaml")
    client.update_file(state_id, "current_step: b\n", "application/x-yaml")

    page = client.list_changes(tok)
    assert state_id in page.changed_file_ids

    # Next page token consumes the change — second call sees nothing.
    page2 = client.list_changes(page.next_page_token)
    assert page2.changed_file_ids == set()


def test_list_changes_reports_creates(client):
    tok = client.get_changes_start_page_token()
    alpha_id = client.folder_id("ACE/alpha")
    new_id = client.upload_file(alpha_id, "new.md", "body", "text/markdown")

    page = client.list_changes(tok)
    assert new_id in page.changed_file_ids


def test_list_changes_reports_deletes(client):
    state_id = client.file_id("ACE/alpha/run_state.yaml")
    tok = client.get_changes_start_page_token()
    # Trash the parent folder; the fake should record the delete of children.
    alpha_id = client.folder_id("ACE/alpha")
    client.trash_folder(alpha_id)

    page = client.list_changes(tok)
    assert state_id in page.changed_file_ids
