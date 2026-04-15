"""Tests for the write surface on the DriveClient ABC (Task 0 of the
web-native opp lifecycle plan).

Covers create_folder, upload_file, update_file, and copy_file against
FakeDriveClient. GoogleDriveClient's real behavior is exercised in
integration tests; these unit tests pin the in-memory fake's contract
so downstream tasks (opp creation, artifact editing, fork run) have a
stable foundation.
"""
from __future__ import annotations

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


def test_create_folder_inside_existing_folder():
    fake = FakeDriveClient.from_tree({"ACE": {}})
    ace_id = fake.folder_id("ACE")
    new_id = fake.create_folder(parent_id=ace_id, name="malaria-pilot")
    children = fake.list_files(ace_id)
    assert any(f.id == new_id and f.name == "malaria-pilot" for f in children)


def test_upload_file_text():
    fake = FakeDriveClient.from_tree({"ACE": {"malaria-pilot": {}}})
    folder_id = fake.folder_id("ACE/malaria-pilot")
    file_id = fake.upload_file(
        parent_id=folder_id,
        name="idea.md",
        content="# Malaria pilot\n",
        mime_type="text/markdown",
    )
    content = fake.get_content(file_id, "text/markdown")
    assert content.content == "# Malaria pilot\n"


def test_update_file_replaces_content():
    fake = FakeDriveClient.from_tree({
        "ACE": {"malaria-pilot": {"idea.md": "# Old\n"}}
    })
    file_id = fake.file_id("ACE/malaria-pilot/idea.md")
    fake.update_file(file_id, content="# New\n", mime_type="text/markdown")
    assert fake.get_content(file_id, "text/markdown").content == "# New\n"


def test_copy_file_to_new_parent():
    fake = FakeDriveClient.from_tree({
        "ACE": {
            "malaria-pilot": {
                "runs": {
                    "run-001": {"idd.md": "# IDD body"},
                    "run-002": {},
                }
            }
        }
    })
    src_id = fake.file_id("ACE/malaria-pilot/runs/run-001/idd.md")
    dst_folder = fake.folder_id("ACE/malaria-pilot/runs/run-002")
    new_id = fake.copy_file(src_id, dst_folder, new_name="idd.md")
    assert fake.get_content(new_id, "text/markdown").content == "# IDD body"
