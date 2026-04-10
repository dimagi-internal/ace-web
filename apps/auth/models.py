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

    class Meta:
        db_table = "personal_tokens"

    def __str__(self):
        return f"Token {self.label!r} for {self.user_id}"

    @classmethod
    def create_for_user(cls, *, user, label: str) -> tuple[str, "PersonalToken"]:
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        token = cls.objects.create(user=user, token_hash=token_hash, label=label)
        return raw, token

    @classmethod
    def lookup(cls, raw: str) -> "PersonalToken | None":
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        try:
            return cls.objects.select_related("user").get(
                token_hash=token_hash, revoked_at__isnull=True
            )
        except cls.DoesNotExist:
            return None
