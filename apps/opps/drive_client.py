"""Google Drive client abstraction.

Ported from ../connect-search/backend/app/core/drive.py. The ABC defines the
methods the sync layer uses; GoogleDriveClient is the real implementation
that wraps googleapiclient.discovery.build("drive", "v3", ...). Tests use
FakeDriveClient (apps/opps/tests/fixtures/fake_drive.py) as a drop-in.

Surface kept intentionally small: the Workbench only ever reads — listing
folders recursively, fetching file content, getting file metadata. Writes
(create_folder, create_shortcut, share_file) from the connect-search version
are not ported because the ace-web Workbench never writes to Drive.
"""
from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass

from apps.service_accounts import registry


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    web_view_link: str
    path: str = ""  # full slash-separated path from the listing root
    size_bytes: int | None = None
    modified_time: str | None = None                # ISO-8601 string, as returned by Drive


@dataclass
class FileContent:
    content: str                                    # UTF-8 for text files; base64 for binary
    content_type: str                               # e.g. "text/markdown", "application/json"
    encoding: str | None = None                     # "base64" for binary files


class DriveClient(ABC):
    """Narrow read-only Drive interface the sync layer depends on."""

    @abstractmethod
    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        """List immediate children of a folder, or the full recursive tree."""

    @abstractmethod
    def get_file(self, file_id: str) -> DriveFile:
        """Fetch metadata for a single file or folder."""

    @abstractmethod
    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        """Fetch the body of a file. Google Docs types are exported to text/plain
        or text/csv; binary types are returned base64-encoded."""


class GoogleDriveClient(DriveClient):
    """Real Google Drive implementation. Requires authenticated credentials."""

    FOLDER_MIME = "application/vnd.google-apps.folder"

    def __init__(self, credentials):
        from googleapiclient.discovery import build
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        results: list[DriveFile] = []
        self._list_folder(folder_id, path="", results=results, recursive=recursive,
                          page_size=page_size)
        return results

    def _list_folder(
        self, folder_id: str, path: str, results: list, recursive: bool, page_size: int
    ):
        page_token = None
        while True:
            response = self._service.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields=(
                    "nextPageToken, "
                    "files(id, name, mimeType, webViewLink, size, modifiedTime)"
                ),
                pageSize=page_size,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()

            for f in response.get("files", []):
                file_path = f"{path}/{f['name']}" if path else f["name"]
                if f["mimeType"] == self.FOLDER_MIME:
                    if recursive:
                        self._list_folder(f["id"], file_path, results, True, page_size)
                    else:
                        results.append(self._to_drive_file(f, file_path))
                else:
                    results.append(self._to_drive_file(f, file_path))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

    @staticmethod
    def _to_drive_file(f: dict, path: str) -> DriveFile:
        size = f.get("size")
        return DriveFile(
            id=f["id"],
            name=f["name"],
            mime_type=f["mimeType"],
            web_view_link=f.get("webViewLink", ""),
            path=path,
            size_bytes=int(size) if size is not None else None,
            modified_time=f.get("modifiedTime"),
        )

    def get_file(self, file_id: str) -> DriveFile:
        f = self._service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, webViewLink, size, modifiedTime",
            supportsAllDrives=True,
        ).execute()
        return self._to_drive_file(f, path=f["name"])

    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        export_map = {
            "application/vnd.google-apps.document": ("text/plain", "text/plain"),
            "application/vnd.google-apps.spreadsheet": ("text/csv", "text/csv"),
            "application/vnd.google-apps.presentation": ("text/plain", "text/plain"),
        }
        if mime_type in export_map:
            export_mime, content_type = export_map[mime_type]
            content = self._service.files().export(
                fileId=file_id, mimeType=export_mime
            ).execute()
            text = content.decode("utf-8") if isinstance(content, bytes) else content
            return FileContent(content=text, content_type=content_type)

        # Regular file download.
        content = self._service.files().get_media(fileId=file_id).execute()
        if isinstance(content, bytes):
            try:
                text = content.decode("utf-8")
                return FileContent(content=text, content_type=mime_type)
            except UnicodeDecodeError:
                return FileContent(
                    content=base64.b64encode(content).decode("ascii"),
                    content_type=mime_type,
                    encoding="base64",
                )
        return FileContent(content=content, content_type=mime_type)


class DriveServiceAccountNotConfigured(RuntimeError):
    """Kept as a backward-compatible alias. New code should catch
    ServiceAccountNotFound from the registry instead."""


def get_drive_client(on_behalf_of: str | None = None) -> GoogleDriveClient:
    """Return a Drive client backed by the 'ace-drive' service account.

    Args:
        on_behalf_of: Optional email to impersonate via domain-wide delegation.
            Requires a matching ImpersonationGrant in the registry.
    """
    creds = registry.get_credentials(
        "ace-drive",
        on_behalf_of=on_behalf_of,
        context={"caller": "opps.drive_client"},
    )
    return GoogleDriveClient(creds)
