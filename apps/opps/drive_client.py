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
import threading
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
    drive_id: str | None = None                     # shared-drive id; None for My Drive


@dataclass
class FileContent:
    content: str                                    # UTF-8 for text files; base64 for binary
    content_type: str = "text/plain"               # e.g. "text/markdown", "application/json"
    encoding: str | None = None                     # "base64" for binary files


@dataclass
class ChangesPage:
    """One page of `drive.changes.list` results.

    `changed_file_ids` is the set of file IDs whose state changed (created,
    modified, removed) since the input page token. `next_page_token` is the
    token to use on the next `list_changes` call to fetch only what changed
    after this page; it is durable across calls and process restarts.

    `expired` is True when Drive returned 410 Gone on the input token —
    callers should treat all caches scoped to this drive as invalid and
    re-seed via `get_changes_start_page_token`.
    """
    changed_file_ids: set[str]
    next_page_token: str
    expired: bool = False


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
    def get_content(
        self, file_id: str, mime_type: str, *, export_as: str | None = None
    ) -> FileContent:
        """Fetch the body of a file. Google Docs types are exported to text/plain
        or text/csv; binary types are returned base64-encoded.

        ``export_as`` overrides the export MIME for a Google-native type on
        THIS read only (e.g. ``text/markdown`` for an ACE-authored prose doc).
        It is deliberately per-call, never a global default: `run_state.yaml`,
        `decisions.yaml` and every verdict are also Google Docs, and exporting
        those as markdown escapes the YAML (``\\---``, ``run\\_id``) and breaks
        the parse. Use `apps.opps.drive_export.prose_export_mime` to decide.
        Ignored for non-Google-native files."""

    def link_shared(self, file_ids: list[str]) -> dict[str, bool]:
        """Which of ``file_ids`` anyone with the link can open.

        MEASURED, never assumed. The public run-summary page tags every
        link it serves with who can open it, and the only honest source
        for a Drive link is the file's own ACL: a file carrying an
        ``anyone`` permission is openable by a partner with no Google
        account, and one that does not is not. Asserting either without
        reading it produces a page that tells a reviewer "Open" next to a
        door that answers "You need access."

        Returns ``{file_id: True|False}`` for every id it could resolve.
        An id ABSENT from the result means **could not tell** — the read
        failed, or this client cannot perform it. Callers must render
        that as unknown; they must NOT default it either way, which is
        the bug this method exists to remove.

        Not abstract: a DriveClient that cannot read ACLs is a valid
        client, it simply knows nothing here, and the base answer ("I
        could resolve none of these") is exactly right for it.
        """
        return {}

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
    def upload_binary(
        self, parent_id: str, name: str, content: bytes, mime_type: str
    ) -> str:
        """Create a new file under parent_id with binary content (no UTF-8 encode).
        Returns new file ID. Use for audio/video/image/etc."""

    @abstractmethod
    def update_binary(self, file_id: str, content: bytes, mime_type: str) -> None:
        """Replace the content of an existing file with binary bytes."""

    @abstractmethod
    def get_binary(self, file_id: str) -> bytes:
        """Fetch the raw bytes of a Drive file. Unlike ``get_content`` (which
        round-trips through base64 for non-utf8 payloads) this returns raw
        bytes — appropriate for the audio cache + music bed download paths
        where the caller writes the result straight to a local file."""

    @abstractmethod
    def copy_file(
        self, file_id: str, new_parent_id: str, new_name: str | None = None
    ) -> str:
        """Copy a file to a new parent. Returns new file ID."""

    @abstractmethod
    def move_file(self, file_id: str, new_parent_id: str) -> None:
        """Change file_id's parent to new_parent_id (atomic; no copy).

        Drive supports this via files.update with addParents + removeParents
        query params. Operates on whatever parent(s) the file currently has;
        after the call the file lives only under new_parent_id.
        """

    @abstractmethod
    def trash_folder(self, folder_id: str) -> None:
        """Move a folder (and all descendants) to Drive trash.

        Drive's native trash is 30-day recoverable. We do NOT permanently
        delete — that would defeat accidental-deletion recovery."""

    # --- Changes feed (for cache invalidation) ---

    @abstractmethod
    def get_changes_start_page_token(self, drive_id: str | None = None) -> str:
        """Return a fresh `pageToken` for `list_changes` from this point in time.

        Used when no token is stored yet, or after a 410 Gone reply forces a
        full re-seed. Pass `drive_id` for a shared drive; pass None for the
        SA's My Drive (the `corpora=user` scope).
        """

    @abstractmethod
    def list_changes(
        self, page_token: str, *, drive_id: str | None = None
    ) -> ChangesPage:
        """Return one page of changes since `page_token`.

        On 410 Gone (token expired), returns a `ChangesPage` with
        `expired=True`, `changed_file_ids=set()`, and `next_page_token=""` —
        callers should re-seed via `get_changes_start_page_token`.

        Drains pagination internally — the caller gets one logical page of
        all changes since `page_token`, with `next_page_token` ready for
        the next call.
        """


