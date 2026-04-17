from django.db import models


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
