"""ETag round-trip for v2 endpoints.

Mirrors the policy from the existing opp Workbench cache
(`docs/learnings/opp-cache-architecture.md`): ETag is sha256 of
the serialized response body with stable key ordering. Returning
`HttpResponseNotModified` short-circuits the response writer and
avoids re-serializing the body.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from django.http import HttpRequest, HttpResponseNotModified


def compute_etag(payload: Any) -> str:
    """sha256 of the canonically-serialized payload, wrapped in W/"..."."""
    serialized = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return f'W/"{digest}"'


def maybe_not_modified(request: HttpRequest, etag: str) -> HttpResponseNotModified | None:
    """Return 304 if the request's If-None-Match matches `etag`, else None."""
    inm = request.headers.get("If-None-Match")
    if inm and inm == etag:
        response = HttpResponseNotModified()
        response["ETag"] = etag
        return response
    return None
