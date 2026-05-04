"""Google Drive client abstraction.

Ported from ../connect-search/backend/app/core/drive.py. The ABC defines the
methods the sync layer uses; GoogleDriveClient is the real implementation
that wraps googleapiclient.discovery.build("drive", "v3", ...). Tests use
FakeDriveClient (apps/opps/tests/fixtures/fake_drive.py) as a drop-in.

The read surface (list_files / get_file / get_content) drives the Workbench.
The write surface (create_folder / upload_file / update_file / copy_file)
supports the web-native opp lifecycle: creating opps, editing artifacts,
and forking runs. Only the four write methods the ace-web app needs are
exposed — unrelated connect-search helpers (create_shortcut, share_file)
are intentionally not ported.
"""
from __future__ import annotations

import base64
import functools
import logging
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from apps.service_accounts import registry

log = logging.getLogger(__name__)


# Drive 5xx + 429 are common-enough that letting them surface as Django 500s
# was a real source of perceived flakiness on the opp list and Workbench. Read
# operations are idempotent so retrying is safe; writes are intentionally not
# wrapped because a duplicate create/upload on retry could leak resources.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 0.5  # seconds; effective delays roughly 0.5s, 1.0s, 2.0s + jitter


def _drive_retry(method):
    """Decorator: retry the wrapped Drive read on transient HttpError 5xx/429.

    Three attempts total with exponential backoff and small jitter. Non-retryable
    statuses (and non-HttpError exceptions) propagate immediately. Each retry is
    logged at WARNING with the underlying status so the cause stays visible
    even though the request ultimately succeeds.
    """

    @functools.wraps(method)
    def _wrapped(self, *args, **kwargs):
        # Local import keeps the module importable in test envs that stub
        # googleapiclient out (e.g. apps/opps/tests/fixtures/fake_drive.py
        # never raises HttpError).
        from googleapiclient.errors import HttpError  # noqa: PLC0415

        last_exc: Exception | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                return method(self, *args, **kwargs)
            except HttpError as exc:
                status = getattr(getattr(exc, "resp", None), "status", None)
                if status not in _RETRYABLE_STATUS or attempt == _RETRY_ATTEMPTS:
                    raise
                delay = _RETRY_BASE_DELAY * (2 ** (attempt - 1))
                delay += random.uniform(0, delay * 0.25)
                log.warning(
                    "drive_retry: %s attempt %d/%d failed status=%s; sleeping %.2fs",
                    method.__name__, attempt, _RETRY_ATTEMPTS, status, delay,
                )
                time.sleep(delay)
                last_exc = exc
        # Defensive — loop above either returns or raises; this is unreachable
        # but mypy / type-checkers like the explicit fallthrough.
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("drive_retry: exhausted attempts without exception")

    return _wrapped


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    web_view_link: str
    path: str = ""  # full slash-separated path from the listing root
    size_bytes: int | None = None
    modified_time: str | None = None                # ISO-8601 string, as returned by Drive
    parent_id: str | None = None                    # immediate parent folder id (optional)


@dataclass
class FileContent:
    content: str                                    # UTF-8 for text files; base64 for binary
    content_type: str = "text/plain"               # e.g. "text/markdown", "application/json"
    encoding: str | None = None                     # "base64" for binary files


