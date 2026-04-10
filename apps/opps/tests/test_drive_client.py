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
        "ACE": {"malaria-pilot": {"idd.md": "# IDD"}}
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
                "idd.md": "# IDD",
                "runs": {
                    "r1": {"run.yaml": "run_id: r1"}
                }
            }
        }
    })
    ace_id = client.folder_id("ACE/malaria-pilot")
    files = client.list_files(ace_id, recursive=True)
    by_name = {f.name: f for f in files}
    assert sorted(by_name) == ["idd.md", "run.yaml"]
    # Path construction matters for downstream sync code.
    assert by_name["idd.md"].path == "idd.md"
    assert by_name["run.yaml"].path == "runs/r1/run.yaml"


def test_fake_drive_get_content():
    client = FakeDriveClient.from_tree({
        "ACE": {"malaria-pilot": {"idd.md": "# Malaria IDD\nbody"}}
    })
    files = client.list_files(client.folder_id("ACE/malaria-pilot"))
    idd = next(f for f in files if f.name == "idd.md")
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
