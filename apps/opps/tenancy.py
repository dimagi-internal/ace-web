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

import re

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


# ─── Who a released reviewer can open: own tenancy vs ACE's shared tenants ──
#
# The run summary tags a link `admin only` when a reviewer will NEVER get
# access to it — not merely when it needs a sign-in (Jonathan, 2026-10-03:
# "admin only was meant to mean you needed to be dimagi because the things
# weren't properly isolated. That is no longer true and you should expect
# access"). `/ace:release` invites each reviewer into the opp's OWN HQ
# project space, Connect org and ace-web workspace, and Labs dashboards are
# opened to `labs_allowed_domains`. So a link inside the opp's own tenancy
# is one a reviewer should expect to open; a link into ACE's SHARED tenants
# (the values every pre-tenancy opp was built in — migration 0006) is not.

#: ACE's shared tenants. Kept in step with
#: `apps/opps/migrations/0006_backfill_shared_tenancy.py::SHARED_TENANCY`
#: (plus the shared PM org, which that migration deliberately left unset).
SHARED_HQ_DOMAINS = frozenset({"connect-ace-prod"})
SHARED_CONNECT_ORGS = frozenset({"ace-nm-org", "ace-pm-org"})
SHARED_OCS_TEAMS = frozenset({"connect-ace"})
DIMAGI_EMAIL_DOMAINS = frozenset({"@dimagi.com", "@dimagi-ai.com"})

_HQ_DOMAIN_RE = re.compile(r"/a/([A-Za-z0-9][A-Za-z0-9_-]*)/")


def _own(value: str | None, shared: frozenset[str]) -> bool:
    return bool(value) and value not in shared


def _url_space(url: str | None) -> str | None:
    """The `/a/<space>/` segment HQ and Connect both put in their URLs."""
    if not isinstance(url, str):
        return None
    m = _HQ_DOMAIN_RE.search(url)
    return m.group(1) if m else None


class TenancyAccess:
    """Answers "will a released reviewer be able to open this link?".

    Each answer is True only when the link points INSIDE the opp's own
    tenancy. An unset field, a shared tenant, or a URL into a different
    space than the tenancy names all answer False — the honest default,
    because a reviewer is only ever invited into the opp's own tenants.
    """

    def __init__(self, tenancy: dict | None) -> None:
        t = tenancy or {}
        self.hq_domain = t.get("hq_domain")
        self.connect_orgs = {
            o for o in (t.get("connect_pm_org"), t.get("connect_holding_org")) if o
        }
        self.ocs_team = t.get("ocs_team")
        self.labs_domains = list(t.get("labs_allowed_domains") or [])

    @property
    def has_own_tenancy(self) -> bool:
        """The opp was built in its own tenants (and so gets a release)."""
        return _own(self.hq_domain, SHARED_HQ_DOMAINS) or any(
            _own(o, SHARED_CONNECT_ORGS) for o in self.connect_orgs
        )

    def hq_app(self, url: str | None) -> bool:
        space = _url_space(url)
        return _own(self.hq_domain, SHARED_HQ_DOMAINS) and (
            space is None or space == self.hq_domain
        )

    def connect(self, url: str | None) -> bool:
        own = {o for o in self.connect_orgs if _own(o, SHARED_CONNECT_ORGS)}
        if not own:
            return False
        space = _url_space(url)
        return space is None or space in own

    def ocs_console(self) -> bool:
        """Never — reviewers use the public chatbot, not the team console,
        even on an opp with its own OCS team (`/ace:release` invites no one
        to OCS)."""
        return False

    def labs(self) -> bool:
        """Labs is opened to `labs_allowed_domains`; Dimagi's own domains
        alone mean only Dimagi can open it."""
        return any(d not in DIMAGI_EMAIL_DOMAINS for d in self.labs_domains)

    def workbench(self) -> bool:
        """`/ace:release` invites reviewers to the ace-web workspace of an
        opp with its own tenancy; a shared-tenancy workspace stays internal."""
        return self.has_own_tenancy
