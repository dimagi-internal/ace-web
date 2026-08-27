"""`DriveClient.link_shared` — the ACL read behind the summary's access tags.

The public run-summary page tags every link it serves with who can open
it. For a Google Drive link that tag used to be a hard-coded ``public``,
and on ``spark-facilitator/20260820-0817`` it was wrong: an anonymous
``GET .../export?format=txt`` on the two documents ``design.docs``
served answered **401**, while the page an external partner was sent
rendered them "Open". This module pins the read that replaced the
assertion.

**The API shape below is not invented.** ``files.get(fields=...)`` with
``permissions`` was tried FIRST and returns an empty list for every file
on the ACE shared drive — including ones that are demonstrably
anyone-with-link readable — so a reader built on it would have called
every deliverable admin-only. ``permissions.list`` returns the real ACL.
Both branches of the fixture below are transcribed from a live read on
2026-08-26:

* the PDD (anonymously 401) — many ``user`` / ``group`` entries, no
  ``anyone``;
* the training LLO guide (anonymously reachable) — the same entries plus
  ``{'id': 'anyoneWithLink', 'type': 'anyone', 'role': 'commenter'}``.

Note the role on that entry: ``commenter``, not ``reader``. A test that
keyed on ``role == "reader"`` would have passed its own fixture and
mis-tagged the real file, which is why the check is on ``type`` alone.
"""
from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.opps.drive_cache import CachedDriveClient
from apps.opps.drive_client import DriveClient, GoogleDriveClient

# Verbatim from `permissions.list` on the two live documents, trimmed to
# the fields the reader asks for.
_INHERITED_DIMAGI_ENTRIES = [
    {"id": "00613769850732023979", "type": "user", "role": "fileOrganizer"},
    {"id": "00917134148835662773", "type": "group", "role": "fileOrganizer"},
    {"id": "17169157222438231877", "type": "group", "role": "commenter"},
]
_ANYONE_WITH_LINK = {"id": "anyoneWithLink", "type": "anyone", "role": "commenter"}


class _FakePermissions:
    def __init__(self, by_file: dict[str, object]) -> None:
        self._by_file = by_file
        self.calls: list[str] = []

    def list(self, *, fileId, fields, supportsAllDrives):  # noqa: N803
        self.calls.append(fileId)
        outcome = self._by_file.get(fileId)

        class _Req:
            def execute(_self, http=None):
                if isinstance(outcome, Exception):
                    raise outcome
                return {"permissions": outcome}

        return _Req()


class _FakeService:
    def __init__(self, by_file: dict[str, object]) -> None:
        self._permissions = _FakePermissions(by_file)

    def permissions(self):
        return self._permissions


def _client(by_file: dict[str, object]) -> GoogleDriveClient:
    client = GoogleDriveClient.__new__(GoogleDriveClient)
    client._service = _FakeService(by_file)  # type: ignore[attr-defined]
    client._thread_http = lambda: None  # type: ignore[attr-defined]
    return client


def test_an_anyone_permission_means_the_link_opens():
    client = _client({"llo-guide": [*_INHERITED_DIMAGI_ENTRIES, _ANYONE_WITH_LINK]})
    assert client.link_shared(["llo-guide"]) == {"llo-guide": True}


def test_dimagi_only_entries_do_not_make_a_link_public():
    """The audited PDD. Every entry is a real grant to a real person or
    group — and none of them helps a partner with no Google account."""
    client = _client({"pdd": list(_INHERITED_DIMAGI_ENTRIES)})
    assert client.link_shared(["pdd"]) == {"pdd": False}


def test_a_file_with_no_permissions_at_all_is_not_public():
    client = _client({"orphan": []})
    assert client.link_shared(["orphan"]) == {"orphan": False}


@pytest.mark.parametrize("role", ["reader", "commenter", "writer"])
def test_any_role_on_an_anyone_grant_counts(role):
    """Reader, commenter and writer all mean the door opens. The live
    grant was `commenter`; keying on `reader` would have mis-tagged it."""
    client = _client({"f": [{"id": "anyoneWithLink", "type": "anyone", "role": role}]})
    assert client.link_shared(["f"]) == {"f": True}


