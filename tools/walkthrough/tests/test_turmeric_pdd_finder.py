"""Tests for find_latest_turmeric_pdd against a FakeDriveClient."""
import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from tools.walkthrough.turmeric_pdd_finder import (
    PDDFinderError,
    find_latest_turmeric_pdd,
)


def _tree_with_two_pdd_folders() -> dict:
    return {
        "ACE": {
            "Program Design Docs (PDDs)": {
                "turmeric-v1.md": "old turmeric body",
                "turmeric-v2-updated.md": "new turmeric body",
                "malaria-v1.md": "unrelated",
            },
            "other-folder": {"nope.md": "nothing"},
        }
    }


def test_finds_most_recently_modified_turmeric_pdd():
    fake = FakeDriveClient.from_tree(_tree_with_two_pdd_folders())
    fake.set_modified_time("ACE/Program Design Docs (PDDs)/turmeric-v1.md", "2026-01-01T00:00:00Z")
    fake.set_modified_time("ACE/Program Design Docs (PDDs)/turmeric-v2-updated.md", "2026-04-10T00:00:00Z")

    title, body = find_latest_turmeric_pdd(fake, ace_folder_id=fake.folder_id("ACE"))
    assert title == "turmeric-v2-updated.md"
    assert body == "new turmeric body"


def test_matches_pdd_folder_case_insensitively():
    tree = {
        "ACE": {
            "program design docs": {"turmeric.md": "body"},
        }
    }
    fake = FakeDriveClient.from_tree(tree)
    title, body = find_latest_turmeric_pdd(fake, ace_folder_id=fake.folder_id("ACE"))
    assert title == "turmeric.md"


def test_raises_when_no_pdd_folder():
    fake = FakeDriveClient.from_tree({"ACE": {"other": {"turmeric.md": "x"}}})
    with pytest.raises(PDDFinderError, match="no PDD folder"):
        find_latest_turmeric_pdd(fake, ace_folder_id=fake.folder_id("ACE"))


def test_raises_when_no_turmeric_file():
    fake = FakeDriveClient.from_tree({
        "ACE": {"Program Design Docs (PDDs)": {"malaria.md": "x"}}
    })
    with pytest.raises(PDDFinderError, match="no turmeric"):
        find_latest_turmeric_pdd(fake, ace_folder_id=fake.folder_id("ACE"))
