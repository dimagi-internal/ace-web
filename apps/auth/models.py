from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=200)
    google_sub = models.CharField(max_length=200, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    # Per-user Google Drive OAuth token cache for the ACE opp Workbench
    # (apps/opps). Encrypted via apps.opps.encryption.encrypt_token; decrypted
    # on demand in drive_credentials.ensure_fresh. TextField because the
    # ciphertext is an opaque string, not JSON.
    drive_token_cache = models.TextField(blank=True, default="")
    drive_token_refreshed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email

    def has_drive_token(self) -> bool:
        return bool(self.drive_token_cache)
