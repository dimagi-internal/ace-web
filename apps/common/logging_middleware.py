"""Adds request_id to every log record for traceability across CloudWatch Logs.

Each request is tagged with a UUID (or the caller-supplied ``X-Request-ID``
header), stored in a ``ContextVar`` so it's visible across async boundaries,
and injected into every log record via ``RequestIDFilter``. The response
echoes the id back in ``X-Request-ID`` so callers can correlate their own
logs with CloudWatch Logs Insights queries.

CloudWatch Logs Insights query example::

    fields @timestamp, request_id, levelname, name, message
    | filter levelname = "ERROR"
    | sort @timestamp desc
    | limit 20
"""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

from django.http import HttpRequest, HttpResponse
from django.utils.deprecation import MiddlewareMixin

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIDFilter(logging.Filter):
    """Injects ``request_id`` into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = _request_id_var.get()
        return True


class RequestIDMiddleware(MiddlewareMixin):
    """Assigns a request-id to each inbound request and propagates it."""

    def process_request(self, request: HttpRequest) -> None:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.request_id = rid
        _request_id_var.set(rid)

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        response["X-Request-ID"] = getattr(request, "request_id", "-")
        return response
