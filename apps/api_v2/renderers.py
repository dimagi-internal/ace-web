"""orjson-backed renderer + problem+json content-type override."""
from __future__ import annotations

import orjson
from ninja.renderers import BaseRenderer


class OrjsonRenderer(BaseRenderer):
    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return orjson.dumps(data, option=orjson.OPT_NON_STR_KEYS | orjson.OPT_UTC_Z)


class ProblemJsonRenderer(OrjsonRenderer):
    """Used by the global error handler — sets `application/problem+json`."""

    media_type = "application/problem+json"