class DriveClient(ABC):
    """Narrow read-only Drive interface the sync layer depends on."""

    @abstractmethod
    def list_files(
        self, folder_id: str, recursive: bool = False, page_size: int = 100
    ) -> list[DriveFile]:
        """List immediate children of a folder, or the full recursive tree."""

    def list_folder(self, folder_id: str) -> list[DriveFile]:
        """List immediate children of a folder (non-recursive convenience alias)."""
        return self.list_files(folder_id, recursive=False)

    @abstractmethod
    def get_file(self, file_id: str) -> DriveFile:
        """Fetch metadata for a single file or folder."""

    @abstractmethod
    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        """Fetch the body of a file. Google Docs types are exported to text/plain
        or text/csv; binary types are returned base64-encoded."""

    @abstractmethod
    def create_folder(self, parent_id: str, name: str) -> str:
        """Create a folder under parent_id. Returns new folder ID."""

    @abstractmethod
    def upload_file(
        self, parent_id: str, name: str, content: str, mime_type: str
    ) -> str:
        """Create a new file under parent_id with the given content.
        Returns new file ID."""

    @abstractmethod
    def update_file(self, file_id: str, content: str, mime_type: str) -> None:
        """Replace the content of an existing file."""

    @abstractmethod
    def copy_file(
        self, file_id: str, new_parent_id: str, new_name: str | None = None
    ) -> str:
        """Copy a file to a new parent. Returns new file ID."""

    @abstractmethod
    def trash_folder(self, folder_id: str) -> None:
        """Move a folder (and all descendants) to Drive trash.

        Drive's native trash is 30-day recoverable. We do NOT permanently
        delete — that would defeat accidental-deletion recovery."""


class GoogleDriveClient(DriveClient):
    """Real Google Drive implementation. Requires authenticated credentials."""

    FOLDER_MIME = "application/vnd.google-apps.folder"

    def __init__(self, credentials):
        from googleapiclient.discovery import build
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    @_drive_retry
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

    @_drive_retry
    def get_file(self, file_id: str) -> DriveFile:
        f = self._service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, webViewLink, size, modifiedTime",
            supportsAllDrives=True,
        ).execute()
        return self._to_drive_file(f, path=f["name"])

    @_drive_retry
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

    def create_folder(self, parent_id: str, name: str) -> str:
        body = {
            "name": name,
            "mimeType": self.FOLDER_MIME,
            "parents": [parent_id],
        }
        resp = self._service.files().create(
            body=body, fields="id", supportsAllDrives=True
        ).execute()
        return resp["id"]

    def upload_file(
        self, parent_id: str, name: str, content: str, mime_type: str
    ) -> str:
        from googleapiclient.http import MediaInMemoryUpload
        body = {"name": name, "parents": [parent_id]}
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type)
        resp = self._service.files().create(
            body=body, media_body=media, fields="id", supportsAllDrives=True
        ).execute()
        return resp["id"]

    def update_file(self, file_id: str, content: str, mime_type: str) -> None:
        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype=mime_type)
        self._service.files().update(
            fileId=file_id, media_body=media, supportsAllDrives=True
        ).execute()

    def copy_file(
        self, file_id: str, new_parent_id: str, new_name: str | None = None
    ) -> str:
        body: dict = {"parents": [new_parent_id]}
        if new_name:
            body["name"] = new_name
        resp = self._service.files().copy(
            fileId=file_id, body=body, fields="id", supportsAllDrives=True
        ).execute()
        return resp["id"]

    def trash_folder(self, folder_id: str) -> None:
        self._service.files().update(
            fileId=folder_id,
            body={"trashed": True},
            supportsAllDrives=True,
        ).execute()


class DriveServiceAccountNotConfigured(RuntimeError):
    """Kept as a backward-compatible alias. New code should catch
    ServiceAccountNotFound from the registry instead."""


def get_drive_client(
    workspace=None, on_behalf_of: str | None = None,
) -> GoogleDriveClient:
    """Return a Drive client backed by the 'ace-drive' service account.

    Args:
        workspace: Optional Workspace; when provided, the AccessLog row
            is annotated with `workspace_slug`. The credential itself is
            shared across all workspaces (one `ace-drive` SA), so this
            is purely for audit attribution.
        on_behalf_of: Optional email to impersonate via domain-wide delegation.
            Requires a matching ImpersonationGrant in the registry.
    """
    context: dict = {"caller": "opps.drive_client"}
    if workspace is not None:
        context["workspace_slug"] = workspace.slug
    creds = registry.get_credentials(
        "ace-drive",
        on_behalf_of=on_behalf_of,
        context=context,
    )
    return GoogleDriveClient(creds)
