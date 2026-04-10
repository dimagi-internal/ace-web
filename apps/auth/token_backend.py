"""DRF authentication backend for personal bearer tokens."""
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import PersonalToken


class BearerTokenAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(f"{self.keyword} "):
            return None
        raw = auth_header[len(self.keyword) + 1:]
        token = PersonalToken.lookup(raw)
        if token is None:
            raise AuthenticationFailed("Invalid or revoked token.")
        PersonalToken.objects.filter(pk=token.pk).update(last_used_at=timezone.now())
        return (token.user, token)
