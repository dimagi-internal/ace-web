from django.http import HttpResponseNotModified

from apps.api_v2.etag import compute_etag, maybe_not_modified


def test_compute_etag_stable_for_same_payload():
    e1 = compute_etag({"a": 1, "b": [2, 3]})
    e2 = compute_etag({"b": [2, 3], "a": 1})  # key order shouldn't matter
    assert e1 == e2


def test_compute_etag_changes_for_different_payload():
    e1 = compute_etag({"a": 1})
    e2 = compute_etag({"a": 2})
    assert e1 != e2


def test_maybe_not_modified_returns_304_on_match(rf):
    etag = compute_etag({"a": 1})
    request = rf.get("/x", HTTP_IF_NONE_MATCH=etag)
    response = maybe_not_modified(request, etag)
    assert isinstance(response, HttpResponseNotModified)


def test_maybe_not_modified_returns_none_on_miss(rf):
    request = rf.get("/x", HTTP_IF_NONE_MATCH='"different"')
    response = maybe_not_modified(request, compute_etag({"a": 1}))
    assert response is None


def test_maybe_not_modified_returns_none_without_header(rf):
    request = rf.get("/x")
    response = maybe_not_modified(request, compute_etag({"a": 1}))
    assert response is None
