"""Single NinjaAPI instance for the /api/v2/ namespace.

All v2 routers register against this. Routers live in
`apps/<app>/api_v2.py` and are imported below.
"""
from __future__ import annotations

import logging

from django.http import Http404, HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError

from .auth import session_auth
from .errors import (
    TYPE_AUTH,
    TYPE_INTERNAL,
    TYPE_NOT_FOUND,
    TYPE_VALIDATION,
    Problem,
    ProblemError,
)
from .renderers import OrjsonRenderer

logger = logging.getLogger(__name__)


api = NinjaAPI(
    title="ace-web API",
    version="2.0.0",
    description=(
        "Modern Pydantic-typed API surface for ace-web. "
        "Replaces the legacy `/api/` DRF endpoints. "
        "Errors are RFC 7807 application/problem+json."
    ),
    urls_namespace="api_v2",
    renderer=OrjsonRenderer(),
    docs_url=None,  # we mount Scalar at /api/v2/docs/ separately in urls.py
    openapi_url="/openapi.json",
)


def _problem_response(request: HttpRequest, problem: Problem) -> HttpResponse:
    body = problem.model_dump(exclude_none=True)
    response = HttpResponse(
        content=OrjsonRenderer().render(request, body, response_status=problem.status),
        status=problem.status,
        content_type="application/problem+json",
    )
    return response


@api.exception_handler(ProblemError)
def _on_problem_error(request: HttpRequest, exc: ProblemError) -> HttpResponse:
    problem = Problem(
        type=exc.problem_type,
        title=exc.problem_title,
        status=exc.status_code,
        detail=exc.problem_detail,
        instance=request.path,
        extras=exc.problem_extras,
    )
    return _problem_response(request, problem)


@api.exception_handler(ValidationError)
def _on_validation_error(request: HttpRequest, exc: ValidationError) -> HttpResponse:
    problem = Problem(
        type=TYPE_VALIDATION,
        title="Request validation failed",
        status=422,
        detail="One or more fields failed validation.",
        instance=request.path,
        extras={"errors": exc.errors},
    )
    return _problem_response(request, problem)


@api.exception_handler(AuthenticationError)
def _on_auth_error(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
    problem = Problem(
        type=TYPE_AUTH,
        title="Authentication required",
        status=401,
        detail="This endpoint requires an authenticated session.",
        instance=request.path,
    )
    return _problem_response(request, problem)


@api.exception_handler(HttpError)
def _on_http_error(request: HttpRequest, exc: HttpError) -> HttpResponse:
    """Bare HttpError (raised from handlers using ninja's shortcut) → problem+json."""
    problem = Problem(
        type="about:blank",
        title=exc.message if hasattr(exc, "message") else "HTTP error",
        status=exc.status_code,
        detail=str(exc) if str(exc) else None,
        instance=request.path,
    )
    return _problem_response(request, problem)


@api.exception_handler(Http404)
def _on_http404(request: HttpRequest, exc: Http404) -> HttpResponse:
    """Django Http404 (from get_object_or_404) → problem+json."""
    problem = Problem(
        type=TYPE_NOT_FOUND,
        title="Not found",
        status=404,
        detail=str(exc) if str(exc) else None,
        instance=request.path,
    )
    return _problem_response(request, problem)


@api.exception_handler(Exception)
def _on_unhandled(request: HttpRequest, exc: Exception) -> HttpResponse:
    logger.exception("Unhandled exception in v2 handler")
    problem = Problem(
        type=TYPE_INTERNAL,
        title="Internal server error",
        status=500,
        detail="An unexpected error occurred. The team has been notified.",
        instance=request.path,
    )
    return _problem_response(request, problem)


@api.get("/_auth_smoke/", auth=session_auth, response={200: dict})
def _auth_smoke(request: HttpRequest) -> dict:
    """Internal smoke route — verifies session auth works."""
    return {"email": request.user.email}