class GoogleDriveClient(DriveClient):
    """Real Google Drive implementation. Requires authenticated credentials."""

    FOLDER_MIME = "application/vnd.google-apps.folder"

    def __init__(self, credentials):
        from googleapiclient.discovery import build
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self._credentials = credentials
        # Per-thread transports. googleapiclient's service object is shared
        # safely across threads ONLY if each request carries its own http —
        # the underlying httplib2.Http holds a single connection and reusing
        # it concurrently corrupts responses (it surfaces as
        # ConnectionResetError, not as anything that says "threading").
        self._local = threading.local()

    def _thread_http(self):
        """An authorized http bound to the calling thread."""
        http = getattr(self._local, "http", None)
        if http is None:
            import google_auth_httplib2
            import httplib2

            http = google_auth_httplib2.AuthorizedHttp(
                self._credentials, http=httplib2.Http(timeout=60)
            )
            self._local.http = http
        return http

    # ── Fast paths for bulk run listing ──────────────────────────────────
    # `canopy_agent_runs`'s DriveRunStore negotiates these off the client and
    # falls back to per-run calls when absent. They exist because the
    # fallback costs 1 + 2N sequential round-trips: on a 12-run opp that
    # measured ~25 calls and 30-50s of wall clock, behind a 30s content cache
    # a 50s load can never populate — so every page view paid full price.

    @_drive_retry
    def find_in_folders(self, parent_ids: list[str], name: str) -> dict:
        """{parent_id: DriveFile | None} for `name` under each parent.

        One query per chunk of parents instead of one listing per parent.
        Chunked because the `q` string is bounded and a long OR-list is
        rejected whole — a 400 here would look like "the opp has no runs".
        """
        out: dict[str, DriveFile | None] = {pid: None for pid in parent_ids}
        if not parent_ids:
            return out
        escaped = name.replace("'", "\\'")
        CHUNK = 25
        for i in range(0, len(parent_ids), CHUNK):
            chunk = parent_ids[i:i + CHUNK]
            parents = " or ".join(f"'{pid}' in parents" for pid in chunk)
            page_token = None
            while True:
                resp = self._service.files().list(
                    q=f"({parents}) and name = '{escaped}' and trashed = false",
                    fields=(
                        "nextPageToken, "
                        "files(id, name, mimeType, webViewLink, size, "
                        "modifiedTime, driveId, parents)"
                    ),
                    pageSize=100,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute()
                for f in resp.get("files", []):
                    for parent in f.get("parents", []) or []:
                        if parent in out:
                            out[parent] = DriveFile(
                                id=f["id"],
                                name=f["name"],
                                mime_type=f["mimeType"],
                                web_view_link=f.get("webViewLink", ""),
                                path=f["name"],
                                size_bytes=int(f["size"]) if f.get("size") else None,
                                modified_time=f.get("modifiedTime"),
                                parent_id=parent,
                                drive_id=f.get("driveId"),
                            )
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break
        return out

    def link_shared(self, file_ids: list[str]) -> dict[str, bool]:
        """Concurrent ``permissions.list`` per file — see the base docstring.

        ``files.get(fields="permissions")`` is NOT a substitute and was
        tried first: on the ACE shared drive it returns an EMPTY list for
        every file, including ones that are demonstrably anyone-with-link
        readable, so a reader built on it would have called every
        deliverable admin-only. ``permissions.list`` returns the real ACL
        — verified 2026-08-26 against the spark-facilitator run: the
        training LLO guide (anonymously reachable, 307) carries
        ``{'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'commenter'}``
        and the PDD (anonymously 401) carries no ``anyone`` entry at all.

        Any ``anyone`` permission counts regardless of role — reader,
        commenter and writer all mean the link opens without an account.

        One failure costs that id, not the batch: it is omitted from the
        result, which the caller renders as unknown.
        """
        from concurrent.futures import ThreadPoolExecutor

        out: dict[str, bool] = {}
        ids = [fid for fid in dict.fromkeys(file_ids) if fid]
        if not ids:
            return out

        def _one(file_id: str):
            try:
                resp = self._service.permissions().list(
                    fileId=file_id,
                    fields="permissions(id,type,role)",
                    supportsAllDrives=True,
                ).execute(http=self._thread_http())
            except Exception:  # noqa: BLE001
                log.warning("link_shared failed for %s", file_id, exc_info=True)
                return file_id, None
            perms = resp.get("permissions") or []
            return file_id, any(p.get("type") == "anyone" for p in perms)

        with ThreadPoolExecutor(max_workers=8) as pool:
            for file_id, shared in pool.map(_one, ids):
                if shared is not None:
                    out[file_id] = shared
        return out

    def get_contents(self, specs: list) -> dict:
        """{file_id: text} for many files, concurrently.

        One failed read must not sink the batch — a single unreadable
        run_state should cost that row, not the whole page — so failures are
        logged and omitted rather than raised.
        """
        from concurrent.futures import ThreadPoolExecutor

        out: dict[str, str] = {}
        if not specs:
            return out

        def _one(spec):
            file_id, mime_type = spec
            try:
                return file_id, self._get_content_threadsafe(file_id, mime_type)
            except Exception:  # noqa: BLE001
                log.warning("bulk read failed for %s", file_id, exc_info=True)
                return file_id, None

        # Bounded: Drive rate-limits per user, and the win is already ~10x by
        # 8 workers. More would trade throughput for 403 rateLimitExceeded.
        with ThreadPoolExecutor(max_workers=8) as pool:
            for file_id, text in pool.map(_one, specs):
                if text is not None:
                    out[file_id] = text
        return out

    def _get_content_threadsafe(self, file_id: str, mime_type: str) -> str:
        """get_content's read path, but with a per-thread transport."""
        http = self._thread_http()
        if mime_type.startswith("application/vnd.google-apps."):
            export_mime = "text/csv" if mime_type.endswith(".spreadsheet") else "text/plain"
            content = self._service.files().export(
                fileId=file_id, mimeType=export_mime
            ).execute(http=http)
        else:
            content = self._service.files().get_media(fileId=file_id).execute(http=http)
        if isinstance(content, bytes):
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                import base64
                return base64.b64encode(content).decode("ascii")
        return content

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
                    "files(id, name, mimeType, webViewLink, size, modifiedTime, driveId)"
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
            drive_id=f.get("driveId") or None,
        )

    @_drive_retry
    def get_file(self, file_id: str) -> DriveFile:
        f = self._service.files().get(
            fileId=file_id,
            fields="id, name, mimeType, webViewLink, size, modifiedTime, driveId",
            supportsAllDrives=True,
        ).execute()
        return self._to_drive_file(f, path=f["name"])

    @_drive_retry
    def get_content(
        self, file_id: str, mime_type: str, *, export_as: str | None = None
    ) -> FileContent:
        export_map = {
            "application/vnd.google-apps.document": ("text/plain", "text/plain"),
            "application/vnd.google-apps.spreadsheet": ("text/csv", "text/csv"),
            "application/vnd.google-apps.presentation": ("text/plain", "text/plain"),
        }
        if mime_type in export_map:
            export_mime, content_type = export_map[mime_type]
            if export_as:
                export_mime = content_type = export_as
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

    def upload_binary(
        self, parent_id: str, name: str, content: bytes, mime_type: str
    ) -> str:
        from googleapiclient.http import MediaInMemoryUpload
        body = {"name": name, "parents": [parent_id]}
        media = MediaInMemoryUpload(content, mimetype=mime_type)
        resp = self._service.files().create(
            body=body, media_body=media, fields="id", supportsAllDrives=True
        ).execute()
        return resp["id"]

    def update_binary(self, file_id: str, content: bytes, mime_type: str) -> None:
        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(content, mimetype=mime_type)
        self._service.files().update(
            fileId=file_id, media_body=media, supportsAllDrives=True
        ).execute()

    @_drive_retry
    def get_binary(self, file_id: str) -> bytes:
        content = self._service.files().get_media(fileId=file_id).execute()
        if isinstance(content, bytes):
            return content
        # googleapiclient sometimes returns str for tiny payloads; coerce.
        if isinstance(content, str):
            return content.encode("latin-1")
        raise TypeError(
            f"Unexpected Drive get_media return type: {type(content).__name__}"
        )

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

    @_drive_retry
    def move_file(self, file_id: str, new_parent_id: str) -> None:
        # First fetch the file's current parents so removeParents is exact.
        meta = self._service.files().get(
            fileId=file_id, fields="parents", supportsAllDrives=True,
        ).execute()
        old_parents = ",".join(meta.get("parents", []))
        self._service.files().update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=old_parents,
            fields="id, parents",
            supportsAllDrives=True,
        ).execute()

    def trash_folder(self, folder_id: str) -> None:
        self._service.files().update(
            fileId=folder_id,
            body={"trashed": True},
            supportsAllDrives=True,
        ).execute()

    @_drive_retry
    def get_changes_start_page_token(self, drive_id: str | None = None) -> str:
        kwargs: dict = {"supportsAllDrives": True}
        if drive_id:
            kwargs["driveId"] = drive_id
        resp = self._service.changes().getStartPageToken(**kwargs).execute()
        return resp["startPageToken"]

    @_drive_retry
    def list_changes(
        self, page_token: str, *, drive_id: str | None = None
    ) -> ChangesPage:
        from googleapiclient.errors import HttpError  # noqa: PLC0415

        changed: set[str] = set()
        token = page_token
        try:
            while True:
                kwargs: dict = {
                    "pageToken": token,
                    "fields": "newStartPageToken,nextPageToken,changes(fileId,removed)",
                    "supportsAllDrives": True,
                    "includeItemsFromAllDrives": True,
                    "pageSize": 1000,
                    "spaces": "drive",
                }
                if drive_id:
                    kwargs["driveId"] = drive_id
                resp = self._service.changes().list(**kwargs).execute()
                for c in resp.get("changes", []):
                    fid = c.get("fileId")
                    if fid:
                        changed.add(fid)
                next_token = resp.get("nextPageToken")
                if next_token:
                    token = next_token
                    continue
                # End of pagination: capture newStartPageToken for next observe.
                return ChangesPage(
                    changed_file_ids=changed,
                    next_page_token=resp.get("newStartPageToken", token),
                    expired=False,
                )
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status in (410, "410"):
                return ChangesPage(
                    changed_file_ids=set(), next_page_token="", expired=True,
                )
            raise


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
