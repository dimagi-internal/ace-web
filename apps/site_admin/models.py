from django.conf import settings
from django.db import models


class StaffChange(models.Model):
    """Audit row for a change to a user's site-admin (`User.is_staff`) flag.

    Site admin is the widest grant ace-web has, so every change — a grant, a
    revoke, or the env bootstrap (`ACE_SITE_ADMIN_EMAILS`, where `changed_by`
    is NULL) — records who made it, to whom, and old -> new. Emails are copied
    onto the row so the history still reads after a user is deleted.
    """

    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    changed_by_email = models.CharField(max_length=254, blank=True, default="")
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    target_email = models.CharField(max_length=254)
    old_is_staff = models.BooleanField()
    new_is_staff = models.BooleanField()
    #: "api" for the Site admin page, "bootstrap" for ACE_SITE_ADMIN_EMAILS.
    source = models.CharField(max_length=16, default="api")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "site_admin_staff_changes"
        ordering = ["-created_at", "-id"]