def test_a_failed_read_is_omitted_rather_than_guessed():
    """The contract that makes `unknown` possible upstream. An id the
    client could not resolve must be ABSENT — returning False would
    render an unknown link as `admin only`, and True would restore the
    original bug."""
    client = _client({"boom": RuntimeError("Drive said no")})
    assert client.link_shared(["boom"]) == {}


def test_one_failure_does_not_sink_the_batch():
    client = _client({
        "ok": [_ANYONE_WITH_LINK],
        "boom": RuntimeError("Drive said no"),
    })
    assert client.link_shared(["ok", "boom"]) == {"ok": True}


def test_ids_are_deduped_and_blanks_dropped():
    client = _client({"a": [_ANYONE_WITH_LINK]})
    assert client.link_shared(["a", "a", "", None]) == {"a": True}  # type: ignore[list-item]
    assert client._service._permissions.calls == ["a"]  # type: ignore[attr-defined]


def test_the_base_client_answers_nothing_rather_than_something_wrong():
    """A DriveClient that cannot read ACLs is valid — it simply knows
    nothing, and an empty result is exactly that. The danger would be a
    base impl that returned a default."""
    class _Minimal(DriveClient):
        def list_files(self, folder_id, recursive=False, page_size=100): ...
        def get_file(self, file_id): ...
        def get_content(self, file_id, mime_type, *, export_as=None): ...
        def create_folder(self, parent_id, name): ...
        def upload_file(self, *a, **k): ...
        def update_file(self, file_id, content, mime_type): ...
        def upload_binary(self, *a, **k): ...
        def update_binary(self, file_id, content, mime_type): ...
        def get_binary(self, file_id): ...
        def copy_file(self, *a, **k): ...
        def move_file(self, file_id, new_parent_id): ...
        def trash_folder(self, folder_id): ...
        def get_changes_start_page_token(self, drive_id=None): ...
        def list_changes(self, *a, **k): ...

    assert _Minimal().link_shared(["a", "b"]) == {}


# ─── The cache wrapper ──────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()
    yield
    cache.clear()


def test_the_cache_wrapper_serves_repeats_without_touching_drive():
    inner = _client({"a": [_ANYONE_WITH_LINK], "b": list(_INHERITED_DIMAGI_ENTRIES)})
    wrapped = CachedDriveClient(inner)
    assert wrapped.link_shared(["a", "b"]) == {"a": True, "b": False}
    assert wrapped.link_shared(["a", "b"]) == {"a": True, "b": False}
    assert inner._service._permissions.calls == ["a", "b"]  # type: ignore[attr-defined]


def test_a_false_answer_is_cached_not_treated_as_a_miss():
    """`False` is a real answer. A cache that tested truthiness would
    re-fetch every unshared file on every request — the common case."""
    inner = _client({"b": list(_INHERITED_DIMAGI_ENTRIES)})
    wrapped = CachedDriveClient(inner)
    wrapped.link_shared(["b"])
    wrapped.link_shared(["b"])
    assert inner._service._permissions.calls == ["b"]  # type: ignore[attr-defined]


def test_an_unresolved_id_is_not_cached_as_unknown():
    """A transient Drive failure must not pin `unknown` onto a link for
    the rest of the TTL — the next request gets another chance."""
    inner = _client({"boom": RuntimeError("transient")})
    wrapped = CachedDriveClient(inner)
    assert wrapped.link_shared(["boom"]) == {}
    assert wrapped.link_shared(["boom"]) == {}
    assert inner._service._permissions.calls == ["boom", "boom"]  # type: ignore[attr-defined]


def test_bypass_skips_the_cache():
    inner = _client({"a": [_ANYONE_WITH_LINK]})
    wrapped = CachedDriveClient(inner, bypass=True)
    wrapped.link_shared(["a"])
    wrapped.link_shared(["a"])
    assert inner._service._permissions.calls == ["a", "a"]  # type: ignore[attr-defined]
