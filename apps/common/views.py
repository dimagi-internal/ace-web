import logging

import redis
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)


def _check_database() -> tuple[bool, str | None]:
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:
        return False, type(exc).__name__
    return True, None


def _check_redis() -> tuple[bool, str | None]:
    try:
        r = redis.from_url(
            settings.ACE_REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        r.ping()
    except Exception as exc:
        return False, type(exc).__name__
    return True, None


@require_GET
def health_check(request):
    db_ok, db_err = _check_database()
    redis_ok, redis_err = _check_redis()
    checks = {
        "database": {"ok": db_ok, "error": db_err},
        "redis": {"ok": redis_ok, "error": redis_err},
    }
    healthy = db_ok and redis_ok
    body = {
        "status": "ok" if healthy else "unhealthy",
        "checks": checks,
    }
    if healthy:
        return JsonResponse(body)
    failed = [name for name, c in checks.items() if not c["ok"]]
    logger.warning("health_check failing: %s", ",".join(failed))
    return JsonResponse(body, status=503)
