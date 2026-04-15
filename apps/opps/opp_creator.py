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
) -> CreateOppResult:
    """Create a new opp: Drive folder + workspace row + seeded chat session."""
    if not SLUG_RE.match(slug):
        raise CreateOppError("invalid-slug", f"invalid slug {slug!r}")
    if mode not in ("auto", "review"):
        raise CreateOppError("invalid-mode", f"invalid mode {mode!r}")
    if OppWorkspace.objects.filter(slug=slug).exists():
        raise CreateOppError("slug-taken", f"opp {slug!r} already exists")
    # Drive-side collision
    for child in drive.list_files(ace_root_folder_id):
        if child.name == slug:
            raise CreateOppError(
                "slug-taken", f"Drive folder {slug!r} already exists"
            )

    # Drive writes (outside the Postgres transaction)
    opp_folder_id = drive.create_folder(ace_root_folder_id, slug)
    runs_folder_id = drive.create_folder(opp_folder_id, "runs")
    run1_folder_id = drive.create_folder(runs_folder_id, "run-001")
    drive.upload_file(opp_folder_id, "idea.md", idea, "text/markdown")
    state_yaml = (
        f"opp: {slug}\n"
        f"mode: {mode}\n"
        f"current_run: run-001\n"
        f"phase: design-review\n"
    )
    drive.upload_file(run1_folder_id, "state.yaml", state_yaml, "application/yaml")

    # Transactional: workspace + working session + seed messages
    with transaction.atomic():
        session = Session.objects.create(
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
        workspace = OppWorkspace.objects.create(
            slug=slug,
            display_name=display_name,
            working_session=session,
            created_by=owner,
        )

    return CreateOppResult(slug=slug, workspace=workspace, working_session=session)
