"""Per-opp tenancy: where an opp's assets live in each system ACE writes to.

Every opp carries one (`OppWorkspace.tenancy`); a workspace carries a
default (`Workspace.default_tenancy`) that a new opp copies when it is
created. After that the opp's copy is the truth — changing the default never
rewrites existing opps. Dimagi's own opps use exactly this model; "the shared
tenants" are just the tenancy `dimagi-team`'s opps happen to have.

Tenancy decides where ACE may WRITE, so only workspace owners change it, and
every change is recorded as a `TenancyChange` row. ACE reads an opp's
tenancy through `GET /api/w/{ws}/opps/{slug}/tenancy` when it binds a session
to that opp.

The opp's Drive root is not stored here: an opp lives under its workspace's
`drive_root_folder_id`, so the read API reports that value alongside.

Spec: docs/specs/2026-09-28-clone-and-release-design.md § Tenancy, § B.
"""
from __future__ import annotations

from pydantic import Field, field_validator

from apps.common.schemas import StrictModel

_SLUG = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"


class Tenancy(StrictModel):
    """Every field is optional: a missing one means "not set up yet", which
    ACE's preflight reports as a missing setup item rather than guessing."""

    hq_domain: str | None = Field(default=None, max_length=64, pattern=_SLUG)
    connect_pm_org: str | None = Field(default=None, max_length=64, pattern=_SLUG)
    connect_holding_org: str | None = Field(default=None, max_length=64, pattern=_SLUG)
    ocs_team: str | None = Field(default=None, max_length=64, pattern=_SLUG)
    labs_allowed_domains: list[str] | None = None

    @field_validator("labs_allowed_domains")
    @classmethod
    def _labs_domains(cls, value: list[str] | None) -> list[str] | None:
        """Stored the way Labs stores them: lower-cased with a leading "@"."""
        if value is None:
            return None
        out: list[str] = []
        for raw in value:
            domain = raw.strip().lower()
            if not domain.startswith("@"):
                domain = "@" + domain
            if "." not in domain or " " in domain or len(domain) < 4:
                raise ValueError(f"not an email domain: {raw!r}")
            if domain not in out:
                out.append(domain)
        return out


def clean(raw: dict | None) -> dict:
    """Validate a stored or submitted tenancy and drop unset fields."""
    return Tenancy.model_validate(raw or {}).model_dump(exclude_none=True)


def merge(current: dict | None, patch: dict) -> dict:
    """Apply a PATCH: a field set to None clears it, an absent field is kept."""
    merged = dict(current or {})
    for key, value in patch.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return clean(merged)


def record_change(*, workspace, opp_slug: str, user, before: dict, after: dict) -> None:
    """Audit a tenancy change. `opp_slug=""` is the workspace default."""
    if before == after:
        return
    from apps.workspaces.models import TenancyChange

    TenancyChange.objects.create(
        workspace=workspace,
        opp_slug=opp_slug,
        changed_by=user,
        before=before,
        after=after,
    )
