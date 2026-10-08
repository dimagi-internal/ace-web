from __future__ import annotations

from django.db import transaction

from apps.auth.models import User

from .models import StaffChange


def record_staff_change(*, actor: User | None, target: User, new_is_staff: bool,
                        source: str = "api") -> StaffChange:
    """Set `target.is_staff` and write the audit row, atomically. Callers have
    already checked who may do this and whether it is allowed."""
    with transaction.atomic():
        old = target.is_staff
        target.is_staff = new_is_staff
        target.save(update_fields=["is_staff", "updated_at"])
        return StaffChange.objects.create(
            changed_by=actor, changed_by_email=actor.email if actor else "",
            target=target, target_email=target.email,
            old_is_staff=old, new_is_staff=new_is_staff, source=source,
        )
