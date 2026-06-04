"""BearerTokenAuthMiddleware DB-pressure degradation.

A saturated shared RDS surfaced as an unhandled 500 from the PersonalToken
lookup, hard-failing the ACE run path (run 20260603-2126). These pin the
retryable-503 degradation."""
import json

from django.db import OperationalError
from django.http import HttpResponse
from django.test import RequestFactory

from apps.auth.middleware import BearerTokenAuthMiddleware


def _mw(get_response=None):
    return BearerTokenAuthMiddleware(get_response or (lambda r: HttpResponse("ok")))


def _raise_operational(*_a, **_k):
    raise OperationalError("connection slots reserved for rds_reserved")


def test_call_returns_retryable_503_when_db_unavailable(monkeypatch):
    from apps.auth import models

    monkeypatch.setattr(models.PersonalToken, "lookup", _raise_operational)
    req = RequestFactory().get("/x", HTTP_AUTHORIZATION="Bearer sometoken")

    resp = _mw()(req)

    assert resp.status_code == 503
    assert resp["Retry-After"] == "5"
    assert resp["Content-Type"] == "application/problem+json"
    assert json.loads(resp.content)["detail"] == "db_unavailable"


def test_process_exception_maps_operationalerror_to_503():
    resp = _mw().process_exception(RequestFactory().get("/x"), OperationalError("boom"))
    assert resp is not None
    assert resp.status_code == 503
    assert json.loads(resp.content)["status"] == 503


def test_process_exception_ignores_other_exceptions():
    assert _mw().process_exception(RequestFactory().get("/x"), ValueError("nope")) is None


def test_no_bearer_header_passes_through_without_db():
    seen = {}

    def gr(r):
        seen["called"] = True
        return HttpResponse("ok")

    resp = _mw(gr)(RequestFactory().get("/x"))  # no Authorization header
    assert resp.status_code == 200
    assert seen.get("called") is True
