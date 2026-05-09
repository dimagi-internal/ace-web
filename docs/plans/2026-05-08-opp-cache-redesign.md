# Opp Workbench Cache Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 30-second TTL Drive cache with a Drive-Changes-API–driven long-lived snapshot cache + ETag-aware frontend cache so loading any opp once makes subsequent navigations instant until something in that opp's tree actually changes in Drive.

**Architecture:** Two new backend modules (`drive_changes.py` for the per-request `changes.list` poll; `snapshot_cache.py` for assembled-`OppSnapshot` storage with file-id reverse index). One new frontend module (`oppCache.ts` with module-scoped `Map<key, {data, etag}>`). View layer wires them in: each request validates the cache against Drive's change feed, returns `304 Not Modified` when the frontend's ETag matches, only re-walks Drive on actual change. Existing `CachedDriveClient` survives as in-load dedup.

**Tech Stack:** Python 3.12, Django 5, Channels 4, Redis (django-cache + channels-redis), pytest + pytest-django, React 19, TypeScript 5, Vite 5, fetch API.

**Spec:** `docs/specs/2026-05-08-opp-cache-redesign.md`

---

## File Structure

**New backend files:**
- `apps/opps/drive_changes.py` — `observe(workspace, client) -> set[str]`. Wraps `drive.changes.list`. Manages pageToken in Redis. Per-request polling, no debounce. Handles 410 Gone via full workspace invalidation.
- `apps/opps/snapshot_cache.py` — `get/set/invalidate/fingerprint` for `OppSnapshot`; `get_card/set_card` for `OppCard`; `clear_workspace` for 410 fallback. Stores in Redis, maintains a file_id → cache_key reverse index, also stashes file_ids inline in the cached value as a fallback when the index is missing.
- `apps/opps/touched_tracker.py` — context-manager + contextvar: any `DriveClient` call inside the `with` block records `(file_id, modified_time)` tuples. Used to populate the reverse index after a `load_opp` walk.
- `apps/opps/tests/test_drive_changes.py` — unit tests for `observe()`.
- `apps/opps/tests/test_snapshot_cache.py` — unit tests for the snapshot cache.
- `apps/opps/tests/test_touched_tracker.py` — unit tests for the tracker.

**Modified backend files:**
- `apps/opps/drive_client.py` — add `get_changes_start_page_token() -> str` and `list_changes(page_token) -> ChangesPage` to the ABC; implement on `GoogleDriveClient`.
- `apps/opps/tests/fixtures/fake_drive.py` — implement Changes API methods on `FakeDriveClient` (track mutations, return them on `list_changes`).
- `apps/opps/views.py` — wire `workbench()` and `_opp_list_impl()` to the snapshot cache + Changes API + ETag header.
- `apps/opps/tests/test_views_workbench.py` — extend with cache-hit / 304 / cache-invalidation tests.
- `apps/opps/tests/test_views_opp_list.py` — same.
- `config/settings/base.py` — add `OPPS_USE_CHANGES_API` flag (default `False`).
- `config/settings/connectlabs.py` — flip the flag to `True` (last task; rollout).

**Existing backend files preserved:**
- `apps/opps/drive_cache.py` — `CachedDriveClient` stays. Still does in-load deduplication during the cold-path walk. Untouched.

**New frontend files:**
- `frontend/src/api/oppCache.ts` — module-scoped `Map<string, Entry<T>>` cache + drop helpers + clearAll.

**Modified frontend files:**
- `frontend/src/api/client.ts` — add `apiFetchWithEtag<T>(path, opts)` helper that returns `{ status: 200 | 304, data?: T, etag: string }` so callers can plumb `If-None-Match`.
- `frontend/src/api/opps.ts` — `getOpp` and `listOpps` send `If-None-Match` from the cache and update on response.
- `frontend/src/pages/OppWorkbenchPage.tsx` — `useOppSocket` callback drops the cached entry; refetch loses `force: true`.

---

## Task 1: Add Drive Changes API surface to `DriveClient` ABC + GoogleDriveClient

**Files:**
- Modify: `apps/opps/drive_client.py`
- Test: `apps/opps/tests/test_drive_client.py`

The ABC needs two methods so `drive_changes.py` can be tested with the in-process fake. The real Google implementation wraps `service.changes().getStartPageToken()` and `service.changes().list(pageToken=...)`.

- [ ] **Step 1: Add `ChangesPage` dataclass and ABC methods**

In `apps/opps/drive_client.py`, after the `FileContent` dataclass:

```python
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
```

In the `DriveClient` ABC class, add (after `trash_folder`):

```python
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
```

- [ ] **Step 2: Implement on `GoogleDriveClient`**

After the existing `trash_folder` implementation in `GoogleDriveClient`:

```python
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
                }
                if drive_id:
                    kwargs["driveId"] = drive_id
                    kwargs["includeItemsFromAllDrives"] = True
                    kwargs["spaces"] = "drive"
                else:
                    kwargs["spaces"] = "drive"
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
            if status == 410:
                return ChangesPage(
                    changed_file_ids=set(), next_page_token="", expired=True,
                )
            raise
```

- [ ] **Step 3: Run the existing drive client tests to make sure nothing regressed**

