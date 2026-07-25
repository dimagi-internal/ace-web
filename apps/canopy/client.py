"""Outbound calls to canopy-web. Two calls only: token exchange (the app
credential's single power) and session create (so opp-linkage rules live
server-side). Everything else is browser → canopy directly."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from django.conf import settings


class CanopyError(Exception):
    def __init__(self, status: int, detail: str):
        self.status, self.detail = status, detail
        super().__init__(f"canopy {status}: {detail}")


def _post(path: str, payload: dict, *, bearer: str) -> dict:
    req = urllib.request.Request(
        f"{settings.CANOPY_BASE_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {bearer}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise CanopyError(exc.code, exc.read().decode(errors="replace")[:300]) from exc
    except urllib.error.URLError as exc:
        raise CanopyError(502, str(exc.reason)) from exc


def exchange_token(email: str, *, ttl: int = 3600) -> dict:
    return _post(
        "/api/auth/token-exchange",
        {"acting_as_email": email, "ttl_seconds": ttl},
        bearer=settings.CANOPY_APP_CREDENTIAL,
    )


def create_session(user_token: str, *, title: str, metadata: dict) -> dict:
    return _post(
        f"/api/w/{settings.CANOPY_WORKSPACE}/canopy-sessions/",
        {"agent_slug": settings.CANOPY_AGENT_SLUG, "title": title, "metadata": metadata},
        bearer=user_token,
    )
