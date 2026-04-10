"""Service account models: credential storage, impersonation policy, audit log."""
from django.conf import settings
from django.db import models

from .encryption import decrypt, encrypt


class ServiceAccount(models.Model):
    """A non-human actor with credentials, scoped permissions, and
    controlled impersonation rights. Provider-agnostic: the credential_type
    determines which CredentialProvider interprets the stored credential."""

    CREDENTIAL_TYPES = [
        ("google_sa", "Google Service Account"),
        ("api_key", "API Key"),
    ]

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    credential_type = models.CharField(max_length=50, choices=CREDENTIAL_TYPES)
    credential_encrypted = models.TextField()
    default_scopes = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "service_accounts"

    def __str__(self):
        return f"{self.name} ({self.credential_type})"

    @property
    def credential_json(self) -> str:
        """Decrypt and return the stored credential."""
        return decrypt(self.credential_encrypted)

    @credential_json.setter
    def credential_json(self, value: str):
        """Encrypt and store a credential value."""
        self.credential_encrypted = encrypt(value)


class ImpersonationGrant(models.Model):
    """Defines who a service account is allowed to impersonate.

    subject_pattern is either an exact email ("alice@dimagi.com") or a
    domain wildcard ("*@dimagi.com"). Matching is case-insensitive.
    """

    service_account = models.ForeignKey(
        ServiceAccount, on_delete=models.CASCADE, related_name="grants",
    )
    subject_pattern = models.CharField(max_length=200)
    scopes = models.JSONField(default=list)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "impersonation_grants"

    def __str__(self):
        return f"{self.service_account.name} -> {self.subject_pattern}"

    def matches(self, email: str) -> bool:
        """Check if this grant's subject_pattern matches the given email."""
        email_lower = email.lower()
        pattern_lower = self.subject_pattern.lower()
        if pattern_lower.startswith("*@"):
            return email_lower.endswith(pattern_lower[1:])
        return email_lower == pattern_lower


class AccessLog(models.Model):
    """Audit trail for every credential use through the registry."""

    service_account = models.ForeignKey(
        ServiceAccount, on_delete=models.CASCADE, related_name="access_logs",
    )
    action = models.CharField(max_length=50)
    subject = models.CharField(max_length=200, blank=True, default="")
    scopes_used = models.JSONField(default=list)
    context = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "service_account_access_log"
        indexes = [
            models.Index(fields=["service_account", "-created_at"]),
        ]

    def __str__(self):
        target = f" as {self.subject}" if self.subject else ""
        return f"{self.service_account.name}: {self.action}{target}"
