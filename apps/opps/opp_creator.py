"""Idempotent-ish opp creator. All-or-nothing within a transaction; Drive
write failures leave no Postgres state behind. If the Postgres step fails
after Drive writes succeed, the Drive folder tree is left behind as a
harmless artifact (the slug collision check will catch the retry)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import transaction

from apps.opps.drive_client import DriveClient
from apps.opps.models import OppWorkspace
from apps.sessions.models import Message, Session

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


class CreateOppError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class CreateOppResult:
    slug: str
    workspace: OppWorkspace
    working_session: Session


def create_opp(
    *,
    drive: DriveClient,
    ace_root_folder_id: str,
    owner,
    slug: str,
    display_name: str,
    idea: str,
    mode: str = "review",
    pdd: str = "",
    workspace=None,
) -> CreateOppResult:
    """Create a new opp: Drive folder + workspace row + seeded chat session.

    If ``pdd`` is non-empty, also writes it as ``pdd.md`` in the opp root.
    This lets callers that already have a PDD (e.g. the Turmeric smoke-test
    setup script) pre-populate the idea-to-pdd artifact so the workbench
    preview isn't empty on first load.

    The ``workspace`` argument scopes the slug-uniqueness check. Phase A
    keeps `OppWorkspace.slug` as the global PK so the per-workspace check
    is currently a no-op for correctness; Phase B's PK pivot is what makes
    it load-bearing. Passing the workspace anyway means callers don't have
    to change again at the Phase B cut-over.
    """
    if not SLUG_RE.match(slug):
        raise CreateOppError("invalid-slug", f"invalid slug {slug!r}")
    if mode not in ("auto", "review"):
        raise CreateOppError("invalid-mode", f"invalid mode {mode!r}")
    slug_q = OppWorkspace.objects.filter(slug=slug)
    if workspace is not None:
        slug_q = slug_q.filter(workspace=workspace)
    if slug_q.exists():
        raise CreateOppError("slug-taken", f"opp {slug!r} already exists")
    # Drive-side collision
    for child in drive.list_files(ace_root_folder_id):
        if child.name == slug:
            raise CreateOppError(
                "slug-taken", f"Drive folder {slug!r} already exists"
            )

    # Drive writes (outside the Postgres transaction). Flat layout:
    # ACE/<slug>/{idea.md, pdd.md?}. The ACE plugin (/ace:run) owns
    # state.yaml and writes it directly at the opp root when the
    # lifecycle actually starts. See
    # docs/plans/2026-04-20-drop-multi-run-simplify.md.
    opp_folder_id = drive.create_folder(ace_root_folder_id, slug)
    drive.upload_file(opp_folder_id, "idea.md", idea, "text/markdown")
    if pdd:
        drive.upload_file(opp_folder_id, "pdd.md", pdd, "text/markdown")

    # Transactional: workspace + working session + seed messages
    with transaction.atomic():
        session = Session.create_with_owner(
            owner=owner,
            title=f"{display_name} — working session",
            backend_kind="cli",
            status="active",
            source="web",
            opp_slug=slug,
            opp_run_id="run-001",
        )
        Message.objects.create(
            session=session,
            turn_index=0,
            role="system",
            sender_user=owner,
            content={"type": "system", "source": "opps-create"},
            plaintext=(
                f"Opp `{slug}` created in {mode} mode. "
                "Initial idea is in idea.md."
            ),
            status="complete",
        )
        Message.objects.create(
            session=session,
            turn_index=1,
            role="user",
            sender_user=owner,
            content={"type": "text"},
            plaintext=f"Run /ace:step idea-to-pdd for {slug}.",
            status="complete",
        )
        opp_ws = OppWorkspace.objects.create(
            slug=slug,
            display_name=display_name,
            working_session=session,
            created_by=owner,
            workspace=workspace,
        )

    return CreateOppResult(slug=slug, workspace=opp_ws, working_session=session)
