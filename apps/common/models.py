from django.conf import settings
from django.db import models
from django_cryptography.fields import encrypt


class SystemConfig(models.Model):
    """Simple key-value store for system-level configuration.

    Used for the Claude CLI OAuth token and any future per-instance
    settings that need to survive container restarts.
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "common_system_config"

    def __str__(self):
        return self.key


class UserCredential(models.Model):
    """Per-user Claude CLI credential blob, encrypted at rest.

    blob_encrypted holds the full JSON-serialized {"claudeAiOauth": {...}}
    shape. token_prefix is the first 15 chars of the access token for
    display in the Settings UI (no full token ever re-exposed).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="cli_credential",
    )
    blob_encrypted = encrypt(models.TextField())
    token_prefix = models.CharField(max_length=20)
    uploaded_at = models.DateTimeField(auto_now=True)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    last_validation_ok = models.BooleanField(null=True)

    class Meta:
        db_table = "common_user_credential"

    def __str__(self):
        return f"{self.user.email} ({self.token_prefix}…)"
