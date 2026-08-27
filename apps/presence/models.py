"""Per-user presence preference.

A dedicated model rather than a field on the user: canopy-web uses Django's
stock auth.User, which we do not extend. ace-web mirrors this model exactly
so the two backends stay symmetric.

Absence of a row means visible — the feature is on by default, and we do not
want a backfill migration to be load-bearing for correctness.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models


class PresencePreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="presence_preference",
    )
    show_presence = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "presence_preferences"

    def __str__(self):
        return f"{self.user_id}: show_presence={self.show_presence}"


def show_presence_for(user) -> bool:
    """Whether this user should be written into rosters. Defaults to True.

    Presence is designed to degrade quietly rather than raise, so a caller
    passing an AnonymousUser or an unsaved user instance (no usable primary
    key) gets the same "visible" default as a user with no preference row —
    not a crash. Callers should still gate on is_authenticated where it makes
    sense, but this helper must not depend on that ordering.
    """
    if not getattr(user, "pk", None):
        return True
    pref = PresencePreference.objects.filter(user=user).first()
    return True if pref is None else pref.show_presence
