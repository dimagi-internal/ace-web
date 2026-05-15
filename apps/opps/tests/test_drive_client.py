"""Tests for the DriveClient ABC + the FakeDriveClient test helper.

The real GoogleDriveClient is not tested here — it requires a live Google
Drive API. Its behavior is validated indirectly by sync/view fixture tests
that use FakeDriveClient as a drop-in. This test suite just locks in the
ABC contract and the fake's round-trip behavior.
"""
from unittest.mock import MagicMock, patch

import pytest

from apps.opps.drive_client import (
    DriveClient,
    DriveFile,
    FileContent,
    GoogleDriveClient,
    get_drive_client,
)
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient
from apps.service_accounts.exceptions import ServiceAccountNotFound


def test_drive_file_dataclass_fields():
    f = DriveFile(id="1", name="x.md", mime_type="text/markdown", web_view_link="https://x")
    assert f.id == "1"
    assert f.name == "x.md"
    assert f.path == ""  # default


def test_file_content_dataclass_fields():
    c = FileContent(content="hello", content_type="text/plain")
    assert c.content == "hello"
    assert c.encoding is None


def test_drive_client_is_abstract():
    with pytest.raises(TypeError, match="abstract"):
        DriveClient()


def test_fake_drive_list_files_top_level():
    client = FakeDriveClient.from_tree({
        "ACE": {"malaria-pilot": {"pdd.md": "# IDD"}}
    })
    ace_id = client.folder_id("ACE")
    files = client.list_files(ace_id)
    assert len(files) == 1
    assert files[0].name == "malaria-pilot"
    assert files[0].mime_type == "application/vnd.google-apps.folder"
    assert files[0].path == "malaria-pilot"


def test_fake_drive_list_files_recursive():
    client = FakeDriveClient.from_tree({
        "ACE": {
            "malaria-pilot": {
                "pdd.md": "# IDD",
                "runs": {
                    "r1": {"run.yaml": "run_id: r1"}
                }
            }
        }
    })
    ace_id = client.folder_id("ACE/malaria-pilot")
    files = client.list_files(ace_id, recursive=True)
    by_name = {f.name: f for f in files}
    assert sorted(by_name) == ["pdd.md", "run.yaml"]
    # Path construction matters for downstream sync code.
    assert by_name["pdd.md"].path == "pdd.md"
    assert by_name["run.yaml"].path == "runs/r1/run.yaml"


def test_fake_drive_get_content():
    client = FakeDriveClient.from_tree({
        "ACE": {"malaria-pilot": {"pdd.md": "# Malaria IDD\nbody"}}
    })
    files = client.list_files(client.folder_id("ACE/malaria-pilot"))
    idd = next(f for f in files if f.name == "pdd.md")
    content = client.get_content(idd.id, idd.mime_type)
    assert content.content == "# Malaria IDD\nbody"
    assert content.content_type == "text/markdown"


def test_fake_drive_get_content_on_folder_raises():
    client = FakeDriveClient.from_tree({"ACE": {"malaria-pilot": {}}})
    folder_id = client.folder_id("ACE/malaria-pilot")
    with pytest.raises(ValueError, match="is a folder"):
        client.get_content(folder_id, "application/vnd.google-apps.folder")


# --- get_drive_client() factory tests ---


@pytest.mark.django_db
def test_get_drive_client_uses_registry():
    with patch("apps.opps.drive_client.registry") as mock_registry:
        mock_creds = MagicMock()
        mock_registry.get_credentials.return_value = mock_creds
        with patch("googleapiclient.discovery.build", return_value=MagicMock()):
            client = get_drive_client()
        mock_registry.get_credentials.assert_called_once_with(
            "ace-drive",
            on_behalf_of=None,
            context={"caller": "opps.drive_client"},
        )
    assert isinstance(client, GoogleDriveClient)


@pytest.mark.django_db
def test_get_drive_client_passes_on_behalf_of():
    with patch("apps.opps.drive_client.registry") as mock_registry:
        mock_creds = MagicMock()
        mock_registry.get_credentials.return_value = mock_creds
        with patch("googleapiclient.discovery.build", return_value=MagicMock()):
            get_drive_client(on_behalf_of="alice@dimagi.com")
        mock_registry.get_credentials.assert_called_once_with(
            "ace-drive",
            on_behalf_of="alice@dimagi.com",
            context={"caller": "opps.drive_client"},
        )


@pytest.mark.django_db
def test_get_drive_client_raises_on_missing_sa():
    with patch("apps.opps.drive_client.registry") as mock_registry:
        mock_registry.get_credentials.side_effect = ServiceAccountNotFound("not found")
        with pytest.raises(ServiceAccountNotFound):
            get_drive_client()


def test_fake_drive_move_file_changes_parent():
    """move_file relocates a file from one folder to another."""
    client = FakeDriveClient.from_tree({"root": {"src": {}, "dst": {}}})
    src_id = client.folder_id("root/src")
    dst_id = client.folder_id("root/dst")
    file_id = client.upload_binary(src_id, "x.mp3", b"x", "audio/mpeg")
    client.move_file(file_id, dst_id)
    in_src = {f.id for f in client.list_folder(src_id)}
    in_dst = {f.id for f in client.list_folder(dst_id)}
    assert file_id not in in_src
    assert file_id in in_dst


def test_fake_drive_trash_folder_removes_from_listings():
    tree = {
        "ACE": {
            "doomed": {"opp.yaml": "slug: doomed"},
            "alive": {"opp.yaml": "slug: alive"},
        }
    }
    fake = FakeDriveClient.from_tree(tree)
    doomed_id = fake.folder_id("ACE/doomed")
    fake.trash_folder(doomed_id)
    names = {f.name for f in fake.list_files(fake.folder_id("ACE"))}
    assert names == {"alive"}
