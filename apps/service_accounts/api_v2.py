"""Django Ninja v2 router for the service_accounts (tokens) surface."""
from __future__ import annotations

from typing import Annotated

from django.http import HttpRequest, HttpResponse
from ninja import Path, Router

from apps.api_v2.auth import session_auth
from apps.api_v2.errors import TYPE_NOT_FOUND, ProblemError

from .schemas import PersonalTokenCreatedOut, PersonalTokenCreateIn, PersonalTokenOut

router = Router(auth=session_auth, tags=["tokens"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _token_to_dict(token) -> dict:
    return {
        "id": token.pk,
        "name": token.label,  # DRF uses label; v2 uses name
        "created_at": token.created_at,
        "last_used_at": token.last_used_at,
    }


# ---------------------------------------------------------------------------
# GET /tokens — list my personal tokens
# ---------------------------------------------------------------------------


def list_personal_tokens(user) -> list[dict]:
    """Return personal token dicts for the requesting user.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.auth.models import PersonalToken

    tokens = PersonalToken.objects.filter(
        user=user, revoked_at__isnull=True
    ).order_by("-created_at")
    return [_token_to_dict(t) for t in tokens]


@router.get(
    "",
    response={200: list[PersonalTokenOut]},
    summary="List my personal tokens",
)
def list_tokens(request: HttpRequest) -> HttpResponse:
    from django.http import JsonResponse

    tokens = list_personal_tokens(request.user)
    payload = [PersonalTokenOut.model_validate(t).model_dump(mode="json") for t in tokens]
    return JsonResponse(payload, safe=False)


# ---------------------------------------------------------------------------
# POST /tokens — create personal token
# ---------------------------------------------------------------------------


def create_personal_token(user, name: str) -> dict:
    """Create a personal token; returns dict including raw_token.

    The monkeypatch target in contract tests is this module-level function.
    """
    from apps.auth.models import PersonalToken

    raw, token = PersonalToken.create_for_user(user=user, label=name)
    return {
        "id": token.pk,
        "name": token.label,
        "created_at": token.created_at,
        "last_used_at": token.last_used_at,
        "raw_token": raw,
    }


@router.post(
    "",
    response={201: PersonalTokenCreatedOut},
    summary="Create a personal token",
)
def create_token(request: HttpRequest, body: PersonalTokenCreateIn) -> HttpResponse:
    from django.http import JsonResponse

    result = create_personal_token(request.user, body.name)
    payload = PersonalTokenCreatedOut.model_validate(result).model_dump(mode="json")
    return JsonResponse(payload, status=201)


# ---------------------------------------------------------------------------
# DELETE /tokens/{id} — revoke token
# ---------------------------------------------------------------------------


def revoke_personal_token(user, token_id: int) -> bool:
    """Revoke a token; returns True if found+revoked, False otherwise.

    The monkeypatch target in contract tests is this module-level function.
    """
    from django.utils import timezone

    from apps.auth.models import PersonalToken

    try:
        token = PersonalToken.objects.get(
            pk=token_id, user=user, revoked_at__isnull=True
        )
    except PersonalToken.DoesNotExist:
        return False
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
    return True


@router.delete("/{token_id}", summary="Revoke a personal token")
def delete_token(
    request: HttpRequest,
    token_id: Annotated[int, Path()],
) -> HttpResponse:
    revoked = revoke_personal_token(request.user, token_id)
    if not revoked:
        raise ProblemError(404, "Token not found", type_=TYPE_NOT_FOUND)
    return HttpResponse(status=204)
