import uuid

from django.conf import settings
from django.db import models

from apps.service_accounts.encryption import decrypt, encrypt
from apps.workspaces.models import Workspace


class SlackInstallation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slack_team_id = models.CharField(max_length=32, unique=True)
    slack_team_name = models.CharField(max_length=255)
    bot_user_id = models.CharField(max_length=32)
    bot_token_encrypted = models.TextField()
    ace_workspace = models.ForeignKey(
        Workspace,
        on_delete=models.PROTECT,
        related_name="slack_installations",
    )
    installed_at = models.DateTimeField(auto_now_add=True)
    installed_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="slack_installations",
    )

    class Meta:
        db_table = "slack_installations"

    @property
    def bot_token(self) -> str:
        return decrypt(self.bot_token_encrypted)

    @bot_token.setter
    def bot_token(self, plaintext: str) -> None:
        self.bot_token_encrypted = encrypt(plaintext)

    def __str__(self):
        return f"{self.slack_team_name} ({self.slack_team_id})"


class SlackUserLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installation = models.ForeignKey(
        SlackInstallation,
        on_delete=models.CASCADE,
        related_name="user_links",
    )
    slack_user_id = models.CharField(max_length=32)
    ace_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="slack_user_links",
    )
    slack_email = models.EmailField(blank=True)
    slack_real_name = models.CharField(max_length=255, blank=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    unlinked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "slack_user_links"
        constraints = [
            models.UniqueConstraint(
                fields=["installation", "slack_user_id"],
                condition=models.Q(unlinked_at__isnull=True),
                name="uniq_slack_user_per_installation",
            ),
        ]

    def __str__(self):
        return f"{self.slack_user_id} → {self.ace_user_id}"


class SlackRunThread(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    installation = models.ForeignKey(
        SlackInstallation,
        on_delete=models.CASCADE,
        related_name="run_threads",
    )
    channel_id = models.CharField(max_length=32)
    parent_ts = models.CharField(max_length=32)
    opp_slug = models.CharField(max_length=255)
    run_id = models.CharField(max_length=64)
    ace_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="slack_run_threads",
    )
    triggered_at = models.DateTimeField(auto_now_add=True)
    phase_messages = models.JSONField(default=dict)
    parent_state_hash = models.CharField(max_length=64, blank=True, default="")
    # broken_at: Slack-side failure (channel_not_found, archived, etc.) — dispatcher stops.
    broken_at = models.DateTimeField(null=True, blank=True)
    # stopped_at: user clicked "Stop watching" or ran `/ace untrack`. Differs from
    # broken_at semantically — the run itself may still be running fine; we just
    # don't mirror it anymore. Both fields cause the sweep to skip the thread.
    stopped_at = models.DateTimeField(null=True, blank=True)
    stopped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # source: how this thread was created — "run" (Slack triggered the run via
    # /ace run), "new" (via the modal), or "track" (someone asked us to mirror
    # an existing run, possibly driven on a laptop).
    source = models.CharField(max_length=16, default="run")

    class Meta:
        db_table = "slack_run_threads"
        constraints = [
            models.UniqueConstraint(
                fields=["opp_slug", "run_id"],
                name="uniq_slack_run_thread_per_run",
            ),
        ]
        indexes = [models.Index(fields=["ace_user", "-triggered_at"])]

    def __str__(self):
        return f"{self.opp_slug}/{self.run_id} → {self.channel_id}"
