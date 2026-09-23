import hashlib
import secrets

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=200)
    google_sub = models.CharField(max_length=200, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email


class PersonalToken(models.Model):
    """Long-lived bearer token for CLI tools (e.g., ace-upload).
    The raw token is shown once at creation. Only the sha256 hash is stored.
    """
    user = models.ForeignKey(
        "ace_auth.User", on_delete=models.CASCADE, related_name="personal_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    #: When this stops working. NULL means never, which is what a CLI token is
    #: and why the column is nullable rather than defaulted — the long-lived
    #: tokens this model was built for have no expiry to invent.
    #:
    #: Set for a token minted from a canopy on-behalf-of assertion: that one
    #: stands for somebody who is not present, so it should outlive the answer
    #: it was minted for by as little as possible.
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "personal_tokens"

    def __str__(self):
        return f"Token {self.label!r} for {self.user_id}"

    @classmethod
    def create_for_user(cls, *, user, label: str,
                        ttl_seconds: int | None = None) -> tuple[str, "PersonalToken"]:
        from datetime import timedelta

        from django.utils import timezone

        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        expires_at = (timezone.now() + timedelta(seconds=ttl_seconds)) if ttl_seconds else None
        token = cls.objects.create(user=user, token_hash=token_hash, label=label,
                                   expires_at=expires_at)
        return raw, token

    @classmethod
    def lookup(cls, raw: str) -> "PersonalToken | None":
        from django.db.models import Q
        from django.utils import timezone

        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        try:
            # An expiry nothing checks is a comment. Filtered in the QUERY so
            # every caller of `lookup` gets it, rather than each remembering.
            return cls.objects.select_related("user").get(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()),
                token_hash=token_hash, revoked_at__isnull=True,
            )
        except cls.DoesNotExist:
            return None
