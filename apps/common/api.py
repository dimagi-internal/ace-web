"""Django Ninja v2 router for the common surface (health, etc.)."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from ninja import Router

from apps.common.schemas import HealthOut

router = Router(tags=["common"])


# ---------------------------------------------------------------------------
# GET /health — public health check
# ---------------------------------------------------------------------------


def get_health_status() -> dict:
    """Run database + redis health checks.

    The monkeypatch target in contract tests is this module-level function.
    """
    import redis
    from django.conf import settings
    from django.db import connection

    def _check_db():
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, type(exc).__name__

    def _check_redis():
        try:
            r = redis.from_url(
                settings.ACE_REDIS_URL,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            r.ping()
            return True, None
        except Exception as exc:  # noqa: BLE001
            return False, type(exc).__name__

    db_ok, db_err = _check_db()
    redis_ok, redis_err = _check_redis()
    healthy = db_ok and redis_ok
    return {
        "status": "ok" if healthy else "unhealthy",
        "healthy": healthy,
        "checks": {
            "database": {"ok": db_ok, "error": db_err},
            "redis": {"ok": redis_ok, "error": redis_err},
        },
    }


@router.get(
    "/health",
    auth=None,
    response={200: HealthOut, 503: HealthOut},
    summary="Health check (public)",
)
def health(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    result = get_health_status()
    payload = HealthOut.model_validate(result).model_dump(mode="json")
    status_code = 200 if result["healthy"] else 503
    return JsonResponse(payload, status=status_code)
