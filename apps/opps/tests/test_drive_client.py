"""Tests for the DriveClient ABC + the FakeDriveClient test helper.

The real GoogleDriveClient is not tested here — it requires a live Google
Drive API. Its behavior is validated indirectly by sync/view fixture tests
that use FakeDriveClient as a drop-in. This test suite just locks in the
ABC contract and the fake's round-trip behavior.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from apps.opps.drive_client import (
    DriveClient,
    DriveFile,
    DriveServiceAccountNotConfigured,
    FileContent,
    GoogleDriveClient,
    get_drive_client,
)
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


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


@pytest.fixture(autouse=True)
def _clear_drive_client_cache():
    """Every test starts with an empty cache so settings patches apply."""
    get_drive_client.cache_clear()
    yield
    get_drive_client.cache_clear()


def _fake_sa_key_json() -> str:
    return json.dumps(
        {
            "type": "service_account",
            "client_email": "ace-web@example.iam.gserviceaccount.com",
            "private_key": "FAKE",
            "project_id": "fake-project",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


def test_get_drive_client_raises_when_setting_is_empty():
    with override_settings(ACE_DRIVE_SA_KEY_JSON=""):
        with pytest.raises(DriveServiceAccountNotConfigured):
            get_drive_client()


def test_get_drive_client_raises_on_malformed_json():
    with override_settings(ACE_DRIVE_SA_KEY_JSON="{not json"):
        with pytest.raises(DriveServiceAccountNotConfigured, match="not valid JSON"):
            get_drive_client()


def test_get_drive_client_constructs_credentials_and_client():
    fake_creds = MagicMock(name="fake-creds")
    fake_service = MagicMock(name="fake-service")
    with (
        override_settings(ACE_DRIVE_SA_KEY_JSON=_fake_sa_key_json()),
        patch(
            "apps.opps.drive_client.service_account.Credentials.from_service_account_info",
            return_value=fake_creds,
        ) as mk_from_info,
        patch("googleapiclient.discovery.build", return_value=fake_service) as mk_build,
    ):
        client = get_drive_client()

    assert isinstance(client, GoogleDriveClient)
    assert client._service is fake_service

    # Credentials constructor got the parsed JSON + the full drive scope.
    mk_from_info.assert_called_once()
    args, kwargs = mk_from_info.call_args
    assert args[0]["type"] == "service_account"
    assert args[0]["client_email"] == "ace-web@example.iam.gserviceaccount.com"
    assert kwargs["scopes"] == ["https://www.googleapis.com/auth/drive"]

    # The Google Drive discovery build got the right API name, version, and flags.
    mk_build.assert_called_once_with(
        "drive", "v3", credentials=fake_creds, cache_discovery=False,
    )


def test_get_drive_client_caches_client():
    fake_creds = MagicMock(name="fake-creds")
    with (
        override_settings(ACE_DRIVE_SA_KEY_JSON=_fake_sa_key_json()),
        patch(
            "apps.opps.drive_client.service_account.Credentials.from_service_account_info",
            return_value=fake_creds,
        ) as mk_from_info,
        patch("googleapiclient.discovery.build", return_value=MagicMock()),
    ):
        first = get_drive_client()
        second = get_drive_client()

    assert first is second
    # Second call should hit the cache; the SA constructor ran exactly once.
    assert mk_from_info.call_count == 1
