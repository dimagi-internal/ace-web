"""REST endpoints for personal token management."""
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from apps.common.envelope import error_response, success_response

from .models import PersonalToken


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def token_collection(request: Request) -> Response:
    if request.method == "POST":
        return _create_token(request)
    return _list_tokens(request)


def _create_token(request: Request) -> Response:
    label = (request.data or {}).get("label", "").strip()
    if not label:
        return Response(
            error_response(message="label is required", code="validation_error"),
            status=400,
        )
    raw, token = PersonalToken.create_for_user(user=request.user, label=label)
    return Response(
        success_response({
            "id": token.pk,
            "label": token.label,
            "raw_token": raw,
            "created_at": token.created_at.isoformat(),
        }),
        status=status.HTTP_201_CREATED,
    )


def _list_tokens(request: Request) -> Response:
    tokens = PersonalToken.objects.filter(
        user=request.user, revoked_at__isnull=True
    ).order_by("-created_at")
    items = [
        {
            "id": t.pk,
            "label": t.label,
            "created_at": t.created_at.isoformat(),
            "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        }
        for t in tokens
    ]
    return Response(success_response(items))


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def token_detail(request: Request, pk: int) -> Response:
    try:
        token = PersonalToken.objects.get(
            pk=pk, user=request.user, revoked_at__isnull=True
        )
    except PersonalToken.DoesNotExist:
        return Response(
            error_response(message="token not found", code="not_found"),
            status=404,
        )
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
    return Response(status=status.HTTP_204_NO_CONTENT)