Run: `pytest apps/opps/tests/test_drive_client.py apps/opps/tests/test_drive_client_writes.py -v`
Expected: PASS (existing tests still green; abstract methods don't break instantiation because no test instantiates `DriveClient` directly).

- [ ] **Step 4: Commit**

```bash
git add apps/opps/drive_client.py
git commit -m "feat(opps): add Drive Changes API surface to DriveClient ABC

Adds get_changes_start_page_token() and list_changes() to the ABC, with
real implementations on GoogleDriveClient that drain pagination and
surface 410 Gone via ChangesPage.expired so callers can re-seed."
```

---

## Task 2: Implement Changes API on `FakeDriveClient`

**Files:**
- Modify: `apps/opps/tests/fixtures/fake_drive.py`
- Test: `apps/opps/tests/test_fake_drive_changes.py` (new)

The fake needs to record mutations (create/update/delete) and surface them on `list_changes`. We use a monotonic mutation log so each call returns only changes since the input token.

- [ ] **Step 1: Write the failing test**

Create `apps/opps/tests/test_fake_drive_changes.py`:

```python
"""Tests for FakeDriveClient's changes-feed implementation."""
from __future__ import annotations

import pytest

from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


@pytest.fixture
def client() -> FakeDriveClient:
    return FakeDriveClient.from_tree({
        "ACE": {
            "alpha": {
                "state.yaml": "current_step: a\n",
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
    state_id = client.file_id("ACE/alpha/state.yaml")
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
    state_id = client.file_id("ACE/alpha/state.yaml")
    tok = client.get_changes_start_page_token()
    # Trash the parent folder; the fake should record the delete of children.
    alpha_id = client.folder_id("ACE/alpha")
    client.trash_folder(alpha_id)

    page = client.list_changes(tok)
    assert state_id in page.changed_file_ids
```

- [ ] **Step 2: Run the test — expect FAIL**

Run: `pytest apps/opps/tests/test_fake_drive_changes.py -v`
Expected: FAIL with `AttributeError` or `TypeError` — the abstract methods aren't implemented on `FakeDriveClient` yet.

- [ ] **Step 3: Implement Changes feed on `FakeDriveClient`**

In `apps/opps/tests/fixtures/fake_drive.py`:

Add this import near the top:

```python
from apps.opps.drive_client import DriveClient, DriveFile, FileContent, ChangesPage
```

Add a mutation log to `__init__`:

```python
    def __init__(self):
        self._root = _Node(id="fake-root", name="", parent_id=None, mime_type=self.FOLDER_MIME)
        self._nodes_by_id: dict[str, _Node] = {"fake-root": self._root}
        self._counter = count(1)
        # Append-only log of (sequence, file_id) pairs. `_seq` is the next
        # sequence to assign; tokens are decimal strings of these sequences.
        self._mutation_log: list[tuple[int, str]] = []
        self._seq = count(1)
```

Add a helper `_record(file_id)` that appends to the log:

```python
    def _record_mutation(self, file_id: str) -> None:
        self._mutation_log.append((next(self._seq), file_id))
```

Wire `_record_mutation` into mutating methods. After:
- the file is added to `parent.children` in `upload_file`, call `self._record_mutation(nid)`.
- `update_file` mutates `node.body` — call `self._record_mutation(file_id)`.
- `copy_file` adds `node` — call `self._record_mutation(nid)`.
- `create_folder` — call `self._record_mutation(nid)`.
- `trash_folder` — call `self._record_mutation(...)` for the trashed folder AND every descendant id before dropping them. Easiest: in the inner `_drop` walk, record each `n.id` before popping.

Add the API methods (after `trash_folder`):

```python
    # --- Changes feed (for cache invalidation; matches DriveClient ABC) ---

    def get_changes_start_page_token(self, drive_id: str | None = None) -> str:
        # Return the *next* sequence as the starting point — i.e., a token
        # that says "consider only mutations after this one."
        # We peek without advancing the counter so observers race-free.
        return str(self._peek_seq())

    def list_changes(
        self, page_token: str, *, drive_id: str | None = None
    ) -> ChangesPage:
        try:
            since = int(page_token)
        except ValueError:
            return ChangesPage(set(), str(self._peek_seq()), expired=False)
        changed: set[str] = set()
        max_seen = since
        for seq, fid in self._mutation_log:
            if seq >= since:
                changed.add(fid)
                max_seen = max(max_seen, seq)
        return ChangesPage(
            changed_file_ids=changed,
            next_page_token=str(max_seen + 1),
            expired=False,
        )

    def _peek_seq(self) -> int:
        # `count` doesn't expose its current value; use the log's max + 1
        # if any entries exist, else 1 (the first value the counter would emit).
        if not self._mutation_log:
            return 1
        return self._mutation_log[-1][0] + 1
```

Note: `trash_folder`'s `_drop` recursive function should record mutations:

```python
    def trash_folder(self, folder_id: str) -> None:
        node = self._nodes_by_id.get(folder_id)
        if node is None or node.parent_id is None:
            return
        parent = self._nodes_by_id[node.parent_id]
        parent.children.pop(node.name, None)
        def _drop(n):
            self._record_mutation(n.id)
            for child in list(n.children.values()):
                _drop(child)
            self._nodes_by_id.pop(n.id, None)
        _drop(node)
```

- [ ] **Step 4: Run the test — expect PASS**

Run: `pytest apps/opps/tests/test_fake_drive_changes.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full opps test suite to confirm no regressions**

Run: `pytest apps/opps/tests/ -v`
Expected: All previously-passing tests still pass. The new tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/tests/fixtures/fake_drive.py apps/opps/tests/test_fake_drive_changes.py
git commit -m "test(opps): implement Changes API on FakeDriveClient

Adds an append-only mutation log to the fake so list_changes() can
return only the file_ids that changed since a given pageToken. Mirrors
the real Drive API's semantics for create / update / copy / delete."
```

---

## Task 3: Build `apps/opps/drive_changes.py` (observe function)

**Files:**
- Create: `apps/opps/drive_changes.py`
- Test: `apps/opps/tests/test_drive_changes.py`
- Modify: `apps/opps/snapshot_cache.py` (only the `clear_workspace` signature is referenced — full impl in Task 4)

`observe(workspace, client)` is the single entry point views call. It reads the workspace's pageToken from Redis, calls `list_changes`, writes back the new token, returns the changed file_ids. On 410 it re-seeds and returns `set()` (caller treats as "no changes" for THIS request; next call observes from the new token).

We need to know the workspace's `drive_id` (for shared-drive scoping) — stored in a separate Redis key, lazily resolved on first call by reading `client.get_file(workspace.drive_root_folder_id)` and extracting the `driveId` field. **However, the current `DriveFile` dataclass does not expose `driveId`** — for the fake-driven test path we don't need it (the fake ignores `drive_id` arg). For the real Google path we'll extend `DriveFile` and `_to_drive_file` in a follow-up step within this task.

- [ ] **Step 1: Write the failing test**

Create `apps/opps/tests/test_drive_changes.py`:

```python
"""Tests for apps.opps.drive_changes.observe()."""
from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.opps.drive_changes import observe
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


pytestmark = pytest.mark.django_db


class _StubWorkspace:
    """Minimal stand-in — observe() only reads .id and .drive_root_folder_id."""
    def __init__(self, id: int, drive_root_folder_id: str):
        self.id = id
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
            "alpha": {"state.yaml": "step: a\n"},
            "beta": {"state.yaml": "step: a\n"},
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
    state_id = client.file_id("ACE/alpha/state.yaml")
    client.update_file(state_id, "step: b\n", "application/x-yaml")

    changed = observe(workspace, client)
    assert state_id in changed


def test_each_change_reported_exactly_once(workspace, client):
    observe(workspace, client)
    state_id = client.file_id("ACE/alpha/state.yaml")
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

    def _list_changes(token, *, drive_id=None):
        calls.append(token)
        return ChangesPage(set(), "", expired=True)

    def _start(drive_id=None):
        return "fresh-token"

    monkeypatch.setattr(client, "list_changes", _list_changes)
    monkeypatch.setattr(client, "get_changes_start_page_token", _start)

    assert observe(workspace, client) == set()
    # Subsequent observe should now use the fresh token, not the old one.
    assert observe(workspace, client) == set()
```

- [ ] **Step 2: Run the test — expect FAIL**

Run: `pytest apps/opps/tests/test_drive_changes.py -v`
Expected: FAIL — `apps.opps.drive_changes` does not exist.

- [ ] **Step 3: Implement `apps/opps/drive_changes.py`**

Create `apps/opps/drive_changes.py`:

```python
"""Drive Changes API observer for cache invalidation.

`observe(workspace, client)` returns the set of file_ids that changed in
the workspace's drive since the last call. Each unique change is reported
exactly once across all worker processes via a Redis-stored pageToken.

This is the single source of truth for "did anything change in Drive?".
Views call it once per request and use the returned file_ids to invalidate
matching snapshot-cache keys via apps.opps.snapshot_cache.invalidate.

Failure modes:
  - Drive API raises: log WARNING, return set() (caller serves cached).
  - Drive returns 410 Gone (token expired): re-seed via
    get_changes_start_page_token, clear the workspace's snapshot cache,
    return set() for THIS call. The next call observes from the new token.
"""
from __future__ import annotations

import logging

from django.core.cache import cache

from apps.opps.drive_client import DriveClient

log = logging.getLogger(__name__)

_KEY_VERSION = "v1"


def _token_key(workspace_id: int) -> str:
    return f"drive:changes:{_KEY_VERSION}:token:ws:{workspace_id}"


def _drive_id_key(workspace_id: int) -> str:
    return f"drive:changes:{_KEY_VERSION}:driveid:ws:{workspace_id}"


def _resolve_drive_id(workspace, client: DriveClient) -> str | None:
    """Resolve the workspace's containing shared-drive id (or None for My Drive).

    Cached in Redis so we don't pay a `files.get` on every observe(). The
    cache survives forever because the answer doesn't change for a given
    folder id.
    """
    key = _drive_id_key(workspace.id)
    sentinel = object()
    cached = cache.get(key, sentinel)
    if cached is not sentinel:
        return cached or None  # "" sentinel for "we resolved it as My Drive"
    try:
        f = client.get_file(workspace.drive_root_folder_id)
        # `drive_id` is a future field on DriveFile (see `Step 4` below) —
        # for now, getattr fallback so this works pre-extension.
        drive_id = getattr(f, "drive_id", None) or None
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "drive_changes: failed to resolve drive_id for workspace %s: %s",
            workspace.id, exc,
        )
        return None
    cache.set(key, drive_id or "", timeout=None)
    return drive_id


def observe(workspace, client: DriveClient) -> set[str]:
    """Return the set of file_ids changed in `workspace`'s drive since the last call.

    First call (no token in Redis): seed the token, return set() (treat as
    "no changes yet, all caches are valid"). On Drive failure: log WARNING,
    return set(). On 410 Gone: re-seed, clear the workspace's snapshot cache
    via snapshot_cache.clear_workspace, return set().
    """
    from apps.opps import snapshot_cache  # noqa: PLC0415  (avoid circular import)

    token_key = _token_key(workspace.id)
    drive_id = _resolve_drive_id(workspace, client)

    token = cache.get(token_key)
    if not token:
        # First call: seed and return empty.
        try:
            new_token = client.get_changes_start_page_token(drive_id=drive_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "drive_changes: failed to seed start page token for ws=%s: %s",
                workspace.id, exc,
            )
            return set()
        cache.set(token_key, new_token, timeout=None)
        return set()

    try:
        page = client.list_changes(token, drive_id=drive_id)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "drive_changes: list_changes failed for ws=%s: %s",
            workspace.id, exc,
        )
        return set()

    if page.expired:
        log.info(
            "drive_changes: pageToken expired for ws=%s; re-seeding",
            workspace.id,
        )
        try:
            new_token = client.get_changes_start_page_token(drive_id=drive_id)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "drive_changes: failed to re-seed for ws=%s after 410: %s",
                workspace.id, exc,
            )
            cache.delete(token_key)
            return set()
        cache.set(token_key, new_token, timeout=None)
        snapshot_cache.clear_workspace(workspace.id)
        return set()

    if page.next_page_token:
        cache.set(token_key, page.next_page_token, timeout=None)
    return page.changed_file_ids
```

Note: `observe` calls `snapshot_cache.clear_workspace`. We need a stub for that now so the import works. Continue to Step 4.

- [ ] **Step 4: Add a minimal `clear_workspace` stub**

Create `apps/opps/snapshot_cache.py` with just enough to satisfy the import:

```python
"""Long-lived OppSnapshot / OppCard cache.

Full implementation lands in the next task. This stub exposes
`clear_workspace` so apps.opps.drive_changes can call it during 410
re-seed.
"""
from __future__ import annotations


def clear_workspace(workspace_id: int) -> None:
    """No-op until snapshot caching is wired in (Task 4)."""
    return None
```

- [ ] **Step 5: Run the test — expect PASS**

Run: `pytest apps/opps/tests/test_drive_changes.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Add `drive_id` to `DriveFile` and the Google `_to_drive_file`**

In `apps/opps/drive_client.py`, the `DriveFile` dataclass:

```python
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
```

In `GoogleDriveClient._to_drive_file`, add `drive_id` to the field selection.

Find the `fields=` string in `_list_folder`:

```python
                fields=(
                    "nextPageToken, "
                    "files(id, name, mimeType, webViewLink, size, modifiedTime)"
                ),
```

Change to:

```python
                fields=(
                    "nextPageToken, "
                    "files(id, name, mimeType, webViewLink, size, modifiedTime, driveId)"
                ),
```

In the `_to_drive_file` `@staticmethod`, surface `driveId`:

```python
    @staticmethod
    def _to_drive_file(f: dict, path: str) -> DriveFile:
        return DriveFile(
            id=f["id"],
            name=f["name"],
            mime_type=f["mimeType"],
            web_view_link=f.get("webViewLink", ""),
            path=path,
            size_bytes=int(f["size"]) if "size" in f else None,
            modified_time=f.get("modifiedTime"),
            drive_id=f.get("driveId") or None,
        )
```

Find `get_file` in `GoogleDriveClient` and add `driveId` to its `fields` arg the same way.

- [ ] **Step 7: Run all opps tests — confirm nothing regressed**

Run: `pytest apps/opps/tests/ -v`
Expected: PASS (all previously-passing tests still pass; new test_drive_changes tests pass).

- [ ] **Step 8: Commit**

```bash
git add apps/opps/drive_changes.py apps/opps/snapshot_cache.py apps/opps/drive_client.py apps/opps/tests/test_drive_changes.py
git commit -m "feat(opps): add Drive Changes API observer for cache invalidation

apps/opps/drive_changes.observe(workspace, client) returns the set of
file_ids that changed in a workspace's drive since the last call.
pageToken is stored per-workspace in Redis; first call seeds and returns
empty. 410 Gone re-seeds + clears the workspace snapshot cache. Drive
errors degrade to set() (callers serve cached).

Includes a clear_workspace() stub in snapshot_cache.py so the cross-module
call resolves; full snapshot cache lands next."
```

---

## Task 4: Build `apps/opps/snapshot_cache.py` (full implementation)

**Files:**
- Modify: `apps/opps/snapshot_cache.py` (replacing the Task 3 stub)
- Test: `apps/opps/tests/test_snapshot_cache.py`

The cache stores assembled `OppSnapshot` and `OppCard` Python objects in the Django cache (Redis-backed in dev/prod, locmem in tests). Each cache entry tracks its file_ids both inline (in the value) and via a reverse index (`file_id → set[cache_key]`). Invalidation: union the reverse-index sets for the changed file_ids and `DEL` those keys.

Fingerprint: SHA-256 over sorted `(file_id, modified_time)` tuples. Stable, content-addressed. Used as ETag.

- [ ] **Step 1: Write the failing test**

Create `apps/opps/tests/test_snapshot_cache.py`:

```python
"""Tests for apps.opps.snapshot_cache."""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from django.core.cache import cache

from apps.opps import snapshot_cache


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _flush_cache():
    cache.clear()
    yield
    cache.clear()


@dataclass
class _MockSnapshot:
    """Stands in for OppSnapshot — only needs to be picklable + dataclass."""
    slug: str
    payload: str
    files: list[tuple[str, str]]  # (file_id, modified_time)


def _files(*pairs: tuple[str, str]) -> list[tuple[str, str]]:
    return list(pairs)


def test_get_returns_none_when_unset():
    assert snapshot_cache.get(workspace_id=1, slug="alpha", run_id=None) is None


def test_set_then_get_round_trip():
    snap = _MockSnapshot("alpha", "p", _files(("f1", "2026-01-01")))
    snapshot_cache.set(
        workspace_id=1, slug="alpha", run_id="r1", snap=snap,
        file_ids={"f1"},
    )
    got = snapshot_cache.get(workspace_id=1, slug="alpha", run_id="r1")
    assert got == snap


def test_invalidate_drops_matching_snapshot():
    snap = _MockSnapshot("alpha", "p", _files(("f1", "t1")))
    snapshot_cache.set(1, "alpha", "r1", snap, file_ids={"f1", "f2"})

    snapshot_cache.invalidate({"f2"})
    assert snapshot_cache.get(1, "alpha", "r1") is None


def test_invalidate_only_drops_intersecting_keys():
    snap_a = _MockSnapshot("alpha", "a", _files(("f1", "t1")))
    snap_b = _MockSnapshot("beta", "b", _files(("f3", "t3")))
    snapshot_cache.set(1, "alpha", "r1", snap_a, file_ids={"f1", "f2"})
    snapshot_cache.set(1, "beta", "r1", snap_b, file_ids={"f3"})

    snapshot_cache.invalidate({"f2"})
    assert snapshot_cache.get(1, "alpha", "r1") is None
    assert snapshot_cache.get(1, "beta", "r1") == snap_b


def test_invalidate_unrelated_file_id_is_noop():
    snap = _MockSnapshot("alpha", "p", _files())
    snapshot_cache.set(1, "alpha", "r1", snap, file_ids={"f1"})

    snapshot_cache.invalidate({"unknown-file"})
    assert snapshot_cache.get(1, "alpha", "r1") == snap


def test_card_get_set_round_trip():
    @dataclass
    class _MockCard:
        slug: str

    c = _MockCard("alpha")
    snapshot_cache.set_card(1, "alpha", c, file_ids={"fc1"})
    assert snapshot_cache.get_card(1, "alpha") == c

    snapshot_cache.invalidate({"fc1"})
    assert snapshot_cache.get_card(1, "alpha") is None


def test_clear_workspace_drops_all_keys_for_that_workspace():
    snap_a = _MockSnapshot("alpha", "a", _files())
    snap_b = _MockSnapshot("beta", "b", _files())
    snapshot_cache.set(1, "alpha", "r1", snap_a, file_ids={"f1"})
    snapshot_cache.set(1, "beta", "r1", snap_b, file_ids={"f2"})
    snapshot_cache.set(2, "gamma", "r1", snap_a, file_ids={"f3"})

    snapshot_cache.clear_workspace(1)
    assert snapshot_cache.get(1, "alpha", "r1") is None
    assert snapshot_cache.get(1, "beta", "r1") is None
    assert snapshot_cache.get(2, "gamma", "r1") == snap_a


def test_fingerprint_is_stable():
    snap = _MockSnapshot("alpha", "p", _files(("f1", "t1"), ("f2", "t2")))
    fp1 = snapshot_cache.fingerprint([("f1", "t1"), ("f2", "t2")])
    fp2 = snapshot_cache.fingerprint([("f2", "t2"), ("f1", "t1")])  # different order
    assert fp1 == fp2  # sorted internally


def test_fingerprint_changes_when_modified_time_changes():
    fp1 = snapshot_cache.fingerprint([("f1", "t1")])
    fp2 = snapshot_cache.fingerprint([("f1", "t2")])
    assert fp1 != fp2


def test_invalidate_falls_back_when_reverse_index_missing():
    """If the reverse index is gone (Redis eviction), invalidation falls
    back to the inline file_ids stored on each snapshot value."""
    snap = _MockSnapshot("alpha", "p", _files())
    snapshot_cache.set(1, "alpha", "r1", snap, file_ids={"f1"})

    # Simulate reverse-index loss.
    cache.delete("opp:idx:f1")

    snapshot_cache.invalidate({"f1"})
    assert snapshot_cache.get(1, "alpha", "r1") is None
```

- [ ] **Step 2: Run the test — expect FAIL**

Run: `pytest apps/opps/tests/test_snapshot_cache.py -v`
Expected: FAIL — most functions don't exist yet.

- [ ] **Step 3: Implement the full snapshot cache**

Replace the contents of `apps/opps/snapshot_cache.py`:

```python
"""Long-lived OppSnapshot / OppCard cache, invalidated by Drive file_ids.

Storage layout (all in the Django cache, Redis-backed in prod):

  opp:snap:<workspace_id>:<slug>:<run_id|->        -> dict envelope
  opp:card:<workspace_id>:<slug>                   -> dict envelope
  opp:idx:<file_id>                                -> set[str] of cache keys
  opp:ws:<workspace_id>                            -> set[str] of cache keys

Each snapshot/card envelope is `{"value": <pickled object>, "file_ids":
<set>}`. Storing the file_ids inline gives a fallback when the reverse
index entry is missing (Redis eviction or cold-start mid-session) — we
SCAN the workspace key set, decode each envelope, and invalidate by
intersection.

Fingerprint:
  fingerprint(seq_of_(file_id, modified_time)) -> "sha256:<hex>"

Returned to clients as an ETag header. Stable across the same set of
(file_id, modified_time) pairs regardless of input order.
"""
from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from typing import Any

from django.core.cache import cache

log = logging.getLogger(__name__)

_KEY_VERSION = "v1"


def _snap_key(workspace_id: int, slug: str, run_id: str | None) -> str:
    rid = run_id or "-"
    return f"opp:snap:{_KEY_VERSION}:{workspace_id}:{slug}:{rid}"


def _card_key(workspace_id: int, slug: str) -> str:
    return f"opp:card:{_KEY_VERSION}:{workspace_id}:{slug}"


def _idx_key(file_id: str) -> str:
    return f"opp:idx:{_KEY_VERSION}:{file_id}"


def _ws_key(workspace_id: int) -> str:
    return f"opp:ws:{_KEY_VERSION}:{workspace_id}"


def _add_to_set(cache_key: str, member: str) -> None:
    """Append `member` to a set stored under `cache_key`. Works on any
    Django cache backend (Redis, locmem) by reading-modifying-writing.
    Not strictly atomic — acceptable here because a missed write only
    means we fall back to the inline-file_ids scan path.
    """
    members: set[str] = cache.get(cache_key) or set()
    if not isinstance(members, set):
        members = set(members)
    if member in members:
        return
    members.add(member)
    cache.set(cache_key, members, timeout=None)


def _remove_from_set(cache_key: str, member: str) -> None:
    members: set[str] = cache.get(cache_key) or set()
    if not isinstance(members, set):
        members = set(members)
    members.discard(member)
    if members:
        cache.set(cache_key, members, timeout=None)
    else:
        cache.delete(cache_key)


def get(workspace_id: int, slug: str, run_id: str | None) -> Any | None:
    env = cache.get(_snap_key(workspace_id, slug, run_id))
    if not env:
        return None
    return env.get("value")


def set(  # noqa: A001  (shadows builtin; namespace via module is fine)
    *,
    workspace_id: int,
    slug: str,
    run_id: str | None,
    snap: Any,
    file_ids: set[str],
) -> None:
    key = _snap_key(workspace_id, slug, run_id)
    cache.set(key, {"value": snap, "file_ids": set(file_ids)}, timeout=None)
    for fid in file_ids:
        _add_to_set(_idx_key(fid), key)
    _add_to_set(_ws_key(workspace_id), key)


def get_card(workspace_id: int, slug: str) -> Any | None:
    env = cache.get(_card_key(workspace_id, slug))
    if not env:
        return None
    return env.get("value")


def set_card(
    *, workspace_id: int, slug: str, card: Any, file_ids: set[str],
) -> None:
    key = _card_key(workspace_id, slug)
    cache.set(key, {"value": card, "file_ids": set(file_ids)}, timeout=None)
    for fid in file_ids:
        _add_to_set(_idx_key(fid), key)
    _add_to_set(_ws_key(workspace_id), key)


def invalidate(file_ids: Iterable[str]) -> None:
    """Drop every snapshot/card whose file_ids intersect the input."""
    file_ids = set(file_ids)
    if not file_ids:
        return
    keys_to_drop: set[str] = set()

    # Fast path: reverse index.
    for fid in file_ids:
        members = cache.get(_idx_key(fid))
        if members:
            keys_to_drop.update(members)

    # Fallback: SCAN every cached workspace's known keys for an inline
    # file_id intersection. Bounded by N opps per workspace.
    if not keys_to_drop:
        # Without a reverse index, we don't know which workspace(s) to
        # scan. Walk every workspace whose key-set we know about.
        # Cheap-ish in practice (single-digit workspaces in dev/prod).
        for ws_key in _all_workspace_keys():
            for key in cache.get(ws_key) or set():
                env = cache.get(key)
                if env and file_ids.intersection(env.get("file_ids") or set()):
                    keys_to_drop.add(key)

    if keys_to_drop:
        cache.delete_many(keys_to_drop)
        # Clean up reverse-index entries for the dropped keys.
        for fid in file_ids:
            _remove_set_entries(_idx_key(fid), keys_to_drop)


def clear_workspace(workspace_id: int) -> None:
    """Drop every cached snapshot/card for the workspace."""
    ws_key = _ws_key(workspace_id)
    keys = cache.get(ws_key) or set()
    if keys:
        cache.delete_many(keys)
    cache.delete(ws_key)


def fingerprint(file_id_modtime_pairs: Iterable[tuple[str, str | None]]) -> str:
    """Stable SHA-256 over sorted (file_id, modified_time) pairs.

    Returned as `sha256:<hex>` for use as an HTTP ETag.
    """
    h = hashlib.sha256()
    for fid, mt in sorted((fid, mt or "") for fid, mt in file_id_modtime_pairs):
        h.update(fid.encode("utf-8"))
        h.update(b"\x00")
        h.update(mt.encode("utf-8"))
        h.update(b"\x00")
    return f"sha256:{h.hexdigest()}"


# --- internals ---


def _all_workspace_keys() -> list[str]:
    """Best-effort enumeration of known workspace key-sets.

    Django's cache API doesn't expose key scanning, so we don't attempt a
    real glob; we just check known low-numbered workspace ids. In practice
    workspaces are sparse and small; we cap the scan at 1024 to keep the
    fallback bounded.
    """
    return [_ws_key(i) for i in range(1, 1024)]


def _remove_set_entries(cache_key: str, members_to_remove: set[str]) -> None:
    members: set[str] = cache.get(cache_key) or set()
    if not isinstance(members, set):
        members = set(members)
    members.difference_update(members_to_remove)
    if members:
        cache.set(cache_key, members, timeout=None)
    else:
        cache.delete(cache_key)
```

- [ ] **Step 4: Run the test — expect PASS**

Run: `pytest apps/opps/tests/test_snapshot_cache.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Run the full opps test suite**

Run: `pytest apps/opps/tests/ -v`
Expected: All passing.

- [ ] **Step 6: Commit**

```bash
git add apps/opps/snapshot_cache.py apps/opps/tests/test_snapshot_cache.py
git commit -m "feat(opps): add long-lived snapshot cache with file-id reverse index

apps/opps/snapshot_cache provides get/set/invalidate for OppSnapshot and
OppCard, keyed on (workspace, slug, run_id). Each entry tracks its
file_ids both inline and via a reverse index for surgical invalidation
when Drive Changes reports a mutation. Fingerprint helper computes a
stable SHA-256 over (file_id, modified_time) for use as an HTTP ETag."
```

---

## Task 5: Add `_TouchedFileTracker` for the cold-load path

**Files:**
- Create: `apps/opps/touched_tracker.py`
- Test: `apps/opps/tests/test_touched_tracker.py`
- Modify: `apps/opps/drive_cache.py` (record into the tracker on read methods)

When `load_opp` walks Drive, we need to capture every `(file_id, modified_time)` it encountered so the cache write knows which file_ids to record in the reverse index. We do this with a contextvar-driven tracker that hooks into `CachedDriveClient`'s read methods. Why `CachedDriveClient`: every cold-path read in `load_opp` already goes through it, so one hook covers `list_files`, `get_file`, and `get_content`.

- [ ] **Step 1: Write the failing test**

Create `apps/opps/tests/test_touched_tracker.py`:

```python
"""Tests for apps.opps.touched_tracker."""
from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.opps.drive_cache import CachedDriveClient
from apps.opps.touched_tracker import TouchedFileTracker, current_tracker
from apps.opps.tests.fixtures.fake_drive import FakeDriveClient


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _flush_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def client() -> CachedDriveClient:
    inner = FakeDriveClient.from_tree({
        "ACE": {
            "alpha": {
                "state.yaml": "step: a\n",
                "idea.md": "alpha idea",
            }
        }
    })
    return CachedDriveClient(inner)


def test_no_tracker_active_means_no_recording(client):
    assert current_tracker() is None
    client.list_files(client._inner.folder_id("ACE/alpha"))
    # Nothing to assert — just confirm no exception.


def test_list_files_records_visited_file_ids(client):
    alpha_id = client._inner.folder_id("ACE/alpha")
    state_id = client._inner.file_id("ACE/alpha/state.yaml")
    idea_id = client._inner.file_id("ACE/alpha/idea.md")

    with TouchedFileTracker() as tracker:
        client.list_files(alpha_id)

    assert state_id in tracker.file_ids
    assert idea_id in tracker.file_ids


def test_get_content_records_file_id(client):
    state_id = client._inner.file_id("ACE/alpha/state.yaml")
    with TouchedFileTracker() as tracker:
        client.get_content(state_id, "application/x-yaml")
    assert state_id in tracker.file_ids


def test_pairs_records_modified_time(client):
    """The tracker yields (file_id, modified_time) pairs for fingerprinting."""
    client._inner.set_modified_time("ACE/alpha/state.yaml", "2026-05-08T12:00:00Z")
    state_id = client._inner.file_id("ACE/alpha/state.yaml")

    with TouchedFileTracker() as tracker:
        client.list_files(client._inner.folder_id("ACE/alpha"))

    pairs = dict(tracker.pairs())
    assert pairs[state_id] == "2026-05-08T12:00:00Z"


def test_nested_with_blocks_track_independently(client):
    alpha_id = client._inner.folder_id("ACE/alpha")
    with TouchedFileTracker() as outer:
        client.list_files(alpha_id)
        outer_count = len(outer.file_ids)
        with TouchedFileTracker() as inner:
            client.list_files(alpha_id)
        assert inner.file_ids == outer.file_ids
    # outer didn't double-count its work
    assert len(outer.file_ids) == outer_count
```

- [ ] **Step 2: Run the test — expect FAIL**

Run: `pytest apps/opps/tests/test_touched_tracker.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `apps/opps/touched_tracker.py`**

```python
"""Per-request tracker for file_ids visited during a Drive walk.

Used by views.workbench / _opp_list_impl to capture which file_ids the
cold-path `load_opp` / `load_opp_card` touched, so the snapshot cache
can populate its reverse index correctly.

Activation is via a contextvar so nested code in `load_opp` doesn't have
to thread a parameter through. CachedDriveClient.list_files /
.get_file / .get_content check `current_tracker()` and record into it
when one is active; outside a `with` block the cost is one contextvar
read.
"""
from __future__ import annotations

from contextvars import ContextVar


_current: ContextVar["TouchedFileTracker | None"] = ContextVar(
    "ace_touched_file_tracker", default=None,
)


def current_tracker() -> "TouchedFileTracker | None":
    return _current.get()


class TouchedFileTracker:
    """Context manager. Inside the `with` block, every Drive read through
    CachedDriveClient records the visited (file_id, modified_time) pair.
    """
    def __init__(self) -> None:
        self.file_ids: set[str] = set()
        self._mod_times: dict[str, str | None] = {}
        self._token = None

    def record(self, file_id: str, modified_time: str | None = None) -> None:
        self.file_ids.add(file_id)
        # Don't overwrite a non-empty modified_time with None; the first
        # source-of-truth wins.
        if modified_time is not None:
            self._mod_times[file_id] = modified_time
        elif file_id not in self._mod_times:
            self._mod_times[file_id] = None

    def pairs(self) -> list[tuple[str, str | None]]:
        return [(fid, self._mod_times.get(fid)) for fid in self.file_ids]

    def __enter__(self) -> "TouchedFileTracker":
        self._token = _current.set(self)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            _current.reset(self._token)
            self._token = None
```

- [ ] **Step 4: Wire the tracker into `CachedDriveClient`**

In `apps/opps/drive_cache.py`, import the tracker:

```python
from apps.opps.touched_tracker import current_tracker
```

In `list_files`, after the `result = ...` line, BEFORE the `cache.set(...)`:

```python
        result = self._inner.list_files(folder_id, recursive=recursive, page_size=page_size)
        cache.set(key, result, timeout=self._ttl)
        tracker = current_tracker()
        if tracker is not None:
            for f in result:
                tracker.record(f.id, f.modified_time)
        return result
```

Also wire on the cache-hit branch above the `return hit`:

```python
        if not self._bypass:
            hit = cache.get(key)
            if hit is not None:
                tracker = current_tracker()
                if tracker is not None:
                    for f in hit:
                        tracker.record(f.id, f.modified_time)
                return hit
```

In `get_file`, both miss and hit paths similarly:

```python
    def get_file(self, file_id: str) -> DriveFile:
        key = _file_meta_key(file_id)
        if not self._bypass:
            hit = cache.get(key)
            if hit is not None:
                tracker = current_tracker()
                if tracker is not None:
                    tracker.record(hit.id, hit.modified_time)
                return hit
        result = self._inner.get_file(file_id)
        cache.set(key, result, timeout=self._ttl)
        tracker = current_tracker()
        if tracker is not None:
            tracker.record(result.id, result.modified_time)
        return result
```

In `get_content`, record by file_id (no modified_time available in the FileContent — already captured via list_files):

```python
    def get_content(self, file_id: str, mime_type: str) -> FileContent:
        key = _content_key(file_id, mime_type)
        if not self._bypass:
            hit = cache.get(key)
            if hit is not None:
                tracker = current_tracker()
                if tracker is not None:
                    tracker.record(file_id)
                return hit
        result = self._inner.get_content(file_id, mime_type)
        cache.set(key, result, timeout=self._ttl)
        tracker = current_tracker()
        if tracker is not None:
            tracker.record(file_id)
        return result
```

- [ ] **Step 5: Run the test — expect PASS**

Run: `pytest apps/opps/tests/test_touched_tracker.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the full opps suite to confirm CachedDriveClient changes are non-breaking**

Run: `pytest apps/opps/tests/ -v`
Expected: All previously-passing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add apps/opps/touched_tracker.py apps/opps/drive_cache.py apps/opps/tests/test_touched_tracker.py
git commit -m "feat(opps): add TouchedFileTracker for cache reverse-index population

CachedDriveClient's read methods now record (file_id, modified_time)
pairs into a contextvar-driven tracker when one is active. Views wrap
load_opp / load_opp_card calls in `with TouchedFileTracker() as t:` and
pass t.file_ids to snapshot_cache.set so the reverse index sees every
file the load actually depends on."
```

---

## Task 6: Add `OPPS_USE_CHANGES_API` settings flag

**Files:**
- Modify: `config/settings/base.py`

The flag defaults `False` so the rest of the work can land safely. Production rollout (Task 11) flips it on.

- [ ] **Step 1: Add the flag**

In `config/settings/base.py`, near the existing `OPPS_DRIVE_CACHE_SECONDS` line, add:

```python
# Phase out the 30-second TTL Drive cache in favour of a Drive-Changes-API
# driven snapshot cache. See docs/specs/2026-05-08-opp-cache-redesign.md.
# When False (default), views.workbench / _opp_list_impl behave as before
# — relying on the per-call CachedDriveClient TTL.
# When True, requests:
#   1. Call drive_changes.observe to learn which file_ids changed in this
#      workspace's drive since the last poll.
#   2. Invalidate matching keys in apps.opps.snapshot_cache.
#   3. Serve the cached OppSnapshot / OppCard if still valid (with ETag
#      304 responses when the client's If-None-Match matches).
#   4. Otherwise re-walk Drive once and cache the result with no TTL.
OPPS_USE_CHANGES_API = env.bool("OPPS_USE_CHANGES_API", default=False)
```

- [ ] **Step 2: Verify the setting loads**

Run:
```bash
DJANGO_SECRET_KEY=test DATABASE_URL=sqlite:///tmp/x.db DJANGO_ALLOWED_HOSTS=localhost \
python -c "from django.conf import settings; import django; django.setup(); print(settings.OPPS_USE_CHANGES_API)" \
  --settings=config.settings.base 2>&1 | tail -5
```

Expected: `False`.

- [ ] **Step 3: Commit**

```bash
git add config/settings/base.py
git commit -m "config: add OPPS_USE_CHANGES_API flag (default False)

Gates the new Drive Changes-API + snapshot cache wiring. Lets us land
view changes safely with the old behaviour preserved by default."
```

---

## Task 7: Wire `workbench` view to snapshot cache + ETag

**Files:**
- Modify: `apps/opps/views.py` (the `workbench` function)
- Modify: `apps/opps/tests/test_views_workbench.py`

The cache-wired path is gated on `settings.OPPS_USE_CHANGES_API`. The legacy path is preserved when False so this task ships safely.

- [ ] **Step 1: Write the failing test**

Append to `apps/opps/tests/test_views_workbench.py` (or replace if simpler — make sure existing test names don't collide):

```python
def test_workbench_returns_etag_header_when_flag_on(
    settings, authed_client, malaria_pilot_workbench_setup
):
    settings.OPPS_USE_CHANGES_API = True
    resp = authed_client.get(
        f"/api/opps/{malaria_pilot_workbench_setup.slug}",
        HTTP_X_ACE_WORKSPACE=malaria_pilot_workbench_setup.workspace.slug,
    )
    assert resp.status_code == 200
    assert resp.headers.get("ETag", "").startswith("sha256:")


def test_workbench_returns_304_when_if_none_match_matches(
    settings, authed_client, malaria_pilot_workbench_setup
):
    settings.OPPS_USE_CHANGES_API = True
    setup = malaria_pilot_workbench_setup

    first = authed_client.get(
        f"/api/opps/{setup.slug}",
        HTTP_X_ACE_WORKSPACE=setup.workspace.slug,
    )
    etag = first.headers["ETag"]

    second = authed_client.get(
        f"/api/opps/{setup.slug}",
        HTTP_X_ACE_WORKSPACE=setup.workspace.slug,
        HTTP_IF_NONE_MATCH=etag,
    )
    assert second.status_code == 304
    assert second.content == b""


def test_workbench_returns_200_after_drive_mutation(
    settings, authed_client, malaria_pilot_workbench_setup, fake_drive
):
    """Mutating state.yaml between calls invalidates the cache; second
    response is 200 with a fresh body and a different ETag."""
    settings.OPPS_USE_CHANGES_API = True
    setup = malaria_pilot_workbench_setup

    first = authed_client.get(
        f"/api/opps/{setup.slug}",
        HTTP_X_ACE_WORKSPACE=setup.workspace.slug,
    )
    etag1 = first.headers["ETag"]

    state_id = fake_drive.file_id(f"ACE/{setup.slug}/state.yaml")
    fake_drive.update_file(
        state_id, "current_step: ocs-agent-setup\n", "application/x-yaml",
    )

    second = authed_client.get(
        f"/api/opps/{setup.slug}",
        HTTP_X_ACE_WORKSPACE=setup.workspace.slug,
        HTTP_IF_NONE_MATCH=etag1,
    )
    assert second.status_code == 200
    assert second.headers["ETag"] != etag1


def test_workbench_force_param_bypasses_cache(
    settings, authed_client, malaria_pilot_workbench_setup
):
    settings.OPPS_USE_CHANGES_API = True
    setup = malaria_pilot_workbench_setup

    first = authed_client.get(
        f"/api/opps/{setup.slug}",
        HTTP_X_ACE_WORKSPACE=setup.workspace.slug,
    )
    etag = first.headers["ETag"]

    # Even with matching If-None-Match, ?force=1 must return a fresh 200.
    forced = authed_client.get(
        f"/api/opps/{setup.slug}?force=1",
        HTTP_X_ACE_WORKSPACE=setup.workspace.slug,
        HTTP_IF_NONE_MATCH=etag,
    )
    assert forced.status_code == 200
```

If `malaria_pilot_workbench_setup` and `fake_drive` fixtures don't exist yet in `test_views_workbench.py`'s `conftest.py`, look at the existing test file and replicate the pattern used by other workbench tests there. Most existing view tests in this codebase use a fixture that monkeypatches `apps.opps.drive_client.get_drive_client` to return a `FakeDriveClient`. Reuse that pattern.

If the existing test setup helper is named differently, look at the top of `apps/opps/tests/test_views_workbench.py`:

```bash
grep -E "def |@pytest.fixture" apps/opps/tests/test_views_workbench.py | head -20
```

Find the existing fixture name and substitute it. The test logic is the same regardless.

- [ ] **Step 2: Run the test — expect FAIL**

Run: `pytest apps/opps/tests/test_views_workbench.py -v -k "etag or 304 or force_param or after_drive_mutation"`
Expected: FAIL — view doesn't emit ETag or honour If-None-Match yet.

- [ ] **Step 3: Update `workbench` to use the snapshot cache when the flag is on**

In `apps/opps/views.py`, add the import block at the top:

```python
from apps.opps import drive_changes, snapshot_cache
from apps.opps.touched_tracker import TouchedFileTracker
from apps.opps.serializers import serialize_opp_snapshot  # (if not already imported)
```

(Note: `serialize_opp_snapshot` is already imported per the existing imports at the top of views.py — skip the duplicate.)

Replace the body of `workbench` from the `_require_drive` line through the final `return Response(success_response(serialize_opp_snapshot(snap)))`:

```python
    ws, client, err = _require_drive(request)
    if err is not None:
        return err

    ace_folder_id = _resolve_ace_root_folder_id(ws)
    if ace_folder_id is None:
        return Response(
            error_response("ACE root folder not found", code="ace-root-not-found"),
            status=404,
        )

    run_id = request.GET.get("run_id") or None
    force = request.GET.get("force") == "1"

    if not getattr(settings, "OPPS_USE_CHANGES_API", False):
        # Legacy path — preserved for the rollout window.
        try:
            snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
        except FileNotFoundError:
            return Response(
                error_response(f"no opp named {slug!r}", code="opp-not-found"),
                status=404,
            )
        _overlay_workspace_display_name(snap.opp, slug, workspace=ws)
        return Response(success_response(serialize_opp_snapshot(snap)))

    # New path: validate against Drive Changes API, serve cached if valid.
    changed = drive_changes.observe(ws, client)
    if changed:
        snapshot_cache.invalidate(changed)

    if not force:
        cached = snapshot_cache.get(ws.id, slug, run_id)
        if cached is not None:
            _overlay_workspace_display_name(cached.opp, slug, workspace=ws)
            etag = _snapshot_etag(cached)
            if request.headers.get("If-None-Match") == etag:
                return HttpResponse(status=304, headers={"ETag": etag})
            resp = Response(success_response(serialize_opp_snapshot(cached)))
            resp["ETag"] = etag
            return resp

    try:
        with TouchedFileTracker() as tracker:
            snap = load_opp(client, ace_folder_id=ace_folder_id, slug=slug, run_id=run_id)
    except FileNotFoundError:
        return Response(
            error_response(f"no opp named {slug!r}", code="opp-not-found"),
            status=404,
        )
    _overlay_workspace_display_name(snap.opp, slug, workspace=ws)
    snapshot_cache.set(
        workspace_id=ws.id, slug=slug, run_id=run_id,
        snap=snap, file_ids=tracker.file_ids,
    )
    etag = _snapshot_etag(snap, pairs=tracker.pairs())
    resp = Response(success_response(serialize_opp_snapshot(snap)))
    resp["ETag"] = etag
    return resp
```

Add a helper at module scope (just below the existing `_overlay_workspace_display_name`):

```python
def _snapshot_etag(snap, *, pairs=None) -> str:
    """Compute the ETag for an OppSnapshot.

    Prefers an explicit (file_id, modified_time) pair list when supplied
    (cold-load path — we have it free from TouchedFileTracker). For the
    cached-hit path we don't have the original pairs handy, so we
    fall back to a hash of the serialized payload — stable across
    matching snapshots.
    """
    from apps.opps import snapshot_cache as _sc

    if pairs is not None:
        return _sc.fingerprint(pairs)
    # Cached path: serialize and hash. The serialized payload is the
    # actual response body, so its hash is exactly the freshness signal
    # the frontend cares about.
    import hashlib
    import json
    body = json.dumps(serialize_opp_snapshot(snap), sort_keys=True, default=str)
    return f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"
```

Add the missing `HttpResponse` import at the top of `views.py` if it's not already there (the existing file imports `from django.http import HttpResponse` already — verify).

- [ ] **Step 4: Run the test — expect PASS**

Run: `pytest apps/opps/tests/test_views_workbench.py -v`
Expected: PASS (all existing tests still pass; new tests pass).

- [ ] **Step 5: Commit**

```bash
git add apps/opps/views.py apps/opps/tests/test_views_workbench.py
git commit -m "feat(opps): wire workbench view to snapshot cache + ETag

When OPPS_USE_CHANGES_API is on, GET /api/opps/<slug>:
  1. Polls drive.changes.list to see what file_ids changed since last call.
  2. Invalidates intersecting snapshot_cache keys.
  3. Returns 304 if If-None-Match matches the cached snapshot's ETag.
  4. Otherwise serves the cached snapshot with its ETag.
  5. On miss, walks Drive once via TouchedFileTracker, caches the result
     with the file_ids it touched, returns a fresh ETag.

?force=1 keeps working as a manual cache bypass (powers the Refresh button).
Legacy path preserved when the flag is off."
```

---

## Task 8: Wire `_opp_list_impl` to per-card cache + list ETag

**Files:**
- Modify: `apps/opps/views.py` (`_opp_list_impl`)
- Modify: `apps/opps/tests/test_views_opp_list.py`

The list builds N `OppCard`s. We cache each card individually (same `snapshot_cache.set_card` pattern) and assemble the response from cached + freshly-walked cards. The list response itself also returns an ETag (hash over the constituent card ETags) so a no-change list can be served as a 304.

- [ ] **Step 1: Write the failing test**

Append to `apps/opps/tests/test_views_opp_list.py`:

```python
def test_list_returns_etag_header_when_flag_on(
    settings, authed_client, multi_opp_setup
):
    settings.OPPS_USE_CHANGES_API = True
    resp = authed_client.get(
        "/api/opps/", HTTP_X_ACE_WORKSPACE=multi_opp_setup.workspace.slug,
    )
    assert resp.status_code == 200
    assert resp.headers.get("ETag", "").startswith("sha256:")


def test_list_returns_304_when_unchanged(
    settings, authed_client, multi_opp_setup
):
    settings.OPPS_USE_CHANGES_API = True
    first = authed_client.get(
        "/api/opps/", HTTP_X_ACE_WORKSPACE=multi_opp_setup.workspace.slug,
    )
    etag = first.headers["ETag"]
    second = authed_client.get(
        "/api/opps/", HTTP_X_ACE_WORKSPACE=multi_opp_setup.workspace.slug,
        HTTP_IF_NONE_MATCH=etag,
    )
    assert second.status_code == 304


def test_list_only_reloads_changed_card(
    settings, authed_client, multi_opp_setup, fake_drive
):
    """Mutating one opp's state.yaml only invalidates that opp's card;
    the other cards are served from the cache. We can't easily count
    Drive calls in this integration test, but the behavioural assertion
    is: the response after mutation reflects the change for that opp,
    and the other opps' display_names are still correct."""
    settings.OPPS_USE_CHANGES_API = True
    ws_slug = multi_opp_setup.workspace.slug
    target_slug = multi_opp_setup.slugs[0]

    first = authed_client.get(
        "/api/opps/", HTTP_X_ACE_WORKSPACE=ws_slug,
    )
    assert first.status_code == 200

    state_id = fake_drive.file_id(f"ACE/{target_slug}/state.yaml")
    fake_drive.update_file(
        state_id,
        "current_phase: app-building\ncurrent_step: app-build\nmode: review\n",
        "application/x-yaml",
    )

    second = authed_client.get(
        "/api/opps/", HTTP_X_ACE_WORKSPACE=ws_slug,
        HTTP_IF_NONE_MATCH=first.headers["ETag"],
    )
    assert second.status_code == 200
    payload = second.json()["data"]
    target = next(c for c in payload if c["slug"] == target_slug)
    assert target["current_step"] == "app-build"
```

If `multi_opp_setup` doesn't exist, study the top of `test_views_opp_list.py` for the existing helper used by tests like `test_list_returns_two_opps`. Reuse / extend it.

- [ ] **Step 2: Run the test — expect FAIL**

Run: `pytest apps/opps/tests/test_views_opp_list.py -v -k "etag or 304 or only_reloads"`
Expected: FAIL.

- [ ] **Step 3: Update `_opp_list_impl`**

In `apps/opps/views.py`, modify `_opp_list_impl`. Just before the `for child in root_children:` loop, refactor the per-opp block to use the card cache when the flag is on. Replace the loop body (the `try: card = load_opp_card(...)` through `cards.append({...})` block) with this version:

```python
    use_cache = getattr(settings, "OPPS_USE_CHANGES_API", False)
    if use_cache:
        changed = drive_changes.observe(ws, client)
        if changed:
            snapshot_cache.invalidate(changed)

    cards: list[dict] = []
    card_etag_parts: list[str] = []
    for child in root_children:
        if child.mime_type != "application/vnd.google-apps.folder":
            continue
        opp_children = client.list_files(child.id)
        names = {f.name for f in opp_children}
        if not (
            "idea.md" in names
            or "state.yaml" in names
            or "run_state.yaml" in names
            or "opp.yaml" in names
            or "runs" in names
        ):
            continue

        # Fast path: cached OppCard.
        card = None
        if use_cache:
            card = snapshot_cache.get_card(ws.id, child.name)

        if card is None:
            try:
                with TouchedFileTracker() as tracker:
                    card = load_opp_card(client, opp_folder=child, opp_children=opp_children)
                _overlay_workspace_display_name(card.opp, child.name, workspace=ws)
                if use_cache:
                    snapshot_cache.set_card(
                        workspace_id=ws.id,
                        slug=child.name,
                        card=card,
                        file_ids=tracker.file_ids,
                    )
                    card_etag_parts.append(snapshot_cache.fingerprint(tracker.pairs()))
            except Exception as exc:
                log.warning(
                    "opp_list: failed to load card for %r: %s",
                    child.name, exc, exc_info=True,
                )
                cards.append({
                    "slug": child.name,
                    "display_name": child.name,
                    "labels": [],
                    "tags": [],
                    "created_at": None,
                    "created_by": None,
                    "current_run_id": None,
                    "current_phase": None,
                    "current_phase_display": None,
                    "current_step": None,
                    "current_step_display": None,
                    "status": "error",
                    "pending_gates": [],
                    "pending_gates_display": [],
                    "eval_score": None,
                    "eval_score_pct": None,
                    "eval_passed": None,
                    "last_activity_at": None,
                    "run_count": 1,
                    "error": {"message": str(exc) or exc.__class__.__name__},
                })
                continue
        else:
            _overlay_workspace_display_name(card.opp, child.name, workspace=ws)
            # Cached cards already paid the fingerprint at write time —
            # we don't have a clean way to recover the exact ETag part
            # without re-walking, so derive a stable proxy from the cached
            # value (slug + last_activity_at suffices; both update on any
            # state.yaml mutation).
            card_etag_parts.append(
                f"{child.name}:{card.last_activity_at or ''}"
            )

        if required_tags and not required_tags.issubset(set(card.opp.tags)):
            continue

        pending_slugs = list(card.pending_gate_skills)
        cards.append({
            "slug": card.opp.slug,
            "display_name": card.opp.display_name,
            "labels": card.opp.labels,
            "tags": list(card.opp.tags),
            "created_at": card.opp.created_at,
            "created_by": card.opp.created_by,
            "current_run_id": card.opp.current_run_id,
            "current_phase": card.current_phase,
            "current_phase_display": (
                phase_lookup.get(card.current_phase)
                if card.current_phase
                else None
            ),
            "current_step": card.current_step,
            "current_step_display": (
                display_lookup.get(card.current_step)
                if card.current_step
                else None
            ),
            "status": card.status,
            "pending_gates": pending_slugs,
            "pending_gates_display": [
                display_lookup.get(s, s) for s in pending_slugs
            ],
            "eval_score": card.eval_score,
            "eval_score_pct": normalize_score_pct(card.eval_score),
            "eval_passed": card.eval_passed,
            "last_activity_at": card.last_activity_at,
            "run_count": card.run_count,
        })

    if use_cache:
        import hashlib  # noqa: PLC0415
        h = hashlib.sha256()
        for part in card_etag_parts:
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        list_etag = f"sha256:{h.hexdigest()}"
        if request.headers.get("If-None-Match") == list_etag:
            return HttpResponse(status=304, headers={"ETag": list_etag})
        resp = Response(success_response(cards))
        resp["ETag"] = list_etag
        return resp

    return Response(success_response(cards))
```

(Keep the existing `try/except` for the root listing — only the per-child loop body changed.)

Note: the `import hashlib` inside the function is fine here for clarity; if you'd rather hoist it to the top of `views.py`, do that instead — both are equivalent.

- [ ] **Step 4: Run the test — expect PASS**

Run: `pytest apps/opps/tests/test_views_opp_list.py -v`
Expected: PASS (existing + new tests).

- [ ] **Step 5: Commit**

```bash
git add apps/opps/views.py apps/opps/tests/test_views_opp_list.py
git commit -m "feat(opps): wire opp list to per-card cache + list ETag

When OPPS_USE_CHANGES_API is on, GET /api/opps/ caches each OppCard via
snapshot_cache.set_card and serves cached cards on subsequent requests
unless drive_changes.observe reports the card's file_ids changed. The
overall list ETag is derived from constituent card ETags so an unchanged
list returns 304."
```

---

## Task 9: Frontend — `oppCache.ts`

**Files:**
- Create: `frontend/src/api/oppCache.ts`

Module-scoped, per-tab. Survives route mounts; dies on tab close.

- [ ] **Step 1: Implement `oppCache.ts`**

Create `frontend/src/api/oppCache.ts`:

```typescript
/**
 * Module-scoped per-tab cache for opp data, keyed by slug + runId.
 *
 * The backend serves the source-of-truth for staleness via Drive
 * Changes API + ETag. This cache simply remembers the last response
 * and its ETag so subsequent fetches send `If-None-Match` and skip the
 * body when nothing changed.
 *
 * No persistence to localStorage — correctness in the face of stale
 * localStorage isn't worth the complexity. Cache dies on tab close,
 * which is fine.
 */
import type { OppCard, OppSnapshot } from "./types";

export type Entry<T> = { data: T; etag: string };

const oppSnapshots = new Map<string, Entry<OppSnapshot>>();
const oppLists = new Map<string, Entry<OppCard[]>>();

function snapshotKey(slug: string, runId: string | null | undefined): string {
  return `${slug}:${runId ?? ""}`;
}

export function getCachedSnapshot(
  slug: string,
  runId: string | null | undefined,
): Entry<OppSnapshot> | undefined {
  return oppSnapshots.get(snapshotKey(slug, runId));
}

export function setCachedSnapshot(
  slug: string,
  runId: string | null | undefined,
  entry: Entry<OppSnapshot>,
): void {
  oppSnapshots.set(snapshotKey(slug, runId), entry);
}

export function dropOpp(slug: string): void {
  // Drop every cached entry for this slug regardless of runId.
  for (const key of Array.from(oppSnapshots.keys())) {
    if (key.startsWith(`${slug}:`)) {
      oppSnapshots.delete(key);
    }
  }
  // Also drop any list cache (a list entry contains this opp).
  oppLists.clear();
}

export function getCachedList(key: string): Entry<OppCard[]> | undefined {
  return oppLists.get(key);
}

export function setCachedList(key: string, entry: Entry<OppCard[]>): void {
  oppLists.set(key, entry);
}

export function dropList(key: string): void {
  oppLists.delete(key);
}

export function clearAll(): void {
  oppSnapshots.clear();
  oppLists.clear();
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && bunx tsc -b`
Expected: No errors. (The file is referenced from nowhere yet, but it must type-check.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/oppCache.ts
git commit -m "feat(frontend): add per-tab oppCache module

Module-scoped Map<key, {data, etag}> for OppSnapshot and OppCard[]
responses. Survives route mounts; dies on tab close. Backing for the
ETag-aware getOpp / listOpps wrappers."
```

---

## Task 10: Frontend — `apiFetchWithEtag` helper in `client.ts`

**Files:**
- Modify: `frontend/src/api/client.ts`

The existing `apiFetch` returns the unwrapped envelope payload. ETag-aware callers need access to status (so they can detect 304) and headers. We add a sibling helper that returns the lower-level shape.

- [ ] **Step 1: Add the helper**

In `frontend/src/api/client.ts`, after the existing `apiFetch` function (before the `request` helper at the bottom):

```typescript
export interface FetchWithEtagResult<T> {
  status: number;
  /** Present on 200; undefined on 304. */
  data?: T;
  /** Always present (empty string if the server didn't set one). */
  etag: string;
}

/**
 * Lower-level fetch helper for ETag-aware callers.
 *
 * Behaves like apiFetch (envelope unwrapping, auth-error redirect, CSRF
 * + workspace headers) but exposes the raw response status + ETag header
 * so callers can implement If-None-Match round-trips.
 *
 * 304 responses resolve with `{status: 304, data: undefined, etag}` —
 * the caller is expected to substitute its cached body.
 */
export async function apiFetchWithEtag<T>(
  path: string,
  init: RequestInit = {},
): Promise<FetchWithEtagResult<T>> {
  const url = buildUrl(path);
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const method = (init.method ?? "GET").toUpperCase();
  if (UNSAFE_METHODS.has(method) && !headers.has("X-CSRFToken")) {
    const token = getCsrfToken();
    if (token) headers.set("X-CSRFToken", token);
  }
  if (!headers.has("X-ACE-Workspace")) {
    const slug = getActiveWorkspaceSlug();
    if (slug) headers.set("X-ACE-Workspace", slug);
  }
  const resp = await fetch(url, { ...init, headers });

  if (resp.status === 401 || resp.status === 403) {
    const body = await resp.json().catch(() => ({})) as { detail?: string };
    const isAuthError =
      body.detail?.includes("credentials were not provided") ||
      body.detail?.includes("CSRF") ||
      body.detail?.includes("not authenticated");
    if (isAuthError) {
      const loginUrl = `${API_PREFIX}/auth/login/?next=${encodeURIComponent(window.location.pathname)}`;
      window.location.href = loginUrl;
      return new Promise<FetchWithEtagResult<T>>(() => {});
    }
  }

  const etag = resp.headers.get("ETag") ?? "";

  if (resp.status === 304) {
    return { status: 304, etag };
  }

  if (resp.status === 204) {
    return { status: 204, data: undefined, etag };
  }

  let envelope: ApiEnvelope<T>;
  try {
    envelope = await resp.json();
  } catch {
    throw new ApiError("invalid_response", `${resp.status} ${resp.statusText}`);
  }
  if (!resp.ok && (!envelope || typeof envelope !== "object")) {
    throw new ApiError(`http_${resp.status}`, `${resp.status} ${resp.statusText}`);
  }
  if (envelope && envelope.error) {
    throw new ApiError(envelope.error.code, envelope.error.message);
  }
  if (!envelope || !("data" in envelope)) {
    const detail =
      (envelope as unknown as { detail?: string })?.detail ??
      `${resp.status} ${resp.statusText}`;
    throw new ApiError(`http_${resp.status}`, detail);
  }
  if (envelope.data === null || envelope.data === undefined) {
    throw new ApiError("empty_response", "no data in envelope");
  }
  return { status: resp.status, data: envelope.data, etag };
}

/**
 * `request` variant for ETag-aware callers. Mirrors `request()` by
 * prefixing the path with `/api`.
 */
export function requestWithEtag<T>(
  path: string,
  init: RequestInit = {},
): Promise<FetchWithEtagResult<T>> {
  return apiFetchWithEtag<T>(`/api${path}`, init);
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && bunx tsc -b`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/client.ts
git commit -m "feat(frontend): add apiFetchWithEtag helper

Sibling of apiFetch that surfaces response status + ETag header so
ETag-aware callers can implement If-None-Match round-trips. Also exports
requestWithEtag, the /api-prefixed convenience."
```

---

## Task 11: Frontend — make `getOpp` / `listOpps` ETag-aware

**Files:**
- Modify: `frontend/src/api/opps.ts`

- [ ] **Step 1: Update `getOpp`**

In `frontend/src/api/opps.ts`, replace the existing `getOpp` and `listOpps`:

```typescript
import { request, requestWithEtag } from "./client";
import {
  getCachedSnapshot, setCachedSnapshot,
  getCachedList, setCachedList,
} from "./oppCache";
import type {
  CreateOppPayload,
  CreateOppResponse,
  DiscussResponse,
  LinkedChat,
  MultiRunSummary,
  OppCard,
  OppCompare,
  OppSnapshot,
  Scorecard,
  StepDetail,
  WorkingSessionResponse,
} from "./types";

export async function listOpps(
  tags?: string[],
  opts?: { force?: boolean },
): Promise<OppCard[]> {
  const params = new URLSearchParams();
  if (tags && tags.length > 0) params.set("tags", tags.join(","));
  if (opts?.force) params.set("force", "1");
  const q = params.toString();
  const path = `/opps/${q ? `?${q}` : ""}`;

  const cacheKey = `tags=${(tags ?? []).join(",")}`;
  const cached = !opts?.force ? getCachedList(cacheKey) : undefined;
  const headers: HeadersInit = cached ? { "If-None-Match": cached.etag } : {};

  const res = await requestWithEtag<OppCard[]>(path, { headers });
  if (res.status === 304 && cached) return cached.data;
  if (res.data) {
    setCachedList(cacheKey, { data: res.data, etag: res.etag });
    return res.data;
  }
  throw new Error("listOpps: unexpected empty response without cache");
}

// (createOpp, deleteOpp, updateOppTags unchanged — keep as in current file.)

export async function getOpp(
  slug: string,
  runId?: string,
  opts?: { force?: boolean },
): Promise<OppSnapshot> {
  const params = new URLSearchParams();
  if (runId) params.set("run_id", runId);
  if (opts?.force) params.set("force", "1");
  const q = params.toString();
  const path = `/opps/${encodeURIComponent(slug)}${q ? `?${q}` : ""}`;

  const cached = !opts?.force ? getCachedSnapshot(slug, runId ?? null) : undefined;
  const headers: HeadersInit = cached ? { "If-None-Match": cached.etag } : {};

  const res = await requestWithEtag<OppSnapshot>(path, { headers });
  if (res.status === 304 && cached) return cached.data;
  if (res.data) {
    setCachedSnapshot(slug, runId ?? null, { data: res.data, etag: res.etag });
    return res.data;
  }
  throw new Error("getOpp: unexpected empty response without cache");
}

// (Other functions unchanged. Keep getOppCompare, getScorecard,
// getMultiRunSummary, getStepDetail, getLinkedChats, discussStep,
// getWorkingSession, artifactBodyUrl, writeArtifact, runAction
// exactly as they are in the current file.)
```

Carefully merge the unchanged functions back in — read the current file first and keep everything except `getOpp` / `listOpps`.

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && bunx tsc -b`
Expected: No errors. (The build flag is the strict one used in the prod Docker build.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/opps.ts
git commit -m "feat(frontend): make getOpp/listOpps ETag-aware via oppCache

getOpp and listOpps now consult the per-tab cache, send If-None-Match
when a cached entry exists, and reuse the cached body on 304. Other
endpoints unchanged. The ?force=1 escape hatch still bypasses the cache
end-to-end."
```

---

## Task 12: Frontend — drop `force: true` from `useOppSocket` callback

**Files:**
- Modify: `frontend/src/pages/OppWorkbenchPage.tsx`

Background: today the `opp.updated` WebSocket event triggers `load({ silent: true, force: true })`. With the Drive Changes API in place, the next request automatically picks up the change. We just drop the cached entry and refetch normally.

- [ ] **Step 1: Update the callback**

In `frontend/src/pages/OppWorkbenchPage.tsx`, find the `useOppSocket` block (around line 90) and replace with:

```typescript
import { dropOpp } from "../api/oppCache";

// ... inside the component body, replace the existing useOppSocket call:
useOppSocket({
  slug,
  runId,
  onOppUpdated: () => {
    dropOpp(slug);
    load({ silent: true });
  },
});
```

The existing `load` callback signature already supports `{ silent: true }` (the existing call passed `{ silent: true, force: true }` — keep `silent`, drop `force`).

- [ ] **Step 2: Verify it compiles**

Run: `cd frontend && bunx tsc -b`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/OppWorkbenchPage.tsx
git commit -m "feat(frontend): drop force=true from useOppSocket on opp.updated

The Drive Changes API is now the sole invalidation mechanism. The
WebSocket event drops the per-tab cache entry and triggers a normal
refetch — backend's observe() picks up the change on the next request,
re-walks Drive, and serves a fresh snapshot.

force=true survives only on the explicit Refresh button."
```

---

## Task 13: Local smoke test (flag on)

**Files:**
- None modified — local-only verification.

Validate the end-to-end behaviour against a running dev stack before flipping the flag in prod.

- [ ] **Step 1: Start the dev stack with the flag on**

Run:
```bash
OPPS_USE_CHANGES_API=true docker compose up -d
```

Wait for `/api/health` to return 200:
```bash
until curl -fsS http://localhost:8001/api/health >/dev/null 2>&1; do sleep 2; done
echo "READY"
```

- [ ] **Step 2: Manual checklist (in the browser, with DevTools Network tab open)**

Log in as your normal user. Open `http://localhost:8001/`, navigate to an opp.

- [ ] First load of the opp: 200 response, `ETag: sha256:...` header. Note the request duration (should be the usual cold-cache 5–25 s for a real opp; faster for the seeded fakes).
- [ ] Click into a different opp, then navigate back to the first: **304 Not Modified** in DevTools, no body, sub-second total.
- [ ] Reload the page (browser refresh): the request goes out, returns 304, page renders from in-memory cache instantly.
- [ ] Click the explicit "Refresh" button (if visible) or append `?force=1` to the URL: 200 response with a fresh body, even though the ETag matches.
- [ ] Mutate Drive externally (edit a file in Google Drive web UI, or upload one via the CLI). Refresh the page. After Drive's small propagation lag (≤ 2 s), the next request returns 200 with new content + new ETag.

- [ ] **Step 3: Tear down the stack**

```bash
docker compose down
```

If anything failed: roll back the offending task by reverting that commit, fix, re-run the task's tests, re-commit. Do not skip ahead.

- [ ] **Step 4: Commit a note documenting the smoke-test result**

If everything passed, no commit needed — proceed to Task 14.

If something needed adjustment, commit the fix and document briefly:

```bash
git commit -m "fix(opps): <what was wrong> in smoke-test path"
```

---

## Task 14: Production rollout — flip the flag

**Files:**
- Modify: `config/settings/connectlabs.py`

- [ ] **Step 1: Find the right section in `connectlabs.py`**

```bash
grep -n "OPPS_\|env(" config/settings/connectlabs.py | head -20
```

Find a logical place to set defaults (near other `OPPS_*` settings, or in the env-override section).

- [ ] **Step 2: Set the default to `True` for the labs deploy**

Add (or modify) in `config/settings/connectlabs.py`:

```python
# 2026-05-08: Drive Changes API + snapshot cache redesign.
# Spec: docs/specs/2026-05-08-opp-cache-redesign.md
# Plan: docs/plans/2026-05-08-opp-cache-redesign.md
# Rolled out after smoke testing on local stack. Can be force-disabled
# via OPPS_USE_CHANGES_API=false env override on the ECS task if needed.
OPPS_USE_CHANGES_API = env.bool("OPPS_USE_CHANGES_API", default=True)
```

- [ ] **Step 3: Run the test suite once more end-to-end**

Run: `pytest apps/opps/ -v`
Expected: All passing.

- [ ] **Step 4: Commit + push + deploy**

```bash
git add config/settings/connectlabs.py
git commit -m "chore(deploy): enable OPPS_USE_CHANGES_API on labs

Activates the new Drive-Changes-API-driven snapshot cache for the labs
deploy. Smoke tested locally; no behavioural regressions expected. Can
be disabled via env var on the ECS task if anything looks off in
production."
git push
gh workflow run deploy-labs.yml --ref main -f run_migrations=false
```

Watch the deploy in `gh run watch` (or via the GitHub Actions UI). Verify on labs after deploy:
- Open an opp → 200 with ETag header (DevTools).
- Refresh → 304.

- [ ] **Step 5: Monitor for 24 hours**

Check CloudWatch logs for `drive_changes:` WARNING / ERROR entries. None expected; one or two on cold-start are fine.

If issues surface, set `OPPS_USE_CHANGES_API=false` on the ECS task definition and re-deploy. The legacy code path is still in place.

---

## Task 15: Cleanup — remove the flag and the legacy code path

**Files:**
- Modify: `apps/opps/views.py` (remove `if not getattr(settings, "OPPS_USE_CHANGES_API"...)` branches)
- Modify: `config/settings/base.py` (remove the flag)
- Modify: `config/settings/connectlabs.py` (remove the override)

**Run this only after one week of stable operation on labs.**

- [ ] **Step 1: Remove the flag check from `workbench`**

In `apps/opps/views.py`, in `workbench`, delete the `if not getattr(settings, "OPPS_USE_CHANGES_API", False):` block (the legacy path) entirely. The new path becomes unconditional. Same for `_opp_list_impl`'s `use_cache = ...` variable — remove the gate, always run the new logic.

- [ ] **Step 2: Remove the flag from settings**

In `config/settings/base.py`: delete the `OPPS_USE_CHANGES_API = env.bool(...)` line and its comment block.

In `config/settings/connectlabs.py`: delete the override.

- [ ] **Step 3: Run the full test suite**

Run: `pytest apps/opps/ -v`
Expected: All passing.

- [ ] **Step 4: Commit**

```bash
git add apps/opps/views.py config/settings/base.py config/settings/connectlabs.py
git commit -m "chore(opps): drop OPPS_USE_CHANGES_API flag and legacy cache path

The Drive-Changes-API + snapshot cache redesign has been stable on labs
for one week. Removing the gate and the 30-second-TTL fallback in the
workbench / list views. CachedDriveClient stays in place as in-load
deduplication during the cold-path walk."
```

- [ ] **Step 5: Push**

```bash
git push
gh workflow run deploy-labs.yml --ref main -f run_migrations=false
```

---

## Self-Review

Reading the spec section by section against the plan:

- **Goals — load once, instant forever, single source of truth, both layers, graceful failure.** Tasks 7–8 (backend cache + ETag), 9–11 (frontend cache + ETag), 3 (single source of truth = Drive Changes), 13 (smoke), 14 (rollout). All goals covered.
- **Non-goals — no cross-tab, no push, no eliminating cold first load.** Plan doesn't introduce any of these. ✓
- **Architecture diagram — frontend cache → backend snapshot cache + drive_changes → Drive.** Tasks 9–12 frontend, Tasks 3–4 backend modules, Tasks 7–8 wiring. ✓
- **drive_changes.observe contract — first call seeds, returns ∅; pageToken in Redis; 410 re-seeds + clears workspace.** Task 3 step 3 implements all of this. ✓
- **snapshot_cache contract — get/set/invalidate/fingerprint, get_card/set_card, clear_workspace, reverse index, inline-file_ids fallback.** Task 4 step 3. ✓
- **load_opp instrumentation — TouchedFileTracker via contextvar.** Task 5. ✓
- **View wiring — observe → invalidate → cache hit + ETag → 304 / 200.** Tasks 7 (workbench) + 8 (list). ✓
- **`?force=1` survives.** Task 7 step 3 explicitly preserves it. ✓
- **Frontend oppCache + ETag round-trip.** Tasks 9–11. ✓
- **WebSocket integration drops force=true.** Task 12. ✓
- **Failure modes — Drive failure returns ∅, 410 reseed, reverse-index miss fallback, Redis down.** Tested in Task 3 (Drive failure, 410), Task 4 (reverse-index miss), inherent (Redis down = `cache.get` returns None). ✓
- **Migration — flag default False, flip on labs, then delete.** Tasks 6, 14, 15. ✓
- **Tests — unit + integration.** Tasks 2, 3, 4, 5, 7, 8 each include explicit test code. ✓
- **Out of scope — Drive watch, pager rules, BroadcastChannel, slug-hint shortcut.** None appear in the plan. ✓

**Placeholder scan:** No "TBD", "TODO", "implement later", "fill in details", or empty test bodies. Every code step shows the actual code. The one bit of indirection is "look at the existing fixture name" in Tasks 7 and 8 — that's a navigation hint with a concrete grep command, not a placeholder.

**Type consistency:** `ChangesPage`, `TouchedFileTracker`, `current_tracker()`, `snapshot_cache.{get,set,invalidate,fingerprint,get_card,set_card,clear_workspace}`, `drive_changes.observe`, `apiFetchWithEtag`, `requestWithEtag`, `getCachedSnapshot`, `setCachedSnapshot`, `dropOpp`, `getCachedList`, `setCachedList`, `clearAll` — names are consistent across tasks where they appear.
