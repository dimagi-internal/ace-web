"""Data models for the ACE web harness sessions, messages, and drafts.

These models are designed to be:
- Append-only for messages: the consumer in Plan 1B/1C is the sole writer
  and never edits a row after status='complete'. Enforcement lives in the
  consumer/serializer layer, not at the DB level.
- Multi-player native (many-to-many user-session via SessionParticipant)
- Extensible to future modules via nullable opportunity_id, ocs_agent_id, idd_ref
"""
import secrets

from django.conf import settings
from django.db import IntegrityError, models, transaction


def generate_slug() -> str:
    """8-character URL-safe random slug for sessions."""
    return secrets.token_urlsafe(6)[:8]


def generate_share_token() -> str:
    """24-byte URL-safe random token for share URLs (~32 chars)."""
    return secrets.token_urlsafe(24)


class Session(models.Model):
    BACKEND_KIND_CHOICES = [
        ("cli", "CLI (subscription)"),
        ("api", "API (key)"),
        ("mcp", "MCP-augmented API"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("archived", "Archived"),
        ("imported", "Imported"),
    ]
    SOURCE_CHOICES = [
        ("web", "Web"),
        ("upload", "Upload"),
    ]

    slug = models.CharField(max_length=32, unique=True, default=generate_slug)
    title = models.CharField(max_length=500, blank=True, default="")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_sessions"
    )
    backend_kind = models.CharField(max_length=16, choices=BACKEND_KIND_CHOICES, default="cli")
    backend_config = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default="web")

    # Placeholders for future modules. All nullable so adding modules later
    # does not require a schema migration.
    opportunity_id = models.BigIntegerField(null=True, blank=True)
    ocs_agent_id = models.CharField(max_length=200, null=True, blank=True)
    idd_ref = models.CharField(max_length=500, null=True, blank=True)
    cli_session_id = models.CharField(max_length=200, null=True, blank=True)

    # ACE opp linkage — populated when a Session is launched from the Workbench
    # via "Discuss in chat". See apps/opps and docs/specs/.
    # Strings, not FKs: Opps live in Google Drive, not Postgres.
    opp_slug = models.CharField(max_length=64, blank=True, default="")
    opp_run_id = models.CharField(max_length=64, blank=True, default="")
    opp_step_skill = models.CharField(max_length=64, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "sessions"
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["owner", "-created_at"]),
            models.Index(
                fields=["opp_slug", "opp_run_id", "opp_step_skill"],
                name="idx_session_opp_step",
            ),
        ]

    def __str__(self):
        return f"{self.slug}: {self.title or '(untitled)'}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = generate_slug()
        # Each attempt runs in its own savepoint so that a duplicate-slug
        # IntegrityError rolls back only this attempt and does not poison
        # an enclosing transaction (Django requires a fresh savepoint after
        # an IntegrityError before more queries can be issued).
        for _ in range(5):
            try:
                with transaction.atomic():
                    return super().save(*args, **kwargs)
            except IntegrityError:
                if not self.pk:
                    # Slug collision on insert — regenerate and retry
                    self.slug = generate_slug()
                    continue
                raise
        raise IntegrityError("Could not generate a unique slug after 5 attempts")

    @classmethod
    def create_with_owner(cls, *, owner, **kwargs) -> "Session":
        """Create a Session AND the owner SessionParticipant row atomically.

        The read paths (`/api/sessions/<slug>`, messages list, consumer auth)
        require the user to be a SessionParticipant. Creating a session
        without that row makes it invisible to its own owner, which caused
        a real "Loading chat…" hang in the Workbench. Every production
        call site must go through this helper; `Session.objects.create`
        direct is reserved for tests that need fine-grained participant
        control.
        """
        with transaction.atomic():
            session = cls.objects.create(owner=owner, **kwargs)
            SessionParticipant.objects.create(
                session=session, user=owner, role="owner",
            )
        return session


class SessionParticipant(models.Model):
    ROLE_CHOICES = [
        ("owner", "Owner"),
        ("editor", "Editor"),
        ("viewer", "Viewer"),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="session_memberships"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default="editor")
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "session_participants"
        constraints = [
            models.UniqueConstraint(fields=["session", "user"], name="unique_participant"),
        ]
        indexes = [
            models.Index(fields=["session", "last_seen_at"]),
        ]

    def __str__(self):
        return f"{self.user_id} in session {self.session_id} as {self.role}"


class Message(models.Model):
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
        ("tool_use", "Tool use"),
        ("tool_result", "Tool result"),
    ]
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("streaming", "Streaming"),
        ("complete", "Complete"),
        ("error", "Error"),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="messages")
    turn_index = models.IntegerField()
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
    )
    content = models.JSONField()
    plaintext = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    error_detail = models.TextField(null=True, blank=True)
    # Set explicitly by the consumer when streaming begins (Plan 1B/1C).
    # Distinct from `created_at`, which is set on row insert.
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[{self.session_id}] turn {self.turn_index} ({self.role})"

    class Meta:
        db_table = "messages"
        constraints = [
            models.UniqueConstraint(
                fields=["session", "turn_index"], name="unique_session_turn"
            ),
        ]
        ordering = ["session_id", "turn_index"]


class Draft(models.Model):
    SLOT_CHOICES = [
        ("next", "Next"),
        ("queued", "Queued"),
    ]
    STATUS_CHOICES = [
        ("open", "Open"),
        ("sent", "Sent"),
        ("discarded", "Discarded"),
    ]

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="drafts")
    creator_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_drafts"
    )
    slot = models.CharField(max_length=8, choices=SLOT_CHOICES, default="queued")
    queue_position = models.IntegerField(null=True, blank=True)
    body = models.TextField(blank=True, default="")
    version = models.IntegerField(default=0)
    last_editor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="edited_drafts"
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="open")
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_message = models.ForeignKey(
        Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="from_draft"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Draft {self.id} ({self.slot}/{self.status})"

    class Meta:
        db_table = "drafts"
        constraints = [
            # Only one open "next" draft per session.
            models.UniqueConstraint(
                fields=["session"],
                condition=models.Q(slot="next", status="open"),
                name="one_next_per_session",
            ),
        ]


class ShareToken(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="share_tokens")
    token = models.CharField(max_length=64, unique=True, default=generate_share_token)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="share_tokens"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Token {self.token[:8]}... for session {self.session_id}"

    class Meta:
        db_table = "share_tokens"


class IngestUpload(models.Model):
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name="ingest_records"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="uploads"
    )
    source_path = models.CharField(max_length=1000, blank=True, default="")
    raw_bytes = models.BigIntegerField(default=0)
    line_count = models.IntegerField(default=0)
    cli_session_id = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Upload {self.id} to session {self.session_id}"

    class Meta:
        db_table = "ingest_uploads"
